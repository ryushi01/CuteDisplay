#!/usr/bin/env python3
"""Source-only gateway event adapter for Kitty V6 attested live continuity.

Not installed in the actual Open WebUI gateway. This module does NOT
identify people, authorize owner history from a voice score, or send any
content to a model. The caller must feed observe_upstream() ONLY decoded
events from the authenticated upstream provider socket, not S3/client JSON.

The actual Ubuntu gateway reports completed transcriptions but no explicit
VAD speech-start/stop literals. We therefore allow a completed provider item
to become the observation anchor when no VAD stop was seen. This alone never
authorizes memory: the separate trusted issuer must still sign the exact
server-generated session ID, provider item ID and transcript digest.
"""
from kitty_attested_live_call_v6 import AttestedLiveCall
from kitty_turn_context_v6 import attested_voice_turn_context


class GatewayTurnAdapter:
    """Passive state machine with no network or user-visible forwarding."""

    def __init__(self, *, attested_call=None):
        self.call = attested_call if isinstance(
            attested_call, AttestedLiveCall) else AttestedLiveCall()
        self._stopped_item = None
        self._stop_without_item = False
        self._started = False
        self._closed = False

    @property
    def session_id(self):
        return self.call.session_id

    def observe_client(self, event):
        """Only cancel/clear; never trust identity or a client-supplied ticket."""
        if self._closed or not isinstance(event, dict):
            return
        if event.get("type") in (
                "response.cancel", "input_audio_buffer.clear",
                "conversation.item.delete"):
            self.unknown_turn()

    def observe_upstream(self, event):
        """Provider events only. Never invoke with client-provided objects."""
        if self._closed or not isinstance(event, dict):
            return False
        kind = event.get("type")
        if kind == "input_audio_buffer.speech_started":
            self.call.upstream_speech_started()
            self._stopped_item = None
            self._stop_without_item = False
            self._started = True
            return False
        if kind == "input_audio_buffer.speech_stopped":
            item = event.get("item_id")
            if not self._started:
                self.call.upstream_speech_started()
            self._started = False
            self._stop_without_item = not (
                isinstance(item, str) and item.strip())
            self._stopped_item = item if not self._stop_without_item else None
            if self._stopped_item is not None:
                return self.call.upstream_speech_stopped(self._stopped_item)
            self.call.unknown_turn()
            return False
        if kind == "conversation.item.input_audio_transcription.completed":
            item = event.get("item_id")
            transcript = event.get("transcript")
            if (not isinstance(item, str)
                    or not isinstance(transcript, str)):
                self.unknown_turn()
                return False
            if self._stop_without_item:
                self.unknown_turn()
                return False
            if self._stopped_item is not None:
                if item != self._stopped_item:
                    self.unknown_turn()
                    return False
            else:
                # The live gateway has no explicit VAD handler markers.
                # Trust only the provider's completed item ID as an anchor,
                # never the identity. A signed speaker ticket is still needed.
                self.call.upstream_speech_started()
                if not self.call.upstream_speech_stopped(item):
                    self.unknown_turn()
                    return False
            self._stopped_item = None
            self._started = False
            return self.call.upstream_transcript_completed(item, transcript)
        if kind in ("error", "conversation.item.input_audio_transcription.failed"):
            self.unknown_turn()
        return False

    def verify_independent_turn(self, item_id, signed_ticket, *,
                                owner_grant=None, audio_sha256=None):
        """Only a separately verified issuer may supply signed_ticket.

        Do not call this method on a client speaker-result event or an
        S3-requested speaker identity. A bearer token is not human proof.
        """
        if self._closed:
            return False
        return self.call.verify_turn(
            item_id, signed_ticket, owner_grant=owner_grant,
            audio_sha256=audio_sha256)

    async def context_for_item(self, item_id, *, service_url="",
                               service_token="", owner_grant=None,
                               include_owner_history=False, owner_lookup=None):
        if self._closed:
            return ""
        return await attested_voice_turn_context(
            self.call, item_id, service_url, service_token,
            owner_grant, include_owner_history=include_owner_history,
            owner_lookup=owner_lookup)

    def unknown_turn(self):
        self._stopped_item = None
        self._stop_without_item = False
        self._started = False
        self.call.unknown_turn()

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.unknown_turn()
        self.call.end_call()
