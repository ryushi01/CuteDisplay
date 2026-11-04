#!/usr/bin/env python3
"""Optional atomic private X-vector adaptive profile store (Ubuntu, not enabled).

Never create a new owner identity or alter the immutable enrollment anchors.
No audio/transcript files or microphone samples are stored. The profile is
always shadow/candidate-only, with no memory authorization or access to SD.
Explicit owner-adaptation consent + a pinned model are required.
"""
import copy
import fcntl
import json
import os
from pathlib import Path
import stat
import tempfile

ALLOWED = {
    "adaptive_embeddings", "adaptive_audio_hashes",
    "adaptive_source", "memory_authorization",
}
MODEL = "speechbrain/spkrec-xvect-voxceleb"


def _read(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("invalid_xvector_profile_path")
    st=path.stat()
    if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077:
        raise PermissionError("xvector_profile_requires_0600")
    if st.st_size<=0 or st.st_size>250000:
        raise ValueError("xvector_profile_size")
    data=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data,dict):
        raise ValueError("invalid_xvector_profile")
    if (data.get("mode")!="shadow_only"
            or data.get("memory_authorization") is not False
            or data.get("speaker_id")!="person:shana"
            or data.get("owner_enrollment_id")!="person:shana"
            or data.get("model")!=MODEL
            or data.get("model_id")!=MODEL
            or data.get("adaptive_learning_consent") is not True):
        raise PermissionError("xvector_owner_consent_not_configured")
    anchors=data.get("anchor_embeddings",())
    if not isinstance(anchors,list) or not 3<=len(anchors)<=8:
        raise ValueError("invalid_original_anchors")
    from kitty_voice_adaptation_policy_v6 import _unit
    if any(len(_unit(v))!=512 for v in anchors):
        raise ValueError("wrong_encoder_dimension")
    return data


def load_owner_shadow_profile(path):
    return copy.deepcopy(_read(path))


def _protected(data):
    return {k:v for k,v in data.items() if k not in ALLOWED}


def save_shadow_if_original_unchanged(path, original, candidate):
    """Compare-and-swap with a 0600 lock file, never overwrite another update."""
    path=Path(path)
    if not isinstance(original,dict) or not isinstance(candidate,dict):
        return False
    if (_protected(candidate)!=_protected(original)
            or candidate.get("memory_authorization") is not False
            or candidate.get("adaptive_source")
                !="independently_attested_owner_turn"
            or not isinstance(candidate.get("adaptive_embeddings"),list)
            or len(candidate["adaptive_embeddings"])>6):
        return False
    if path.is_symlink() or not path.is_file():
        return False
    lockpath=path.with_name(path.name+".lock")
    flags=os.O_CREAT|os.O_RDWR
    if hasattr(os,"O_NOFOLLOW"):
        flags|=os.O_NOFOLLOW
    descriptor=os.open(lockpath,flags,0o600)
    temporary=None
    try:
        with os.fdopen(descriptor,"rb+") as lock:
            if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
                return False
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
            current=_read(path)
            if current!=original:
                return False
            # Verify that the only modifications are bounded, model-consistent
            # adaptive entries. The authenticated learning policy generates
            # them; storage does not itself verify the proof.
            from kitty_voice_adaptation_policy_v6 import effective_embeddings
            from datetime import datetime, timezone
            if len(effective_embeddings(candidate,
                   now=datetime.now(timezone.utc).isoformat()))<3:
                return False
            raw=json.dumps(candidate,sort_keys=True,separators=(",",":")).encode()
            if len(raw)>250000:
                return False
            handle,tmp=tempfile.mkstemp(prefix=".kitty-xvector-adaptive-",
                                        dir=path.parent)
            temporary=Path(tmp)
            with os.fdopen(handle,"wb") as output:
                os.fchmod(output.fileno(),0o600)
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary,path)
            temporary=None
            return True
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
