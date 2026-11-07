#!/usr/bin/env python3
"""Fail-closed owner-private SD semantic authorization.

Three independent conditions are required by the memory storage boundary:
  1. Authenticated local memory-service transport (HTTP handler's bearer).
  2. A short-lived owner grant issued after trusted login/proof OR an
     explicitly opt-in, calibrated, isolated voice-only owner issuer.
  3. A separate trusted speaker issuer's signed ticket for THIS exact
     provider-observed session, item and transcript (current question).

The signing secret MUST live only with the trusted speaker issuer and memory
service, never with S3 device credentials, Bluetooth or a mutable SD snapshot.
In voice-only mode the same isolated issuer may establish both credentials;
separate keys are NOT independent authentication factors. This is an explicit
owner risk opt-in; live trusted gateway wiring is not installed by source code.
"""
from kitty_owner_session_v6 import verify_grant

OWNER_ID = "person:owner"


def authorized_semantic_speaker(payload, owner_proof,
                                trusted_turn_secret=None, *, now=None):
    """Return fixed owner identity ONLY for exact, independently signed turn.

    A copied owner grant, device token, probable voice label, SD owner sidecar,
    or self-introduction is never enough. The query MUST equal the independently
    signed transcription: a valid ticket cannot become a general-purpose
    bearer credential to query arbitrary private facts.
    """
    if not isinstance(payload, dict) or owner_proof is None:
        return None
    if payload.get("speaker_id") != OWNER_ID:
        return None
    session_id = payload.get("session_id")
    grant = payload.get("owner_grant")
    item = payload.get("item_id")
    transcript = payload.get("transcript")
    query = payload.get("query")
    ticket = payload.get("turn_attestation")
    audio_sha256 = payload.get("audio_sha256")
    if (not isinstance(session_id, str) or not 16 <= len(session_id) <= 100
            or not isinstance(grant, str) or not 1 <= len(grant) <= 1024
            or not isinstance(item, str) or not 1 <= len(item) <= 160
            or not isinstance(transcript, str) or not 1 <= len(transcript) <= 300
            or not isinstance(query, str) or query != transcript
            or not isinstance(ticket, str) or not 1 <= len(ticket) <= 1024
            or (audio_sha256 is not None and
                (not isinstance(audio_sha256, str) or len(audio_sha256) != 64
                 or any(c not in "0123456789abcdef" for c in audio_sha256)))
            or not isinstance(trusted_turn_secret, bytes)
            or len(trusted_turn_secret) < 32):
        return None
    owner_secret = getattr(owner_proof, "secret", None)
    if (not isinstance(owner_secret, bytes) or len(owner_secret) < 32
            or owner_secret == trusted_turn_secret
            or not verify_grant(owner_secret, grant, session_id, now=now)):
        return None

    # Explicitly separated issuer audience; a learning/voice-familiarity
    # ticket cannot grant memory access. The issuer, not the S3, must have
    # independently authenticated the actual speaker for the exact turn.
    from kitty_attested_live_call_v6 import verify_external_attestation
    identity = verify_external_attestation(
        trusted_turn_secret, ticket, session_id=session_id,
        item_id=item, transcript=transcript, now=now, purpose="turn",
        audio_sha256=audio_sha256)
    return OWNER_ID if identity == (OWNER_ID, "owner") else None
