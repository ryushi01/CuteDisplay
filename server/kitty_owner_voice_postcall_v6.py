#!/usr/bin/env python3
"""Post-call, bounded owner voice-learning worker for Kitty V6 (not deployed).

The live realtime gateway must NOT call CPU embedding on audio forwarding.
On a completed, independently signed and exact-audio-bound OWNER turn, stage at
most one short WAV in RAM. At call end, a background worker recomputes the
signature/proof at the original admission time, loads the current consented
profile and stores only a vetted embedding using caller-provided atomic
load/save callbacks. No raw audio, transcript or grant is written to disk.

Disabled by default; do not enable without an actual trusted speaker issuer,
explicit biometric learning consent, model-version pin, and staging validation.
"""
import hashlib
import threading
import time
from datetime import datetime, timezone

from kitty_attested_live_call_v6 import verify_external_attestation
from kitty_owner_session_v6 import verify_grant
from kitty_voice_learning_v6 import (
    learn_verified_owner_utterance, wav_quality_ok,
)

MAX_HOLD_SECONDS = 14400  # discard a stale pending sample after four hours
_GLOBAL_CPU_WORKER = threading.BoundedSemaphore(1)


class PostCallOwnerVoiceLearner:
    """Single pending sample per call; never invoked by candidate matches."""

    def __init__(self, *, enabled=False, attestation_secret=None,
                 owner_grant_secret=None, model_id="", owner_profile_id="",
                 load_profile=None, save_profile=None, embedding_fn=None,
                 other_profiles_fn=None, wall_clock=time.time,
                 monotonic=time.monotonic):
        self.enabled = (
            enabled is True
            and isinstance(attestation_secret, bytes)
            and len(attestation_secret) >= 32
            and isinstance(owner_grant_secret, bytes)
            and len(owner_grant_secret) >= 32
            and owner_grant_secret != attestation_secret
            and isinstance(model_id, str) and len(model_id) >= 8
            and isinstance(owner_profile_id, str)
            and owner_profile_id not in ("", "person:owner")
            and callable(load_profile) and callable(save_profile))
        self._signer=attestation_secret
        self._owner=owner_grant_secret
        self._model=model_id
        self._profile_id=owner_profile_id
        self._load=load_profile
        self._save=save_profile
        self._embed=embedding_fn
        self._other=other_profiles_fn
        self._wall=wall_clock
        self._mono=monotonic
        self._lock=threading.Lock()
        self._call=""
        self._pending=None
        self._count=0
        self._outcome="disabled" if not self.enabled else "idle"

    @property
    def outcome(self):
        with self._lock:
            return self._outcome

    def begin_call(self, session_id):
        with self._lock:
            self._pending=None
            self._call=session_id if self.enabled and isinstance(
                session_id,str) else ""
            self._count=0
            self._outcome="ready" if self._call else "disabled"
            return bool(self._call)

    def offer_verified_owner_turn(self, *, session_id, item_id, transcript,
                                  microphone_wav, attestation, owner_grant):
        """Fast bounded admission; use from non-audio gateway observer task.

        Return only a boolean. No CPU voice-model inference or disk write.
        The signed proof must bind the exact WAV, transcript, owner and turn.
        """
        if (not self.enabled or not isinstance(microphone_wav,bytes)
                or not wav_quality_ok(microphone_wav)):
            return False
        timestamp=int(self._wall())
        digest=hashlib.sha256(microphone_wav).hexdigest()
        identity=verify_external_attestation(
            self._signer, attestation, session_id=session_id,
            item_id=item_id, transcript=transcript, now=timestamp,
            audio_sha256=digest)
        if identity!=("person:owner","owner") or not verify_grant(
                self._owner, owner_grant, session_id, now=timestamp):
            return False
        with self._lock:
            if not self._call or self._call!=session_id:
                return False
            # The most recent independently verified utterance is preferred;
            # never accumulate an unbounded history of raw recordings.
            self._pending=(session_id,item_id,transcript,microphone_wav,
                           attestation,owner_grant,timestamp,self._mono())
            self._count+=1
            self._outcome="queued"
            return True

    def cancel(self):
        """Unknown/other speaker, revoked consent or call cancellation."""
        with self._lock:
            self._pending=None
            self._outcome="discarded" if self.enabled else "disabled"

    def finish_call(self, *, background=True):
        """Consume pending in RAM after the call; no audio path work.

        Do not schedule competing model/GPU work while the Mac is speaking.
        The CPU worker is single-flight process-wide.
        """
        with self._lock:
            pending=self._pending
            self._pending=None
            self._call=""
            if not self.enabled or pending is None:
                self._outcome="no_verified_sample" if self.enabled else "disabled"
                return False
        if not _GLOBAL_CPU_WORKER.acquire(blocking=False):
            with self._lock:
                self._outcome="busy_dropped"
            return False

        def run():
            try:
                receipt=self._process(pending)
                with self._lock:
                    self._outcome="learned" if receipt else "rejected"
            except (OSError, ValueError, TypeError, PermissionError,
                    RuntimeError, KeyError, ImportError):
                with self._lock:
                    self._outcome="rejected"
            finally:
                _GLOBAL_CPU_WORKER.release()

        if background:
            try:
                threading.Thread(target=run,daemon=True,
                                 name="kitty-owner-voice-postcall").start()
                return True
            except RuntimeError:
                _GLOBAL_CPU_WORKER.release()
                with self._lock:
                    self._outcome="rejected"
                return False
        run()
        return self.outcome=="learned"

    def _process(self,pending):
        session_id,item_id,transcript,raw,ticket,grant,admitted,started=pending
        if self._mono()-started>MAX_HOLD_SECONDS:
            return False
        # Never approve a new owner retroactively at processing time.
        # The original short-lived proofs had to be valid at admission.
        admission_dt=datetime.fromtimestamp(admitted,timezone.utc)
        profile=self._load()
        if not isinstance(profile,dict):
            return False
        others=self._other() if callable(self._other) else ()
        result=learn_verified_owner_utterance(
            profile, raw, session_id=session_id, item_id=item_id,
            transcript=transcript, signed_turn_ticket=ticket,
            owner_grant=grant, speaker_signer_secret=self._signer,
            owner_grant_secret=self._owner, model_id=self._model,
            owner_profile_id=self._profile_id, embedding_fn=self._embed,
            other_profiles=others, now=admission_dt)
        # The storage callback must CAS the original profile under the same
        # file/DB lock used by live identify, rechecking consent and anchors.
        if self._save(profile, result) is not True:
            return False
        return True
