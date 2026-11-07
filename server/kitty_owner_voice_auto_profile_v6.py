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
