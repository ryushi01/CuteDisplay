#!/usr/bin/env python3
"""Validate an independently consented local owner voice-auth profile.

The historical shadow_only profile is a conversational candidate profile,
NOT an owner authorization enrollment. It may not be silently promoted.
The user can choose a separate opt-in mode without re-pairing the iPhone.
Profile vectors are local identity material, not a memory authority.
"""
import json
import math
import os
import statistics
from pathlib import Path
import stat

OWNER_ID = "person:shana"
MODEL_ID = "speechbrain/spkrec-xvect-voxceleb"
MAX_BYTES = 250_000
MIN_ANCHORS = 3
DIMENSIONS = 512
CONSENT = "owner-accepts-voice-auth-spoofing-risk-v1"


def consented_owner_profile(path):
    if not isinstance(path, (str, Path)) or not str(path):
        return False
    p = Path(path)
    try:
        if p.is_symlink() or not p.is_file():
            return False
        info = p.stat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077
                or not 100 <= info.st_size <= MAX_BYTES):
            return False
        data = json.loads(p.read_text(encoding="utf-8"))
        if (not isinstance(data, dict)
                or data.get("mode") != "owner_voice_auto_auth_v6"
                or data.get("speaker_id") != OWNER_ID
                or data.get("owner_enrollment_id") != OWNER_ID
                or data.get("model_id") != MODEL_ID
                or data.get("owner_private_memory_opt_in") != CONSENT
                or data.get("memory_authorization") != "voice_auto_opt_in"):
            return False
        anchors = data.get("anchor_embeddings")
        if not isinstance(anchors, list) or len(anchors) < MIN_ANCHORS:
            return False
        for anchor in anchors:
            if (not isinstance(anchor, list) or len(anchor) != DIMENSIONS
                    or any(type(v) not in (float, int) or not math.isfinite(v)
                           or abs(v) > 1 for v in anchor)):
                return False
        return True
    except (OSError, UnicodeError, ValueError, TypeError):
        return False



def match_local_enrolled_owner(wav, profile_path, *, embed_fn=None):
    """Fresh local CPU comparison, never a caller-provided score.

    The caller must dispatch this OUTSIDE the realtime WebSocket/audio
    handler. A valid consented profile is reread each time so revocation
    fails closed. The SpeechBrain model must already be cached locally.
    This is biometric similarity, NOT replay detection or owner presence.
    """
    unknown = {"speaker_id": "unknown", "score": None}
    if not consented_owner_profile(profile_path):
        return unknown
    try:
        ref = json.loads(Path(profile_path).read_text(encoding="utf-8"))
        if embed_fn is None:
            from kitty_speaker_cpu_v6 import _embedding
            embed_fn = _embedding
        vec = embed_fn(wav)
        if (not isinstance(vec, (list, tuple)) or len(vec) != DIMENSIONS
                or any(type(v) not in (float, int) or not math.isfinite(v)
                       for v in vec)):
            return unknown
        norm = math.sqrt(math.fsum(float(v)*float(v) for v in vec))
        if norm < 0.01:
            return unknown
        unit = [float(v)/norm for v in vec]
        anchors = ref["anchor_embeddings"]
        scores = []
        for anchor in anchors:
            length = math.sqrt(math.fsum(float(x)*float(x) for x in anchor))
            if length < 0.01:
                return unknown
            scores.append(math.fsum(
                a*float(b)/length for a,b in zip(unit, anchor)))
        score = statistics.median(scores)
        if not math.isfinite(score):
            return unknown
        return {
            "speaker_id":OWNER_ID if score >= 0.965 else "unknown",
            "score":round(min(max(float(score), -1.0), 1.0), 6),
        }
    except (OSError, ValueError, KeyError, TypeError, ImportError, RuntimeError):
        return unknown
