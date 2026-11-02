#!/usr/bin/env python3
"""Authorize private semantic SD-derived searches at the storage service.

A bearer token authenticates the Kitty device/service, NOT the human speaker.
Never authorize by a caller-provided person:ID, voice candidate, self-introduction,
SD sidecar, or S3 API token alone.

Current scope is intentionally OWNER ONLY.  A short-lived owner grant must have
been issued after independently enrolled-key verification and must match the
request's session. Per-turn owner proof and verified guest access are future work.
No private search is made when this check fails.
"""
from kitty_owner_session_v6 import verify_grant

OWNER_ID = "person:owner"


def authorized_semantic_speaker(payload, owner_proof):
    """Return the fixed owner identity only for a valid signed session grant."""
    if not isinstance(payload, dict) or owner_proof is None:
        return None
    if payload.get("speaker_id") != OWNER_ID:
        return None
    session_id = payload.get("session_id")
    grant = payload.get("owner_grant")
    if (not isinstance(session_id, str) or not 8 <= len(session_id) <= 100
            or not isinstance(grant, str) or not 1 <= len(grant) <= 1024):
        return None
    secret = getattr(owner_proof, "secret", None)
    if not verify_grant(secret, grant, session_id):
        return None
    return OWNER_ID
