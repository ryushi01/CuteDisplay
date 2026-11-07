#!/usr/bin/env python3
"""SOURCE ONLY: non-blocking gateway-private owner proof / S3 receipt bridge.

Never install this by changing the live Open WebUI route without its separate
rollback, source-provenance, socket-identity, and hardware validation.
Only call on_provider_completed from the authenticated *provider* event loop,
and on_authenticated_s3_ack from the authenticated *S3 device* receive loop.
Neither callback may be exposed to S3/client/model self-reported identities.

The source-only bridge does not forward audio or insert model prompts. Voice
CPU scoring runs in a bounded background worker; only signed S3 receipts are
sent to the authenticated device socket. Ordinary calls remain unaffected.
"""
import asyncio
from collections import deque
import time

from kitty_attested_live_call_v6 import ITEM, AUDIO_HASH
from kitty_owner_archive_gateway_v6 import (
    OwnerArchiveGatewayCorrelator, ACK_TYPE, MAX_ITEMS_PER_CALL, MAX_OFFSET,
    MAX_TIMESTAMP_DRIFT,
)
from kitty_owner_voice_auth_issuer_v6 import VoiceOwnerIssuer

MAX_VOICE_QUEUE = 4
MAX_EARLY_ACKS = 8
MAX_EARLY_AGE = 12
VOICE_TIMEOUT = 4.0
SEND_TIMEOUT = 0.8


