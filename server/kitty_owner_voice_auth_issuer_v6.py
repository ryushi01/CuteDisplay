#!/usr/bin/env python3
"""Opt-in source-only voice owner issuer; never expose as an HTTP endpoint.

A separately trusted Ubuntu issuer may turn multiple *fresh, authenticated S3
microphone captures* into exact, short-lived owner grants and turn tickets.
Candidate / self-introduction JSON from the phone, S3 or gateway is NOT input.
The issuer's profile loader and CPU scorer must be private, trusted callables.

This is voice-based authentication with a spoofing tradeoff, NOT equivalent to
hardware-backed owner presence. Deploy only after owner opt-in, independently
calibrated impostor/replay tests and a secure gateway-to-issuer transport.
No gateway or S3 firmware integration is performed by this module.
"""
import hashlib
import math
import time

from kitty_attested_live_call_v6 import (
    SESSION, ITEM, _digest, issue_external_attestation,
)
from kitty_owner_session_v6 import issue_grant
from kitty_voice_claims_v6 import claimed_speaker
from kitty_voice_learning_v6 import wav_quality_ok

MIN_TURNS = 3
MAX_TURNS = 128
MAX_CAPTURE_AGE = 12
MAX_BETWEEN_TURNS = 90
MIN_AUTH_SCORE = 0.970
MIN_COMPETITOR_MARGIN = 0.10


