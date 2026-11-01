#!/usr/bin/env python3
"""Offline Kitty microphone enrollment audit. Never writes or enables profiles.

Usage: python kitty_voice_enrollment_audit_v6.py --wav-dir /path/to/wavs
The operator retrieves WAVs locally. No network, device authentication, or
realtime WebSocket operations are performed.
"""
import argparse
import itertools
import os
import statistics
from pathlib import Path

def audit(directory):
    from kitty_speaker_cpu_v6 import _embedding, THRESHOLD
    import numpy as np
    names = ["kitty-candidate-1.wav", "kitty-sample-2.wav",
             "kitty-sample-3.wav", "kitty-sample-1.wav"]
    paths = [directory / name for name in names]
    if any(not p.is_file() or p.is_symlink() for p in paths):
        raise ValueError("four_regular_samples_required")
    vectors = [np.asarray(_embedding(p.read_bytes()), dtype="float64") for p in paths]
    print("=== Kitty quiet-room enrollment audit ===")
    print("Existing recognition threshold: %.3f" % THRESHOLD)
    for i, j in itertools.combinations(range(len(vectors)), 2):
        print("Pair %d/%d: %.3f" % (i + 1, j + 1,
                                    float(np.dot(vectors[i], vectors[j]))))
    # Leave-one-out prevents measuring a recording against itself.
    holdout = []
    for i in range(len(vectors)):
        against = [float(np.dot(vectors[i], vectors[j]))
                   for j in range(len(vectors)) if j != i]
        score = float(statistics.median(against))
        holdout.append(score)
        print("Holdout %d: median=%.3f decision=%s" % (
            i+1, score, "pass" if score >= THRESHOLD else "unknown"))
    passed = sum(s >= THRESHOLD for s in holdout)
    print("Independent holdouts passed: %d/4" % passed)
    print("Activation recommendation: %s" % (
        "review_with_impostor_validation" if passed == 4 else "DO_NOT_ACTIVATE"))
    print("No voice profile, audio, threshold, or memory changed.")
    return passed == 4

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav-dir", required=True, type=Path)
    args = ap.parse_args()
    audit(args.wav_dir)

if __name__ == "__main__":
    main()
