#!/usr/bin/env python3
"""Opt-in automatic owner recognition from locally captured microphone audio.

A consented locally enrolled owner profile may authorize a private memory
turn after TWO independently compared provider-correlated microphone turns.
A spoken name assists conversation identification, but cannot authenticate
someone by itself. This is a source-only optional trusted issuer, not installed
in the live gateway. No phone key copying or re-pairing is required.

WARNING: Biometric matching is vulnerable to imitation/replay and is not
security-equivalent to owner-presence authentication. Keep opt-in. Do not
turn the existing 0.960 conversational hint into a signed owner identity.
"""
import hashlib
import io
import math
import re
import time
import wave
from array import array

from kitty_attested_live_call_v6 import (
    issue_external_attestation, SESSION, ITEM, _digest,
)
from kitty_owner_session_v6 import issue_grant

OWNER_CANDIDATE = "person:shana"
OWNER_ID = "person:owner"
MIN_VOICE_SCORE = 0.970
MIN_NAMED_SCORE = 0.965
MIN_TURNS = 2
WINDOW_SECONDS = 45
MAX_WAV_BYTES = 300_000
MAX_ISSUED_TURNS = 64
NAME_INTRO = re.compile(
    r"\b(?:i am|i'm|my name is|this is)\s+(?P<name>[A-Za-z_-]{2,32})\b",
    re.I,
)


def _valid_wav(raw):
    if not isinstance(raw, bytes) or not 50 <= len(raw) <= MAX_WAV_BYTES:
        return False
    try:
        with wave.open(io.BytesIO(raw), "rb") as f:
            if (f.getframerate(), f.getnchannels(), f.getsampwidth(),
                    f.getcomptype()) != (16000, 1, 2, "NONE"):
                return False
            duration = f.getnframes() / 16000
            if not 1.5 <= duration <= 8:
                return False
            pcm = f.readframes(f.getnframes())
        if len(pcm) < 48000:
            return False
        samples = array("h")
        samples.frombytes(pcm)
        if not samples:
            return False
        power = math.fsum(float(x) * float(x) for x in samples) / len(samples)
        return power >= (0.008 * 32768) ** 2
    except (OSError, ValueError, EOFError, wave.Error):
        return False


class AutomaticVoiceOwner:
    """Per-authenticated-gateway-session opt-in owner voice verifier.

    The match_audio callback MUST compute a fresh comparison of the captured
    WAV against a locally enrolled, explicitly consented owner profile. It
    must never accept a claimed speaker name/score from S3 or a caller.
    The adapter must call observe in a separate worker, never in the audio
    event handler. Its output is evidence for a one-turn private request,
    not permission to expose all owner notes to a call-global prompt.
    """

    def __init__(
        self, *, session_id, match_audio, turn_issuer_secret, grant_secret,
        opt_in=False, enrolled_owner_profile=False,
        named_confirmation_opt_in=False, clock=time.monotonic,
        wall_clock=time.time, candidate_id=OWNER_CANDIDATE,
        threshold=MIN_VOICE_SCORE,
    ):
        self.session_id = session_id if (
            isinstance(session_id, str) and SESSION.fullmatch(session_id)) else None
        self._enabled = bool(
            opt_in is True and enrolled_owner_profile is True
            and self.session_id is not None
            and callable(match_audio)
            and isinstance(turn_issuer_secret, bytes)
            and len(turn_issuer_secret) >= 32
            and isinstance(grant_secret, bytes)
            and len(grant_secret) >= 32
            and grant_secret != turn_issuer_secret
            and candidate_id == OWNER_CANDIDATE
            and type(threshold) is float
            and MIN_VOICE_SCORE <= threshold <= 1.0
        )
        self._match = match_audio
        self._turn_secret = turn_issuer_secret if self._enabled else None
        self._grant_secret = grant_secret if self._enabled else None
        self._candidate = candidate_id
        self._threshold = threshold
        self._named_enabled = self._enabled and named_confirmation_opt_in is True
        self._clock = clock
        self._wall = wall_clock
        self._observed = []
        self._seen = set()
        self._audio_seen = set()
        self._closed = False

    @property
    def enabled(self):
        return self._enabled and not self._closed

    def close(self):
        self._closed = True
        self._observed.clear()
        self._seen.clear()
        self._audio_seen.clear()
        self._turn_secret = None
        self._grant_secret = None

    def speaker_change(self):
        """Revoke transient owner evidence if a guest/unknown turn occurs."""
        self._observed.clear()

    def observe(self, *, item_id, transcript, microphone_wav,
                trusted_provider_capture=False):
        """Maybe issue exact owner turn attestation + short owner grant.

        Standard mode: TWO distinct high-scoring local microphone matches.
        Explicit named-convenience mode: owner's spoken name + one fresh
        locally verified match at a slightly lower threshold. Name alone
        NEVER authorizes. Neither mode guarantees replay resistance.
        """
        if (not self.enabled or trusted_provider_capture is not True
                or not isinstance(item_id, str) or not ITEM.fullmatch(item_id)
                or _digest(transcript) is None or item_id in self._seen
                or len(self._seen) >= MAX_ISSUED_TURNS
                or not _valid_wav(microphone_wav)):
            self.speaker_change()
            return None
        self._seen.add(item_id)
        try:
            match = self._match(microphone_wav)
        except Exception:
            self.speaker_change()
            return None
        score = match.get("score") if isinstance(match, dict) else None
        speaker = match.get("speaker_id") if isinstance(match, dict) else None
        if (speaker != self._candidate or type(score) not in (float, int)
                or not math.isfinite(score)
                or not MIN_NAMED_SCORE <= score <= 1):
            self.speaker_change()
            return None

        now = self._clock()
        digest = hashlib.sha256(microphone_wav).hexdigest()
        if digest in self._audio_seen:
            self.speaker_change()
            return None
        self._audio_seen.add(digest)
        name = NAME_INTRO.search(transcript)
        name_confirmed = bool(
            name and name.group("name").casefold() == "shana")
        # A named confirmation is an explicitly selectable *weaker*
        # convenience setting, and still requires a real matching voice.
        # Merely claiming the owner's name cannot issue private credentials.
        named_ready = (self._named_enabled and name_confirmed
                       and score >= MIN_NAMED_SCORE)
        if not named_ready and score < self._threshold:
            self.speaker_change()
            return None
        self._observed = [
            (item, audio_hash, t)
            for item, audio_hash, t in self._observed
            if now >= t and now - t <= WINDOW_SECONDS
        ]
        if any(audio_hash == digest for _, audio_hash, _ in self._observed):
            self.speaker_change()
            return None
        self._observed.append((item_id, digest, now))
        self._observed = self._observed[-MIN_TURNS:]
        if len(self._observed) < MIN_TURNS and not named_ready:
            return None
        wall = int(self._wall())
        ticket = issue_external_attestation(
            self._turn_secret, session_id=self.session_id,
            item_id=item_id, transcript=transcript,
            speaker_id=OWNER_ID, speaker_role="owner",
            audio_sha256=digest, now=wall, purpose="turn", ttl=10,
        )
        grant = issue_grant(
            self._grant_secret, True, self.session_id, now=wall, ttl=60,
        )
        return {
            "speaker_id": OWNER_ID, "speaker_role": "owner",
            "provenance": "consented_voice_auto_v6",
            "session_id": self.session_id, "item_id": item_id,
            "transcript": transcript, "audio_sha256": digest,
            "turn_attestation": ticket, "owner_grant": grant,
            "self_introduction_confirmed": name_confirmed,
        }
