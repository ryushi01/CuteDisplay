#!/usr/bin/env python3
"""Offline, read-only Kitty speaker-verifier evaluation.

Run with the Kitty venv in server/, from Ubuntu. Does not change profiles,
thresholds, recordings, or any live service.
"""
import io
import os
import subprocess
import wave
from pathlib import Path

import numpy as np

NAMES = (
    "kitty-candidate-1.wav",
    "kitty-sample-2.wav",
    "kitty-sample-3.wav",
    "kitty-sample-1.wav",
)
SAMPLES = "/app/backend/data/kitty-enrollment-samples"

def settings():
    path = Path.home() / "kitty-v6/private/memory-service.env"
    for line in path.read_text().splitlines():
        if line.startswith(("KITTY_SPEAKER_MODEL_DIR=", "KITTY_VOICE_PROFILES_V6=")):
            key, value = line.split("=", 1)
            os.environ[key] = value.strip().strip('"').strip("'")

def vector(speaker, filename):
    data = subprocess.check_output(
        ["sudo", "docker", "exec", "open-webui",
         "cat", f"{SAMPLES}/{filename}"]
    )
    with wave.open(io.BytesIO(data)) as wf:
        assert wf.getframerate() == 16000
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert 1.5 <= wf.getnframes() / 16000 <= 8
    return np.asarray(speaker._embedding(data), dtype=np.float64)

def similarity(left, right):
    return float(np.dot(left, right))

def main():
    settings()
    import kitty_speaker_cpu_v6 as speaker

    recordings = [vector(speaker, name) for name in NAMES]
    old = [np.asarray(v, dtype=np.float64) for v in
           speaker._load()["speakers"]["person:shana"]["embeddings"]]
    print("=== Existing Mac profile: each held-out Kitty utterance ===")
    for name, v in zip(NAMES, recordings):
        scores = [similarity(v, p) for p in old]
        print(f"{name}: median={np.median(scores):.3f}; "
              f"individual={[round(x, 3) for x in scores]}")

    print("\n=== Four-fold Kitty leave-one-out ===")
    accepted = 0
    for i, (name, v) in enumerate(zip(NAMES, recordings)):
        enrollment = [w for j, w in enumerate(recordings) if i != j]
        scores = [similarity(v, w) for w in enrollment]
        median = float(np.median(scores))
        accepted += median >= speaker.THRESHOLD
        print(f"{name}: median={median:.3f}; "
              f"scores={[round(x, 3) for x in scores]}; "
              f"pass={median >= speaker.THRESHOLD}")
    print(f"Acceptance against other Kitty utterances: {accepted}/{len(NAMES)}")
    print(f"Threshold held unchanged: {speaker.THRESHOLD:.2f}")
    print("No impostor samples available: false-accept rate NOT evaluated.")
    print("No profile, service, recording, or firmware modified.")

if __name__ == "__main__":
    main()
