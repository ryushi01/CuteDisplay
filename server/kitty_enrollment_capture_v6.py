"""Opt-in, bounded temporary samples from Kitty's actual microphone.

Capture is disabled unless the operator creates the local enable marker.
Three recordings maximum; owner reviews them before any profile replacement.
No recordings or voiceprints are transmitted to a third party.
"""
import os
from pathlib import Path

ROOT = Path("/run/kitty-semantic")
MARKER = ROOT / "enrollment.enabled"
OUTPUT = Path("/app/backend/data/kitty-enrollment-samples")

def capture(pcm24):
    if not MARKER.is_file() or MARKER.is_symlink():
        return False
    if not OUTPUT.is_dir() or OUTPUT.is_symlink():
        return False
    if not isinstance(pcm24, bytes) or len(pcm24) < 24000 * 2 * 2:
        return False
    try:
        from .kitty_realtime_speaker_v6 import to_16k_wav
    except ImportError:
        from kitty_realtime_speaker_v6 import to_16k_wav
    audio = to_16k_wav(pcm24)
    for index in range(1, 4):
        destination = OUTPUT / ("kitty-sample-%d.wav" % index)
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(str(destination), flags, 0o600)
        except FileExistsError:
            continue
        with os.fdopen(fd, "wb") as file:
            file.write(audio)
        print("[KITTY_ENROLL] captured_sample=%d" % index, flush=True)
        # Three existing filenames limit capture automatically.
        # Marker remains on the read-only mount; operator removes it on host.
        return True
    return False
