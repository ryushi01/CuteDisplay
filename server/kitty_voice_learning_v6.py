#!/usr/bin/env python3
"""Kitty V6 gradual, owner-consented voice adaptation — source-only.

After an independently attested owner microphone turn, learn a small *derived*
speaker embedding off the audio path. Voice samples never authenticate anyone
or grant memory access. Do not call this with "voice_probable" or guessed IDs.

The original enrollment anchors are immutable; the profile must explicitly opt
in to *automatic* adaptation and pin the encoder model. No model downloads,
microphone captures, cloud calls or profile writes occur in this module.
"""
import hashlib
import io
import math
import statistics
import wave
from datetime import datetime, timezone

from kitty_attested_live_call_v6 import verify_external_attestation
from kitty_owner_session_v6 import verify_grant
from kitty_voice_adaptation_policy_v6 import propose, _unit, MIN_SCORE

MAX_WAV_BYTES = 300000
MAX_CLIPPED_FRACTION = 0.02
MIN_RMS = 0.008
MAX_RMS = 0.7
MIN_COMPETITOR_MARGIN = 0.10


def _timestamp(now):
    if now is None:
        now = datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("timezone_aware_datetime_required")
    return now.astimezone(timezone.utc)


def wav_quality_ok(raw):
    """Check bounded 16-kHz microphone PCM; not a spoof/liveness detector."""
    if not isinstance(raw, bytes) or not 1024 < len(raw) <= MAX_WAV_BYTES:
        return False
    try:
        with wave.open(io.BytesIO(raw), "rb") as wav:
            if ((wav.getframerate(), wav.getnchannels(), wav.getsampwidth())
                    != (16000, 1, 2)):
                return False
            frames = wav.getnframes()
            if not 1.5 <= frames / 16000 <= 8:
                return False
            payload = wav.readframes(frames)
            if len(payload) != frames * 2:
                return False
        # No third-party libs or audio buffering beyond this sample.
        import array
        samples = array.array("h")
        samples.frombytes(payload)
        if not samples:
            return False
        if __import__("sys").byteorder != "little":
            samples.byteswap()
        rms = math.sqrt(sum(float(x)*float(x) for x in samples)
                        / len(samples)) / 32768.0
        clipped = sum(abs(x) >= 32700 for x in samples) / len(samples)
        return MIN_RMS <= rms <= MAX_RMS and clipped < MAX_CLIPPED_FRACTION
    except (OSError, ValueError, EOFError, wave.Error):
        return False


def _median_similarity(vec, anchors):
    values=[]
    for anchor in anchors:
        normalized=_unit(anchor)
        if len(normalized)!=len(vec):
            raise ValueError("embedding_dimension_mismatch")
        values.append(math.fsum(a*b for a,b in zip(vec,normalized)))
    if len(values)<3:
        raise ValueError("not_enough_anchors")
    return statistics.median(values)


def learn_verified_owner_utterance(profile, raw_wav, *, session_id, item_id,
                                    transcript, signed_turn_ticket,
                                    owner_grant, speaker_signer_secret,
                                    owner_grant_secret, model_id,
                                    owner_profile_id, embedding_fn=None,
                                    other_profiles=(), now=None):
    """Return a NEW adaptive profile, never mutate the original or authorize.

    Must be called with server-observed WAV and upstream item/transcript from
    the same turn. "signed_turn_ticket" must be issued by an independent
    trusted speaker verifier with the exact *audio hash*, never by the voice
    candidate matcher or the owner login verifier alone.
    """
    if not isinstance(profile,dict):
        raise ValueError("invalid_profile")
    if (profile.get("consent") != "local_explicit_enrollment"
            or profile.get("adaptive_learning_consent") is not True):
        raise PermissionError("automatic_voice_learning_requires_separate_consent")
    if (not isinstance(model_id,str) or len(model_id)<8
            or profile.get("model_id") != model_id
            or not isinstance(owner_profile_id,str)
            or not owner_profile_id.startswith("person:")
            or owner_profile_id == "person:owner"
            or profile.get("owner_enrollment_id") != owner_profile_id):
        raise ValueError("missing_pinned_owner_enrollment")
    stamp=_timestamp(now)
    unix_time=int(stamp.timestamp())
    if not wav_quality_ok(raw_wav):
        raise ValueError("invalid_audio_quality")
    audio_digest=hashlib.sha256(raw_wav).hexdigest()
    identity=verify_external_attestation(
        speaker_signer_secret,signed_turn_ticket,session_id=session_id,
        item_id=item_id,transcript=transcript,
        now=unix_time,audio_sha256=audio_digest)
    if identity != ("person:owner","owner"):
        raise PermissionError("independent_owner_turn_proof_required")
    if not verify_grant(owner_grant_secret,owner_grant,session_id,
                        now=unix_time):
        raise PermissionError("owner_session_grant_required")
    if embedding_fn is None:
        # Must be scheduled on the CPU *after* the conversation ends, never
        # in the realtime WebSocket/I2S forward loop.
        from kitty_speaker_cpu_v6 import _embedding
        embedding_fn=_embedding
    vector=_unit(embedding_fn(raw_wav))
    anchors=profile.get("anchor_embeddings",profile.get("embeddings",()))
    anchor_score=_median_similarity(vector,anchors)
    floor=profile.get("min_genuine_floor",MIN_SCORE)
    if (type(floor) not in (float,int) or not math.isfinite(floor)
            or not MIN_SCORE<=floor<=1.0):
        raise ValueError("invalid_model_specific_floor")
    if anchor_score < floor:
        raise ValueError("outside_protected_enrollment_voice")
    if not isinstance(other_profiles,(list,tuple)):
        raise ValueError("invalid_competitor_profiles")
    for other in other_profiles:
        if not isinstance(other,dict):
            raise ValueError("invalid_competitor_profile")
        peer_anchors=other.get("anchor_embeddings",other.get("embeddings",()))
        if peer_anchors and (_median_similarity(vector,peer_anchors)
                             > anchor_score-MIN_COMPETITOR_MARGIN):
            raise ValueError("ambiguous_other_enrolled_voice")
    # Exact recording replay and near-duplicate audio are never useful
    # training samples, even when a mistakenly reused proof is present.
    hashes=profile.get("adaptive_audio_hashes",[])
    if not isinstance(hashes,list):
        raise ValueError("invalid_history")
    if audio_digest in hashes:
        raise ValueError("duplicate_recording")
    result=propose(profile,vector,now=stamp.isoformat(),score=anchor_score,
                   verified=True,explicit_approval=True)
    # Keep only bounded opaque digests for duplicate detection: no WAVs,
    # transcripts, speaker names or raw sound are persisted here.
    result["adaptive_audio_hashes"]=(hashes+[audio_digest])[-32:]
    result["adaptive_source"]="independently_attested_owner_turn"
    result["memory_authorization"]=False
    return result
