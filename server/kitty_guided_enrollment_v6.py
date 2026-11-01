#!/usr/bin/env python3
"""Offline guided Kitty speaker enrollment evaluation.

Uses six or more independently recorded WAV utterances. Splits by capture
order into enrollment and holdout samples; does not create or modify profiles.
Do not treat the result as an impostor/false-acceptance calibration.
"""
import argparse
import itertools
import statistics
from pathlib import Path

def evaluate(paths, threshold):
    import numpy as np
    from kitty_speaker_cpu_v6 import _embedding
    vectors = [np.asarray(_embedding(p.read_bytes()), dtype="float64") for p in paths]
    # Alternate samples across enrollment and holdout to reduce sequence bias.
    enroll = list(range(0, len(paths), 2))
    holdout = list(range(1, len(paths), 2))
    if len(enroll) < 3 or len(holdout) < 3:
        raise ValueError("at_least_six_independent_utterances_required")
    # Choose a coherent subset using only enrollment recordings.
    subset = None
    for count in range(len(enroll), 2, -1):
        viable = []
        for group in itertools.combinations(enroll, count):
            sim = [float(np.dot(vectors[i], vectors[j]))
                   for i, j in itertools.combinations(group, 2)]
            if min(sim) >= threshold:
                viable.append((statistics.mean(sim), group))
        if viable:
            subset = max(viable)[1]
            break
    print("=== Kitty guided enrollment audit ===")
    print("Enrollment candidates:", len(enroll))
    print("Independent holdouts:", len(holdout))
    print("Threshold:", round(threshold, 3))
    if subset is None:
        print("Status: REJECT — no internally consistent three-sample cohort")
        return False
    print("Selected candidate filenames:", ", ".join(paths[i].name for i in subset))
    results = []
    for index in holdout:
        similarities = [float(np.dot(vectors[index], vectors[j])) for j in subset]
        median = statistics.median(similarities)
        results.append(median)
        print("Holdout %s: median=%.3f %s" %
              (paths[index].name, median,
               "PASS" if median >= threshold else "REJECT"))
    ok = all(score >= threshold for score in results)
    print("Status:", "CANDIDATE_ONLY — require impostor validation and owner approval"
          if ok else "REJECT — independent holdout below threshold")
    print("No profile or memory modifications.")
    return ok

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wav-dir", required=True, type=Path)
    parser.add_argument("--threshold", type=float, default=0.82)
    args = parser.parse_args()
    if not 0.82 <= args.threshold <= 1.0:
        parser.error("cannot reduce configured security threshold")
    # Sorted names form the deterministic capture-order split.
    files = sorted(p for p in args.wav_dir.glob("*.wav") if p.is_file() and not p.is_symlink())
    if len(files) < 6 or len(files) > 24:
        parser.error("expected 6–24 WAV files")
    evaluate(files, args.threshold)

if __name__ == "__main__":
    main()
