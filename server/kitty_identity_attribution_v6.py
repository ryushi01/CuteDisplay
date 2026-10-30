#!/usr/bin/env python3
"""Conservative identity/speaker attribution for V6 semantic memory.

A transcript's speaker identity is NOT established by the fact that Kitty is
owner-centric or by the contents of a transcript. No voice biometrics.
This module contains pure helpers for future SD-worker/semantic integrations.
"""
from dataclasses import dataclass, asdict
from typing import Optional

OWNER = "person:owner"
ASSISTANT = "agent:kitty"
UNKNOWN = "unknown"
ALLOWED_SOURCES = {"session_verified", "explicit_introduction", "explicit_correction", "unverified"}
ALLOWED_ROLES = {"owner", "guest", "remote_ai", "kitty", "unknown"}

@dataclass(frozen=True)
class Attribution:
    speaker_id: str = UNKNOWN
    speaker_role: str = "unknown"
    provenance: str = "unverified"
    confidence: str = "unknown"

    def __post_init__(self):
        if self.speaker_role not in ALLOWED_ROLES or self.provenance not in ALLOWED_SOURCES:
            raise ValueError("invalid attribution")
        if self.confidence not in {"unknown", "claimed", "verified"}:
            raise ValueError("invalid confidence")
        if not self.speaker_id or len(self.speaker_id) > 128:
            raise ValueError("invalid speaker id")
        if self.confidence == "verified" and self.provenance != "session_verified":
            raise ValueError("a spoken name alone cannot verify identity")
        if self.speaker_id == OWNER and self.confidence != "verified":
            # Owner ID only from an authenticated session; a spoken "I am
            # Shana" must not silently turn into an owner fact.
            raise ValueError("owner identity requires a verified session")

def resolve_speaker(session_owner_verified=False, explicit_identity: Optional[str]=None,
                    explicit_role: Optional[str]=None) -> Attribution:
    """Resolve the current turn; explicit self-identification is a *claim*.

    Never infer that the current speaker is Shana based on owner-centric memory
    or the fact that the current caller uses the same microphone.
    """
    if explicit_role == "kitty":
        # A role label supplied by a microphone transcript is untrusted.
        # Only a trusted internal assistant-output channel may mark Kitty verified.
        return Attribution()
    if explicit_identity and explicit_role in {"guest", "remote_ai"}:
        key = explicit_identity.strip().casefold()
        if not key or len(key) > 80:
            return Attribution()
        # Only non-PII-safe identifier; names live in separately sourced facts.
        return Attribution(f"{explicit_role}:{key}", explicit_role,
                           "explicit_introduction", "claimed")
    if session_owner_verified:
        return Attribution(OWNER, "owner", "session_verified", "verified")
    return Attribution()

def should_write_owner_fact(attribution: Attribution) -> bool:
    return (attribution.speaker_id == OWNER and attribution.speaker_role == "owner"
            and attribution.provenance == "session_verified"
            and attribution.confidence == "verified")

def memory_record(text: str, attribution: Attribution, about_id: Optional[str]=None):
    """Annotate memory without assuming speaker == subject of the statement."""
    return {
        "text": text,
        "attribution": asdict(attribution),
        "about_id": about_id if about_id else None,
    }

def correction_target(previous: Attribution, current: Attribution) -> Optional[str]:
    """A correction targets only the claiming speaker, never the owner by default."""
    if current.speaker_id != UNKNOWN and current.speaker_id == previous.speaker_id:
        return current.speaker_id
    return None
