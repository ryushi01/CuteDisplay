#!/usr/bin/env python3
"""Offline speaker scoring evaluation. Never modifies profiles or service state.

Uses the existing Kitty V6 embedding pipeline. Calculates leave-one-out
same-speaker scores and an unseen-utterance holdout. With one known human,
these results CANNOT estimate impostor acceptance rates or justify access
to private speaker-scoped memory.
"""
import argparse
from pathlib import Path
import numpy as np
from kitty_speaker_cpu_v6 import _embedding


def normalize(x):
    x=np.asarray(x, dtype=np.float64)
    n=np.linalg.norm(x)
    if not np.isfinite(n) or n < 1e-8:
        raise ValueError("invalid vector")
    return x/n


def score(query, references, method):
    query=normalize(query)
    refs=np.stack([normalize(v) for v in references])
    cosines=refs @ query
    if method == "median":
        return float(np.median(cosines))
    if method == "centroid":
        return float(normalize(refs.mean(axis=0)) @ query)
    if method == "max":
        return float(np.max(cosines))
    raise ValueError("unknown score method")


def evaluate(vectors, train_ids, holdouts):
    result={}
    for method in ("median","centroid","max"):
        loo={}
        for item in train_ids:
            other=[vectors[i] for i in train_ids if i!=item]
            loo[item]=score(vectors[item],other,method)
        unseen={i: score(vectors[i],[vectors[j] for j in train_ids],method)
                for i in holdouts}
        result[method]={"loo":loo,"holdout":unseen}
    return result


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--folder", type=Path,
                    default=Path.home()/"kitty-v6/private/voice-samples")
    ap.add_argument("--train", nargs="+", type=int, default=[1,4,5])
    ap.add_argument("--holdout", nargs="+", type=int, default=[6,7,8,9])
    args=ap.parse_args()
    ids=tuple(dict.fromkeys(args.train+args.holdout))
    if len(args.train)<3 or len(set(args.train))!=len(args.train):
        ap.error("need at least three distinct enrollment samples")
    if set(args.train)&set(args.holdout):
        ap.error("holdout cannot overlap enrollment")
    vectors={}
    for i in ids:
        path=args.folder/f"voice{i}.wav"
        if not path.is_file() or path.is_symlink():
            ap.error(f"missing non-symlink sample: {path}")
        vectors[i]=normalize(_embedding(path.read_bytes()))
    results=evaluate(vectors,args.train,args.holdout)
    print("Kitty V6 offline speaker scoring (cosine similarity)")
    for method,data in results.items():
        print(f"\n{method}:")
        print("  leave-one-out:", " ".join(f"voice{i}={s:.3f}" for i,s in data["loo"].items()))
        print("  unseen:", " ".join(f"voice{i}={s:.3f}" for i,s in data["holdout"].items()))
    print("\nNo score threshold was changed. No recordings or profiles were modified.")
    print("Single-person tests cannot establish safe impersonation resistance.")
    print("Speaker-specific private-memory recall must remain disabled.")


if __name__=="__main__":
    main()
