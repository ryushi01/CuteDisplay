#!/usr/bin/env python3
"""SOURCE ONLY: gateway socket-provenance gate for opt-in owner SD receipts.

No live route patch/deployment, no audio manipulation, no model prompts,
no owner-history enablement. The actual Open WebUI route must supply TWO
independently authenticated socket *objects*: upstream provider and S3 device.

This gate never trusts a 'source', 'speaker', 'owner' or 'channel_id' JSON
field. Client/S3 data can only contribute a signed archive ACK after the
trusted voice issuer separately verifies an exact upstream item and S3 mic.
"""
from kitty_attested_live_call_v6 import ITEM
from kitty_owner_archive_gateway_v6 import ACK_TYPE
from kitty_owner_receipt_async_bridge_v6 import AsyncOwnerReceiptBridge

MAX_PROVIDER_ITEMS = 128
MAX_TRANSCRIPT_BYTES = 255
PROVIDER_COMPLETE = "conversation.item.input_audio_transcription.completed"
PROVIDER_FAIL = "conversation.item.input_audio_transcription.failed"
PROVIDER_ERRORS = {PROVIDER_FAIL, "error"}
DEVICE_INTERRUPTS = {"response.cancel", "input_audio_buffer.clear",
                     "conversation.item.delete"}


class ProviderTranscriptEvidence:
    """Bounded volatile provider-only final transcript store; no disk writes.

    The gateway instantiates this store first and passes store.lookup to
    AsyncOwnerReceiptBridge(provider_transcript=...). Never initialize it
    from a client/S3 event stream. Store each provider item exactly once.
    """

    def __init__(self, *, provider_socket):
        if (provider_socket is None or isinstance(
                provider_socket, (str, bytes, int, float, bool,
                                  dict, list, tuple, set))):
            raise ValueError("private provider socket reference required")
        self._provider = provider_socket
        self._items = {}
        self._seen = set()
        self._closed = False

    def observe(self, *, channel, event):
        """Only authenticated provider transcription completions are accepted."""
        if (self._closed or channel is not self._provider
                or not isinstance(event, dict)
                or event.get("type") != PROVIDER_COMPLETE):
            return None
        item, transcript = event.get("item_id"), event.get("transcript")
        if (not isinstance(item, str) or not ITEM.fullmatch(item)
                or item in self._seen or len(self._seen) >= MAX_PROVIDER_ITEMS
                or not isinstance(transcript, str)
                or not 1 <= len(transcript.encode("utf-8")) <= MAX_TRANSCRIPT_BYTES
                or any(ch in transcript for ch in ("\t", "\r", "\n", "\x00"))):
            return None
        self._seen.add(item)
        self._items[item] = transcript
        return item

    def lookup(self, item_id):
        """Read-only internal lookup, NEVER a client JSON lookup API."""
        return self._items.get(item_id) if not self._closed else None

    def invalidate(self):
        # Allow new provider item IDs after a cancelled turn, but never
        # allow old item IDs or transcripts to re-enter via a replay.
        self._items.clear()

    def close(self):
        self._closed = True
        self._items.clear()
        self._seen.clear()


class OwnerGatewayEventGate:
    """One-call, sync O(1) event provenance gate.

    Exactly one AsyncOwnerReceiptBridge (configured with this store.lookup)
    must be used. Neither socket input should be forwarded from an
    untrusted browser or text/model message.
    """

    def __init__(self, *, bridge, provider_store, provider_socket, s3_socket):
        if (not isinstance(bridge, AsyncOwnerReceiptBridge)
                or not isinstance(provider_store, ProviderTranscriptEvidence)
                or provider_socket is None or s3_socket is None
                or provider_socket is s3_socket
                or provider_store._provider is not provider_socket
                or provider_store._closed
                or bridge._channel is not s3_socket
                or bridge._correlator._device is not s3_socket
                or getattr(bridge._transcript, "__self__", None) is not provider_store
                or getattr(bridge._transcript, "__func__", None)
                   is not ProviderTranscriptEvidence.lookup):
            raise ValueError("distinct authenticated gateway socket handles required")
        self._bridge = bridge
        self._store = provider_store
        self._provider = provider_socket
        self._s3 = s3_socket
        self._closed = False

    @property
    def owner_history_enabled(self):
        # Owner-private semantic recall remains disabled until separate
        # hardware biometric/anti-replay deployment validation.
        return False

    def from_provider(self, *, channel, event):
        if (self._closed or channel is not self._provider
                or not self._bridge.active or not isinstance(event, dict)):
            return False
        kind = event.get("type")
        if kind in PROVIDER_ERRORS:
            self.interrupted()
            return False
        if kind != PROVIDER_COMPLETE:
            return False
        item = self._store.observe(channel=channel, event=event)
        if item is None:
            # A repeated or structurally malformed provider transcript is
            # not grounds for owner verification; drop previous pending.
            self.interrupted()
            return False
        if self._bridge.on_provider_completed(item):
            return True
        self._store.invalidate()
        self.interrupted()
        return False

    def from_s3(self, *, channel, event):
        """Only the authenticated device receive loop can route an ACK."""
        if (self._closed or channel is not self._s3
                or not self._bridge.active or not isinstance(event, dict)):
            return False
        kind = event.get("type")
        if kind in DEVICE_INTERRUPTS:
            self.interrupted()
            return False
        if kind != ACK_TYPE:
            # Device speaker results and claimed names are never human proof.
            return False
        return self._bridge.on_authenticated_s3_ack(channel=channel, event=event)

    def interrupted(self):
        if not self._closed:
            self._store.invalidate()
            self._bridge.interrupted()

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._store.close()
        self._bridge.close()
