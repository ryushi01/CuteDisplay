"""Kitty V6 voice adaptation policy. Offline-only, fail-closed.

This module never authenticates a speaker and never updates a profile by itself.
External verification is required before an embedding can enter a candidate pool.
A human-approved candidate may replace an *adaptive* slot but not an anchor.
"""
from datetime import datetime, timezone
from math import isfinite, sqrt

MAX_ADAPTIVE = 6
MAX_DAYS = 90
MIN_SPACING_HOURS = 24
MIN_SCORE = 0.82

def _utc(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timezone required")
    return dt.astimezone(timezone.utc)

def _unit(vec):
    if not isinstance(vec, (list, tuple)) or len(vec) != 192:
        raise ValueError("invalid_embedding_dimension")
    if any(not isinstance(x, (int, float)) or not isfinite(x) for x in vec):
        raise ValueError("invalid_embedding_value")
    norm = sqrt(sum(float(x)*float(x) for x in vec))
    if not 0.99 <= norm <= 1.01:
        raise ValueError("embedding_not_unit_normalized")
    return [float(x)/norm for x in vec]

def prune_adaptive(entries, *, now):
    """Remove old adaptive samples, retaining newest MAX_ADAPTIVE entries."""
    current = _utc(now)
    retained = []
    for entry in entries:
        when = _utc(entry["timestamp"])
        age = (current - when).total_seconds()
        if 0 <= age <= MAX_DAYS * 86400:
            retained.append(entry)
    retained.sort(key=lambda e: e["timestamp"], reverse=True)
    return retained[:MAX_ADAPTIVE]

def propose(profile, embedding, *, now, score, verified, explicit_approval):
    """Return new candidate profile, without writing or activating it.

    Never update from voice recognition alone: a bad match could poison memory
    access. "verified" must come from a separate trusted verification mechanism,
    not a speaker ID, self-introduction, or semantic memory response.
    """
    if verified is not True or explicit_approval is not True:
        raise PermissionError("independent_verification_and_approval_required")
    if not isinstance(score, (float, int)) or not isfinite(score) or score < MIN_SCORE:
        raise ValueError("insufficient_similarity")
    vec = _unit(embedding)
    anchor = profile.get("anchor_embeddings", ())
    if len(anchor) < 3:
        raise ValueError("at_least_three_protected_anchors_required")
    for item in anchor:
        _unit(item)
    current = _utc(now)
    existing = prune_adaptive(profile.get("adaptive_embeddings", []), now=now)
    if any(abs((current - _utc(e["timestamp"])).total_seconds()) < MIN_SPACING_HOURS*3600
           for e in existing):
        raise ValueError("adaptive_sample_spacing_too_short")
    entry = {"embedding": vec, "timestamp": current.isoformat(),
             "similarity": round(float(score), 3)}
    # Preserve protected original anchors verbatim.
    return {**profile, "adaptive_embeddings":
            prune_adaptive([entry, *existing], now=now)}

def effective_embeddings(profile, *, now):
    """Use stable anchors and recent vetted samples; no silent learning."""
    anchors = [_unit(x) for x in profile.get("anchor_embeddings", profile.get("embeddings", ()))]
    if len(anchors) < 3:
        raise ValueError("profile_has_no_protected_anchors")
    adaptive = prune_adaptive(profile.get("adaptive_embeddings", []), now=now)
    return anchors + [_unit(x["embedding"]) for x in adaptive]
