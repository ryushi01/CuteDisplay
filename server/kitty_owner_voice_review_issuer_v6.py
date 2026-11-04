#!/usr/bin/env python3
"""Optional human-reviewed owner-voice LEARNING receipt issuer (source-only).

This is NOT realtime owner authentication, and its tickets CANNOT unlock
private semantic recall: they have a separate cryptographic audience.

The trusted gateway injects a PRIVATE capture lookup: only the gateway's
already-observed final S3 microphone item can be reviewed. Do not construct
that lookup from HTTP JSON, S3 sidecars or the client speaker ID. The owner
must separately enroll a P-256 public key and explicitly approve that exact
recording using user-presence-protected key access.

A signed approval is a human labeling decision, not perfect liveness proof.
Recording playback / voice cloning still need real-world impostor evaluation.
No audio data, transcripts or key material are logged or persisted.
"""
import base64
import hashlib
import secrets
import threading
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from kitty_attested_live_call_v6 import (
    SESSION, ITEM, _digest, issue_external_attestation,
)
from kitty_voice_learning_v6 import wav_quality_ok

MAX_PENDING = 16
REVIEW_TTL = 60


def _decode(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 1024:
        raise ValueError("bad signature")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def review_message(session_id, item_id, audio_hash, transcript_hash, nonce):
    """Exact canonical byte string signed in the owner's Secure Enclave."""
    return ("\n".join(("kitty-owner-voice-review-v6",
                       session_id, item_id, audio_hash,
                       transcript_hash, nonce))).encode("ascii")


class OwnerVoiceLearningApproval:
    def __init__(self, *, enrolled_public_key_pem, learning_signer_secret,
                 capture_lookup, consent_check, wall_clock=time.time):
        key = serialization.load_pem_public_key(enrolled_public_key_pem)
        if (not isinstance(key, ec.EllipticCurvePublicKey)
                or not isinstance(key.curve, ec.SECP256R1)):
            raise ValueError("enrolled P-256 owner key required")
        if (not isinstance(learning_signer_secret, bytes)
                or len(learning_signer_secret) < 32):
            raise ValueError("independent learning issuer secret required")
        if not callable(capture_lookup) or not callable(consent_check):
            raise ValueError("trusted capture + consent callbacks required")
        self._key = key
        self._secret = learning_signer_secret
        self._capture = capture_lookup
        self._consent = consent_check
        self._time = wall_clock
        self._pending = {}
        self._lock = threading.Lock()

    def _trusted_capture(self, session_id, item_id):
        # These fields MUST come from the gateway's authenticated provider
        # events and the actual S3 microphone PCM path, not requester JSON.
        try:
            record = self._capture(session_id, item_id)
        except (KeyError, ValueError, RuntimeError, OSError):
            return None
        if (not isinstance(record, dict)
                or record.get("session_id") != session_id
                or record.get("item_id") != item_id
                or record.get("source") != "gateway_observed_s3_microphone"
                or record.get("final_transcript") is not True
                or record.get("overlap") is not False
                or record.get("playback_active") is not False):
            return None
        wav = record.get("wav")
        transcript = record.get("transcript")
        if not wav_quality_ok(wav) or _digest(transcript) is None:
            return None
        return (wav, transcript)

    def request_review(self, session_id, item_id):
        """One temporary approval challenge; never issue a memory grant."""
        if (not isinstance(session_id, str) or not SESSION.fullmatch(session_id)
                or not isinstance(item_id, str) or not ITEM.fullmatch(item_id)
                or self._consent() is not True):
            return None
        record = self._trusted_capture(session_id, item_id)
        if record is None:
            return None
        wav, transcript = record
        audio_hash = hashlib.sha256(wav).hexdigest()
        transcript_hash = _digest(transcript)
        nonce = secrets.token_urlsafe(24)
        now = int(self._time())
        with self._lock:
            self._pending = {k:v for k,v in self._pending.items()
                             if now < v["expires"]}
            if len(self._pending) >= MAX_PENDING:
                return None
            self._pending[nonce] = {
                "session": session_id, "item": item_id,
                "audio": audio_hash, "transcript": transcript_hash,
                "expires": now + REVIEW_TTL}
        # The owner UI must play the locally captured sample, and make it
        # clear that approval saves a voice embedding, not private memory.
        return {"nonce":nonce,"session_id":session_id,"item_id":item_id,
                "audio_sha256":audio_hash,
                "transcript_sha256":transcript_hash,
                "expires_at":now+REVIEW_TTL}

    def approve_review(self, *, session_id, item_id, nonce, signature):
        """Single-use exact-recording user-presence signature -> learning ticket.

        A deliberate, individually reviewed recording may train a candidate
        voice profile. It does not prove the microphone speaker with certainty.
        """
        if not isinstance(nonce, str):
            return None
        now = int(self._time())
        with self._lock:
            review = self._pending.pop(nonce, None)
        if (not review or review["session"] != session_id
                or review["item"] != item_id or now >= review["expires"]
                or self._consent() is not True):
            return None
        record = self._trusted_capture(session_id, item_id)
        if record is None:
            return None
        wav, transcript = record
        audio_hash = hashlib.sha256(wav).hexdigest()
        transcript_hash = _digest(transcript)
        if (audio_hash != review["audio"]
                or transcript_hash != review["transcript"]):
            return None
        try:
            message = review_message(session_id, item_id,
                                     audio_hash, transcript_hash, nonce)
            self._key.verify(_decode(signature), message,
                             ec.ECDSA(hashes.SHA256()))
        except (InvalidSignature, ValueError, TypeError, UnicodeError):
            return None
        # Crucial: purpose="learning" is NOT accepted by AttestedLiveCall's
        # owner/history turn verification, which requires purpose="turn".
        return issue_external_attestation(
            self._secret, session_id=session_id, item_id=item_id,
            transcript=transcript, speaker_id="person:owner",
            speaker_role="owner", audio_sha256=audio_hash,
            purpose="learning", ttl=10, now=now)

    def clear(self):
        with self._lock:
            self._pending.clear()
