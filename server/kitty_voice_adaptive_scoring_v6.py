#!/usr/bin/env python3
"""Candidate-only familiarity scoring for pinned ECAPA/X-vector embeddings.

Protected original enrollment remains the reference. An adaptive cohort may
improve recognition *only* after three separately owner-verified, consented
samples from the same encoder; it never lowers the existing acceptance
threshold and NEVER grants owner memory access. This is not liveness detection.
"""
import math
import statistics

from kitty_voice_adaptation_policy_v6 import _unit, prune_adaptive

MAX_ADAPTIVE_INFLUENCE = 3
MIN_ORIGINAL_RESEMBLANCE = 0.90  # conservative shadow-only X-vector floor


def _median_cosine(query, anchors):
    values=[]
    for anchor in anchors:
        vec=_unit(anchor)
        if len(vec)!=len(query):
            raise ValueError("mixed_embedding_models")
        values.append(math.fsum(a*b for a,b in zip(query,vec)))
    if len(values)<3:
        raise ValueError("at_least_three_protected_anchors")
    return statistics.median(values)


def candidate_score(embedding, anchors, adaptive_entries=(), *,
                    now, adaptive_enabled=False,
                    min_original=MIN_ORIGINAL_RESEMBLANCE):
    """Return similarity + cohort label, NEVER an authenticated identity.

    For a negative/uncertain voice: original confidence is not overridden by
    adaptive samples outside the protected anchor resemblance floor.
    """
    query=_unit(embedding)
    baseline=_median_cosine(query,anchors)
    if (adaptive_enabled is not True or baseline < min_original
            or not isinstance(adaptive_entries,(tuple,list))):
        return baseline, "anchors"
    valid=prune_adaptive(adaptive_entries,now=now)
    if len(valid)<MAX_ADAPTIVE_INFLUENCE:
        return baseline, "anchors"
    try:
        adaptive=_median_cosine(query,[x["embedding"] for x in valid])
    except (ValueError,KeyError,TypeError):
        return baseline, "anchors"
    return (adaptive,"adaptive") if adaptive>baseline else (baseline,"anchors")