class VoiceOwnerIssuer:
    """One call's RAM-only evidence. Must run outside the realtime audio path.

    Both signing keys stay with the trusted issuer, not with the S3 or its
    regular device credential. A single *call-bound* verified turn is required
    for every private lookup, even after the three-turn warm-up.
    """

    def __init__(self, *, profile_loader, capture_lookup, score_audio,
                 grant_secret, turn_secret, owner_profile_id="person:shana",
                 clock=time.time):
        if (not callable(profile_loader) or not callable(capture_lookup)
                or not callable(score_audio)
                or not isinstance(grant_secret, bytes) or len(grant_secret) < 32
                or not isinstance(turn_secret, bytes) or len(turn_secret) < 32
                or grant_secret == turn_secret
                or not isinstance(owner_profile_id, str)
                or owner_profile_id == "person:owner"
                or not owner_profile_id.startswith("person:")):
            raise ValueError("trusted issuer configuration required")
        self._profile = profile_loader
        self._capture = capture_lookup
        self._score = score_audio
        self._grant = grant_secret
        self._turn = turn_secret
        self._owner = owner_profile_id
        self._time = clock
        self._session = None
        self._matches = []
        self._seen_items = set()
        self._seen_audio = set()

    def _policy(self):
        """Re-read opt-in on EVERY turn to honor immediate owner revocation."""
        try:
            p = self._profile()
        except (OSError, ValueError, RuntimeError, KeyError, TypeError):
            return None
        if not isinstance(p, dict):
            return None
        score = p.get("voice_owner_auth_min_score")
        margin = p.get("voice_owner_auth_min_margin")
        anchors = p.get("anchor_embeddings", p.get("embeddings"))
        if (p.get("voice_owner_auth_consent") is not True
                or p.get("owner_enrollment_id") != self._owner
                or p.get("memory_authorization") is not False
                or not isinstance(p.get("model_id"), str)
                or len(p["model_id"]) < 8
                or not isinstance(anchors, list) or len(anchors) < 3
                or type(score) not in (float, int) or not math.isfinite(score)
                or not MIN_AUTH_SCORE <= score <= 1.0
                or type(margin) not in (float, int) or not math.isfinite(margin)
                or not MIN_COMPETITOR_MARGIN <= margin <= 1.0):
            return None
        return p["model_id"], float(score), float(margin)

    def begin_call(self, session_id):
        self.end_call()
        if (not isinstance(session_id, str)
                or not SESSION.fullmatch(session_id)
                or self._policy() is None):
            return False
        self._session = session_id
        return True

    def interrupt(self):
        """A guest, uncertainty, overlap or a gap invalidates accumulated trust."""
        self._matches.clear()

    def end_call(self):
        self._session = None
        self._matches.clear()
        self._seen_items.clear()
        self._seen_audio.clear()

    def verify_microphone_turn(self, item_id):
        """Return call-bound proof only on the third+ consecutive strong turn.

        The caller supplies ONLY the provider item ID. The actual WAV and
        final transcript are retrieved privately from the authenticated
        gateway's trusted S3 capture store. Never accept caller WAV or scores.
        The CPU model work must run in a bounded background worker.
        """
        if (self._session is None or not isinstance(item_id, str)
                or not ITEM.fullmatch(item_id)
                or item_id in self._seen_items
                or len(self._seen_items) >= MAX_TURNS):
            self.interrupt()
            return None
        self._seen_items.add(item_id)
        policy = self._policy()
        if policy is None:
            self.interrupt()
            return None
        model_id, threshold, margin = policy
        now = float(self._time())
        try:
            record = self._capture(self._session, item_id)
        except (OSError, KeyError, ValueError, RuntimeError, TypeError):
            self.interrupt()
            return None
        if not isinstance(record, dict):
            self.interrupt()
            return None
        wav = record.get("wav")
        transcript = record.get("transcript")
        captured = record.get("captured_at")
        if (record.get("source") != "gateway_observed_s3_microphone"
                or record.get("authenticated_s3_session") is not True
                or record.get("final_transcript") is not True
                or record.get("overlap") is not False
                or record.get("playback_active") is not False
                or record.get("session_id") != self._session
                or record.get("item_id") != item_id
                or type(captured) not in (float, int)
                or not math.isfinite(captured)
                or not 0 <= now - captured <= MAX_CAPTURE_AGE
                or _digest(transcript) is None
                or len(transcript) > 300
                or not wav_quality_ok(wav)):
            self.interrupt()
            return None
        digest = hashlib.sha256(wav).hexdigest()
        if digest in self._seen_audio:
            self.interrupt()
            return None
        self._seen_audio.add(digest)
        try:
            result = self._score(wav)
        except (OSError, ValueError, RuntimeError, TypeError):
            self.interrupt()
            return None
        if not isinstance(result, dict):
            self.interrupt()
            return None
        confidence = result.get("score")
        runner_up = result.get("runner_up_score")
        if (result.get("source") != "issuer_local_model"
                or result.get("model_id") != model_id
                or result.get("speaker_id") != self._owner
                or result.get("candidate_only") is not False
                or type(confidence) not in (int, float)
                or type(runner_up) not in (int, float)
                or not math.isfinite(confidence)
                or not math.isfinite(runner_up)
                or not threshold <= confidence <= 1.0
                or not -1.0 <= runner_up <= confidence
                or confidence - runner_up < margin):
            self.interrupt()
            return None
        if self._matches and now - self._matches[-1] > MAX_BETWEEN_TURNS:
            self.interrupt()
        self._matches.append(now)
        self._matches = self._matches[-MIN_TURNS:]
        if len(self._matches) < MIN_TURNS:
            return None
        # A spoken name is useful to Kitty's conversational familiarity but
        # can NEVER substitute for an authenticated microphone/model match.
        name_corrob = claimed_speaker(transcript) == self._owner
        grant = issue_grant(self._grant, True, self._session,
                            now=int(now), ttl=45)
        attestation = issue_external_attestation(
            self._turn, session_id=self._session, item_id=item_id,
            transcript=transcript, speaker_id="person:owner",
            speaker_role="owner", audio_sha256=digest, now=int(now),
            purpose="turn", ttl=10)
        return {
            "session_id": self._session,
            "item_id": item_id,
            "speaker_id": "person:owner",
            "owner_grant": grant,
            "turn_attestation": attestation,
            "audio_sha256": digest,
            "name_corrob": name_corrob,
            "expires_at": int(now) + 10,
        }
