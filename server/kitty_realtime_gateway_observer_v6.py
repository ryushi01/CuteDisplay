"""Opt-in event observer for Kitty realtime speaker identification.

Use this *beside* existing upstream/client forwarding: pass decoded event
copies to observe_client/observe_upstream and do not await recognition.
Unknown or mismatched items never unlock semantic memory. Never log PCM.
"""
import os
import asyncio
import time
try:
    from .kitty_realtime_speaker_session_v6 import SpeakerSession
    from .kitty_realtime_turn_gate_v6 import MemoryTurnGate
except ImportError:
    from kitty_realtime_speaker_session_v6 import SpeakerSession
    from kitty_realtime_turn_gate_v6 import MemoryTurnGate

try:
    from .kitty_voice_familiarity_hints_v6 import CandidateFamiliarity
except ImportError:
    try:
        from kitty_voice_familiarity_hints_v6 import CandidateFamiliarity
    except ImportError:
        CandidateFamiliarity = None

class KittySpeakerObserver:
    def __init__(self, send_to_s3, *, session=None, enabled=False,
                 url=None, token=None, on_candidate=None, on_candidate_clear=None,
                 familiarity_enabled=False):
        self.enabled = enabled is True
        self.on_candidate = on_candidate
        self.on_candidate_clear = on_candidate_clear
        self.candidate_hint = None
        self.candidate_expires = 0.0
        self.familiarity = (CandidateFamiliarity() if
            self.enabled and familiarity_enabled is True
            and CandidateFamiliarity is not None else None)
        if self.familiarity is not None:
            self.familiarity.begin_call()
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
            if self.familiarity is not None:
                self.familiarity.interrupted()

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
            # Keep the last bounded, non-authorizing hint across a short follow-up.
            # This never affects the separate per-turn authorization gate.
            if time.monotonic() >= self.candidate_expires:
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
            if self.familiarity is not None:
                self.familiarity.interrupted()

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
        # Candidate may travel to S3 as non-authorizing attribution metadata.
        # Never replace the authorized speaker_id with a voice candidate.
        if candidate == "person:shana":
            self.candidate_hint = (item, candidate)
            self.candidate_expires = time.monotonic() + 20.0
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
        if candidate == "person:shana" and sid == "unknown":
            safe_event["candidate_speaker_id"] = candidate
            safe_event["candidate_provenance"] = "voice_probable"
        # Optional non-authorizing familiarity metadata. A matching CPU
        # candidate must never become an authenticated owner speaker ID.
        if self.familiarity is not None:
            familiarity = self.familiarity.observe(
                provider_item_id=item,
                speaker_candidate=candidate,
                score=event.get("candidate_score"),
                recognizer_source="trusted_gateway_cpu",
                echo_or_overlap=event.get("playback_active",False))
            if familiarity is not None and sid=="unknown":
                safe_event["candidate_familiarity"] = familiarity["familiarity"]
                safe_event["private_memory_authorized"] = False
        try:
            await self.send_to_s3(safe_event)
            if "candidate_speaker_id" in safe_event:
                print("[KITTY_CANDIDATE_TRANSPORT] sent=true authorization=disabled", flush=True)
        except Exception as exc:
            # Optional metadata delivery must never terminate the live call.
            print("[KITTY_SPEAKER_DELIVERY] error=%s" % type(exc).__name__, flush=True)

    def authorized_recall(self, turn_id, speaker_id, provenance):
        """Legacy probable-voice recall is permanently disabled.

        The independently signed exact-turn owner/guest bridge is separate.
        A voice embedding, BLE pairing or recognized name is never an
        authorization credential for historical/private semantic memory.
        """
        print("[KITTY_RECALL_DIAG] request=skipped reason=trusted_turn_proof_required",
              flush=True)
        return None

    def complete_recall(self, epoch, turn_id, speaker_id, context):
        """Do not release private context through the old voice-probable gate."""
        return ""

    def close(self):
        self.gate.invalidate()
        if self.familiarity is not None:
            self.familiarity.end_call()
        self.candidate_hint = None
        self.candidate_expires = 0.0
        self.session.close()
