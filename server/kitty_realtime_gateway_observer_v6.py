"""Opt-in event observer for Kitty realtime speaker identification.

Use this *beside* existing upstream/client forwarding: pass decoded event
copies to observe_client/observe_upstream and do not await recognition.
Unknown or mismatched items never unlock semantic memory. Never log PCM.
"""
import os
import asyncio
try:
    from .kitty_realtime_speaker_session_v6 import SpeakerSession
    from .kitty_realtime_turn_gate_v6 import MemoryTurnGate
except ImportError:
    from kitty_realtime_speaker_session_v6 import SpeakerSession
    from kitty_realtime_turn_gate_v6 import MemoryTurnGate

class KittySpeakerObserver:
    def __init__(self, send_to_s3, *, session=None, enabled=False,
                 url=None, token=None, on_candidate=None, on_candidate_clear=None):
        self.enabled = enabled is True
        self.on_candidate = on_candidate
        self.on_candidate_clear = on_candidate_clear
        self.candidate_hint = None
        self.url = url if url is not None else os.environ.get("KITTY_SEMANTIC_SERVICE_URL", "")
        self.token = token if token is not None else os.environ.get("KITTY_MEMORY_TOKEN", "")
        self.session = session or SpeakerSession()
        self._session_factory = (lambda: SpeakerSession(identify=self.session._identify))
        self.gate = MemoryTurnGate(ttl=15.0)
        self.send_to_s3 = send_to_s3
        self.pending_stopped_item = None
        self.epoch = None
        self._active_item = None

    def observe_client(self, event):
        if not self.enabled or not isinstance(event, dict):
            return
        if event.get("type") == "input_audio_buffer.append":
            self.session.microphone_chunk(event.get("audio"))
        elif event.get("type") in ("response.cancel", "input_audio_buffer.clear"):
            self.gate.invalidate()
            self.session.close()
            self.session = self._session_factory()
            self.pending_stopped_item = None

    def observe_upstream(self, event):
        if not self.enabled or not isinstance(event, dict):
            return
        kind = event.get("type")
        if kind == "input_audio_buffer.speech_started":
            if callable(self.on_candidate_clear):
                try:
                    asyncio.create_task(self.on_candidate_clear())
                except RuntimeError:
                    pass
            self.session.speech_started()
            self.gate.invalidate()
            self.pending_stopped_item = None
            self._active_item = None
            self.candidate_hint = None
        elif kind == "input_audio_buffer.speech_stopped":
            item = event.get("item_id")
            self.session.speech_stopped(item_id=item if isinstance(item, str) else None)
            self.pending_stopped_item = item
        elif kind == "conversation.item.input_audio_transcription.completed":
            item = event.get("item_id")
            if (not isinstance(item, str) or
                    not self.pending_stopped_item or
                    item != self.pending_stopped_item):
                return
            epoch = self.gate.begin(item)
            if epoch is None:
                return
            self.epoch = epoch
            self._active_item = item
            self.session.schedule(item, self.url, self.token,
                                  self._send_recognition, timeout=12.0)
        elif kind == "error":
            self.gate.invalidate()

    async def _send_recognition(self, event):
        if (not isinstance(event, dict) or self.epoch is None or
                event.get("type") != "kitty.speaker.result" or
                event.get("item_id") != self._active_item):
            return
        sid = event.get("speaker_id", "unknown")
        item = event.get("item_id")
        confidence = event.get("confidence")
        candidate = event.get("candidate_speaker_id")
        if not self.gate.accept_speaker(self.epoch, item, sid, confidence):
            # Unknown is a legitimate negative response for a matching turn.
            if not self.gate._valid(self.epoch, item):
                return
            event = {"type": "kitty.speaker.result", "item_id": item,
                     "speaker_id": "unknown", "confidence": "unknown"}
        # Candidate metadata stays server-side. Never send candidate identity to
        # the S3 or allow it to authorize person-scoped memory.
        if candidate == "person:shana":
            self.candidate_hint = (item, candidate)
        if candidate == "person:shana" and callable(self.on_candidate):
            try:
                await self.on_candidate(item, candidate)
                print("[KITTY_CANDIDATE_CONTEXT] hinted=true memory_authorization=disabled", flush=True)
            except Exception as exc:
                print("[KITTY_CANDIDATE_CONTEXT] error=%s" % type(exc).__name__, flush=True)
        safe_event = {
            "type": "kitty.speaker.result",
            "item_id": item,
            "speaker_id": event.get("speaker_id", "unknown"),
            "confidence": event.get("confidence", "unknown"),
        }
        try:
            await self.send_to_s3(safe_event)
        except Exception as exc:
            # Optional metadata delivery must never terminate the live call.
            print("[KITTY_SPEAKER_DELIVERY] error=%s" % type(exc).__name__, flush=True)

    def authorized_recall(self, turn_id, speaker_id, provenance):
        """Return a turn token only for a matching CPU-observed voice identity.

        A self-introduction or device-submitted name cannot authorize recall.
        The caller must recheck the returned epoch after the async lookup.
        """
        if (not self.enabled or provenance != "voice_probable"
                or not isinstance(turn_id, str)
                or not isinstance(speaker_id, str)
                or self.epoch is None):
            return None
        if not self.gate.allow_recall(self.epoch, turn_id, speaker_id):
            return None
        return self.epoch

    def complete_recall(self, epoch, turn_id, speaker_id, context):
        """Consume a single result for the exact same speaker and turn."""
        if not self.enabled:
            return ""
        return self.gate.consume_context(epoch, turn_id, speaker_id, context)

    def close(self):
        self.gate.invalidate()
        self.candidate_hint = None
        self.session.close()
