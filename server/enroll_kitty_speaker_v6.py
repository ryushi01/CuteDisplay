#!/usr/bin/env python3
"""Explicit opt-in private Kitty V6 speaker enrollment; no service restart.

Usage:
  .venv-v6/bin/python server/enroll_kitty_speaker_v6.py person:ryushi a.wav b.wav c.wav
Recordings must be 16 kHz/mono/16-bit PCM WAV, each 1.5-8 seconds.
Enrollment creates private embeddings only; source WAVs are left untouched.
"""
import argparse
import os
import stat
import sys
import wave
from pathlib import Path

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("speaker_id")
    ap.add_argument("wav", nargs="+", type=Path)
    ap.add_argument("--consent", action="store_true",
                    help="I explicitly consent to local speaker embedding enrollment")
    args = ap.parse_args()
    if not args.consent:
        ap.error("Explicit --consent required; no enrollment performed")
    if not 3 <= len(args.wav) <= 8:
        ap.error("Provide 3-8 WAV samples")
    for p in args.wav:
        if not p.is_file() or p.is_symlink():
            ap.error(f"Missing or symlink WAV: {p}")
        if p.stat().st_size > 300000:
            ap.error(f"Sample too large: {p}")
        try:
            with wave.open(str(p), "rb") as w:
                duration = w.getnframes() / w.getframerate()
                if (w.getframerate(),w.getnchannels(),w.getsampwidth()) != (16000,1,2) or not 1.5 <= duration <= 8:
                    ap.error(f"Invalid WAV (require 16k mono PCM16, 1.5-8 seconds): {p}")
        except (wave.Error, ZeroDivisionError) as e:
            ap.error(f"Cannot read PCM WAV {p}: {e}")
    model = Path.home() / "kitty-v6/private/speaker-models/espnet-ecapa-v6"
    store = Path.home() / "kitty-v6/private/voice-profiles-v6.json"
    if not (model / "hyperparams.yaml").is_file():
        ap.error("Local model missing; prepare and warm it first")
    if store.is_symlink():
        ap.error("Refusing symlink profile store")
    store.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(store.parent, 0o700) if store.parent.name == "private" else None
    os.environ["KITTY_SPEAKER_MODEL_DIR"] = str(model)
    os.environ["KITTY_VOICE_PROFILES_V6"] = str(store)
    from kitty_speaker_cpu_v6 import enroll
    result = enroll(args.speaker_id, [str(p) for p in args.wav])
    if (store.stat().st_mode & 0o077) != 0:
        raise RuntimeError("Profile permissions unsafe")
    print(f"Enrollment complete: {result['enrolled']} ({result['samples']} samples)")
    print(f"Private embeddings: {store}")
    print("Original WAVs were NOT deleted. Delete them yourself after verification.")
    print("Live speaker recognition and semantic recall remain DISABLED.")

if __name__ == "__main__":
    main()