class AsyncOwnerReceiptBridge:
    """One-use, one-call coordinator with no new HTTP/service endpoint.

    All callbacks in the constructor are trusted gateway-internal dependencies.
    provider_transcript(item_id) looks up an immutable finalized provider
    transcript in server-controlled RAM, not a client/S3 JSON field.
    send_to_s3(event) asynchronously writes using the gateway's existing
    authenticated S3 WebSocket send path; it must never write elsewhere.
    socket_active() proves the SAME socket is still authorized and connected.
    """

    def __init__(self, *, issuer, correlator, s3_channel,
                 provider_transcript, send_to_s3, socket_active,
                 clock=time.time, monotonic=time.monotonic):
        if (not isinstance(issuer, VoiceOwnerIssuer)
                or not isinstance(correlator, OwnerArchiveGatewayCorrelator)
                or s3_channel is None
                or any(not callable(v) for v in (
                    provider_transcript, send_to_s3, socket_active,
                    clock, monotonic))):
            raise ValueError("trusted gateway-only dependencies required")
        self._issuer = issuer
        self._correlator = correlator
        self._channel = s3_channel
        self._transcript = provider_transcript
        self._send_to_s3 = send_to_s3
        self._socket_active = socket_active
        self._now = clock
        self._mono = monotonic
        self._session = None
        self._ever_started = False
        self._closed = False
        self._generation = 0
        self._items = set()
        self._acked_items = set()
        self._invalid_items = set()
        self._queue = deque()
        self._early = {}
        self._worker = None
        self._delivery = set()
        self._send_lock = asyncio.Lock()

    @property
    def active(self):
        return self._session is not None and not self._closed

    def _ready(self):
        if not self.active:
            return False
        if not self._correlator.consent_active:
            self.interrupted()
            return False
        try:
            return self._socket_active() is True
        except (OSError, RuntimeError, TypeError, ValueError):
            return False

    def begin_call(self, *, gateway_session_id, channel):
        """Return opt-in S3 capability data; caller decides whether to send.

        Must execute only once after gateway's S3 device authentication.
        Merely negotiating receipt support never enables private-memory recall.
        """
        if self._closed or self._ever_started or channel is not self._channel:
            return None
        if not self._socket_is_active(channel):
            return None
        if not self._issuer.begin_call(gateway_session_id):
            return None
        capability = self._correlator.begin_call(
            trusted_gateway_session_id=gateway_session_id, channel=channel)
        if capability is None:
            self._issuer.end_call()
            return None
        self._ever_started = True
        self._session = gateway_session_id
        return capability

    def _socket_is_active(self, channel):
        if channel is not self._channel:
            return False
        try:
            return self._socket_active() is True
        except (OSError, RuntimeError, TypeError, ValueError):
            return False

    def on_provider_completed(self, item_id):
        """O(1) callback from authenticated upstream *provider* socket.

        No audio decoding, model inference, blocking SD access, network I/O
        or long-running await in the realtime gateway event loop.
        """
        if (not self._ready() or not isinstance(item_id, str)
                or not ITEM.fullmatch(item_id) or item_id in self._items
                or len(self._items) >= MAX_ITEMS_PER_CALL
                or len(self._queue) >= MAX_VOICE_QUEUE):
            return False
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return False
        self._items.add(item_id)
        self._queue.append(item_id)
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run_voice())
        return True

    def on_authenticated_s3_ack(self, *, channel, event):
        """O(1) callback from the authenticated S3 socket, never client JSON.

        ACKs may arrive *before* the background voice scorer finishes.
        Store a bounded one-use ACK for an observed provider item and match
        it after authentic turn proof arrives. No ACK ever authorizes identity.
        """
        if (not self._socket_is_active(channel) or not self._ready()
                or not isinstance(event, dict)
                or event.get("type") != ACK_TYPE):
            return False
        item = event.get("item_id")
        if (not isinstance(item, str) or item not in self._items
                or item in self._early or item in self._acked_items
                or item in self._invalid_items):
            return False
        stamp, offset, digest = (
            event.get("stamp"), event.get("offset"),
            event.get("archive_sha256"))
        now = int(self._now())
        if (type(stamp) is not int or not 1 <= stamp <= MAX_OFFSET
                or type(offset) is not int or not 0 <= offset <= MAX_OFFSET
                or not isinstance(digest, str)
                or not AUDIO_HASH.fullmatch(digest)
                or abs(now-stamp) > MAX_TIMESTAMP_DRIFT):
            return False
        if self._correlator.observe_authenticated_s3_ack(
                channel=channel, event=event):
            self._acked_items.add(item)
            self._schedule_delivery(item)
            return True
        if len(self._early) >= MAX_EARLY_ACKS:
            return False
        self._acked_items.add(item)
        self._early[item] = (float(self._mono()), {
            "type": ACK_TYPE, "item_id": item, "stamp": stamp,
            "offset": offset, "archive_sha256": digest})
        return True

    def _schedule_delivery(self, item):
        if not self._ready():
            return
        generation = self._generation
        task = asyncio.create_task(self._deliver(item, generation))
        self._delivery.add(task)
        task.add_done_callback(self._delivery.discard)

    async def _run_voice(self):
        try:
            while self._queue and self._ready():
                item = self._queue.popleft()
                generation = self._generation
                try:
                    # Does not block provider/receive loops even during CPU
                    # contention. On timeout, fail closed for the whole call;
                    # a Python thread may finish later, but cannot deliver.
                    evidence = await asyncio.wait_for(
                        asyncio.to_thread(self._issuer.verify_microphone_turn, item),
                        timeout=VOICE_TIMEOUT)
                except (OSError, RuntimeError, ValueError, TypeError,
                        TimeoutError, asyncio.TimeoutError):
                    self.close()
                    return
                if not self._ready() or generation != self._generation:
                    continue
                if not isinstance(evidence, dict):
                    self._early.pop(item, None)
                    continue
                if (evidence.get("session_id") != self._session
                        or evidence.get("item_id") != item
                        or evidence.get("speaker_id") != "person:owner"):
                    self._early.pop(item, None)
                    continue
                try:
                    transcript = self._transcript(item)
                except (OSError, RuntimeError, KeyError, ValueError, TypeError):
                    self._early.pop(item, None)
                    continue
                if not isinstance(transcript, str):
                    self._early.pop(item, None)
                    continue
                if not self._correlator.register_owner_turn(
                        item_id=item, transcript=transcript,
                        owner_grant=evidence.get("owner_grant"),
                        turn_attestation=evidence.get("turn_attestation"),
                        audio_sha256=evidence.get("audio_sha256")):
                    self._early.pop(item, None)
                    continue
                buffered = self._early.pop(item, None)
                if buffered is None:
                    continue
                at, ack = buffered
                if (float(self._mono()) - at > MAX_EARLY_AGE
                        or not self._ready()):
                    continue
                if self._correlator.observe_authenticated_s3_ack(
                        channel=self._channel, event=ack):
                    self._schedule_delivery(item)
        except asyncio.CancelledError:
            return

    async def _deliver(self, item, generation):
        if not self._ready() or generation != self._generation:
            return
        # Only the trusted correlator may mint this event.
        receipt = self._correlator.receipt_from_authenticated_ack(item)
        if receipt is None or not self._ready() or generation != self._generation:
            return
        try:
            async with self._send_lock:
                if not self._ready() or generation != self._generation:
                    return
                await asyncio.wait_for(
                    self._send_to_s3(receipt), timeout=SEND_TIMEOUT)
        except (OSError, RuntimeError, TypeError, ValueError, TimeoutError,
                asyncio.TimeoutError):
            # Do not retry an already minted receipt: S3 may have stored it.
            # A delayed, verified SD export is the authoritative outcome.
            return

    def interrupted(self):
        """Guest, playback, overlap, barge-in, provider failure or cancel."""
        if not self.active:
            return
        self._generation += 1
        self._invalid_items.update(self._items)
        self._early.clear()
        self._queue.clear()
        self._issuer.interrupt()
        self._correlator.cancelled_or_guest()

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._generation += 1
        self._session = None
        self._queue.clear()
        self._early.clear()
        self._items.clear()
        self._acked_items.clear()
        self._invalid_items.clear()
        self._correlator.end_call()
        self._issuer.end_call()
        if self._worker is not None:
            self._worker.cancel()
        for task in tuple(self._delivery):
            task.cancel()
        self._delivery.clear()

    async def drain(self):
        """Join existing background tasks (maintenance/tests ONLY, never audio)."""
        worker = self._worker
        if worker is not None:
            await asyncio.gather(worker, return_exceptions=True)
        tasks = tuple(self._delivery)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
