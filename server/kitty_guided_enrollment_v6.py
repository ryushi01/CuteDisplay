#!/usr/bin/env python3
"""Offline voice enrollment diagnostics, read only.

All-sample cohort search is EXPLORATORY, not an independent validation:
sample selection uses the same data. A chronological holdout is evaluated
separately without using it to choose enrollment vectors. Never enrolls.
"""
import argparse
import itertools
import statistics
from pathlib import Path

def evaluate(paths, threshold):
    import numpy as np
    from kitty_speaker_cpu_v6 import _embedding
    vectors = [np.asarray(_embedding(p.read_bytes()), dtype="float64") for p in paths]
    def score(i, j):
        return float(np.dot(vectors[i], vectors[j]))
    print("=== Kitty enrollment diagnostics (read-only) ===")
    print("Samples:", len(paths), "Threshold:", threshold)
    print("=== All recording pairs ===")
    pairs = []
    for i, j in itertools.combinations(range(len(paths)), 2):
        value = score(i, j)
        pairs.append(value)
        print("%s vs %s: %.3f" % (paths[i].name, paths[j].name, value))
    print("Pairwise median: %.3f" % statistics.median(pairs))
    print("Observed pairwise range: %.3f to %.3f" % (min(pairs), max(pairs)))
    print("=== Best exploratory three-sample cohort (NOT validated) ===")
    candidates = []
    for group in itertools.combinations(range(len(paths)), 3):
        similarities = [score(i, j) for i, j in itertools.combinations(group, 2)]
        candidates.append((min(similarities), statistics.mean(similarities), group))
    best = max(candidates)
    print("Best cohort:", ", ".join(paths[i].name for i in best[2]))
    print("Minimum within-cohort similarity: %.3f" % best[0])
    print("Exploratory cohort passes threshold:", best[0] >= threshold)
    print("=== Strict chronological holdout (untouched during selection) ===")
    # First half for training candidate selection; second half reserved for validation.
    k = len(paths) // 2
    enrollment = list(range(k))
    holdout = list(range(k, len(paths)))
    cohort = max(
        itertools.combinations(enrollment, 3),
        key=lambda group: (
            min(score(i, j) for i, j in itertools.combinations(group, 2)),
            statistics.mean(score(i, j) for i, j in itertools.combinations(group, 2))
        ))
    internal = min(score(i, j) for i, j in itertools.combinations(cohort, 2))
    print("Enrollment group:", ", ".join(paths[i].name for i in cohort))
    print("Enrollment minimum pair score: %.3f" % internal)
    holdout_scores = []
    for idx in holdout:
        median = statistics.median(score(idx, j) for j in cohort)
        holdout_scores.append(median)
        print("%s: holdout median=%.3f %s" % (
            paths[idx].name, median,
            "PASS" if median >= threshold else "REJECT"))
    valid = internal >= threshold and all(v >= threshold for v in holdout_scores)
    print("Lowest independent holdout median: %.3f" % min(holdout_scores))
    print("Trial threshold is OFFLINE-ONLY; live memory authorization remains unchanged.")
    print("Enrollment verdict:", "CANDIDATE_ONLY — impostor validation required" if valid
          else "DO_NOT_ACTIVATE")
    print("No profile, memory, recordings or threshold modified.")
    return valid

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav-dir", type=Path, required=True)
    ap.add_argument("--threshold", type=float, default=0.82)
    args = ap.parse_args()
    if not 0.65 <= args.threshold <= 1.0:
        ap.error("audit threshold must be between 0.65 and 1.0")
    paths = sorted(p for p in args.wav_dir.glob("*.wav") if p.is_file() and not p.is_symlink())
    if not 6 <= len(paths) <= 24:
        ap.error("requires between 6 and 24 WAV recordings")
    evaluate(paths, args.threshold)

if __name__ == "__main__":
    main()
