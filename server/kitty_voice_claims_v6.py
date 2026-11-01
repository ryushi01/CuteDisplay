#!/usr/bin/env python3
"""Conservative explicit speaker introductions for Kitty V6.

A self-introduction is useful for conversational continuity when a familiar
voice sounds different. It is NEVER biometric identity verification.
"""
import re

OWNER="person:shana"

# Require first-person self-identification, not mentions like
# "Shana told me..." or "Are you Shana?".
_PATTERNS=[
    r"\b(?:hey[,! ]+)?(?:this is|it's|it is|i am|i'm|my name is)\s+shana\b",
    r"\b(?:salut[,! ]+|bonjour[,! ]+)?(?:c'est|je suis|moi c'est|je m'appelle)\s+shana\b",
    r"(?:私は|わたしは|僕は|ぼくは|俺は|あたしは)?(?:シャナ|しゃな)(?:です|だよ|だ|と申します|と言います|っていうの|といいます)",
    r"(?:私|わたし|僕|ぼく|俺|あたし)は(?:シャナ|しゃな)(?:です|だよ|だ)?",
]
_INTRO=[re.compile(p,re.IGNORECASE) for p in _PATTERNS]

def claimed_speaker(transcript):
    if not isinstance(transcript,str) or len(transcript)>1000:
        return None
    cleaned=transcript.strip()
    if "?" in cleaned or "？" in cleaned:
        return None
    if any(p.search(cleaned) for p in _INTRO):
        return OWNER
    return None

def reconcile_voice_and_claim(voice,transcript):
    """Voice probable wins. Otherwise allow a non-authorizing self-claim."""
    voice=voice if isinstance(voice,dict) else {}
    sid=voice.get("speaker_id")
    confidence=voice.get("confidence")
    claim=claimed_speaker(transcript)
    if confidence=="probable" and isinstance(sid,str) and sid not in ("","unknown"):
        return {"speaker_id":sid,"confidence":"probable",
                "claimed_id":claim,"claim_conflicts":bool(claim and sid!=claim)}
    if claim:
        return {"speaker_id":claim,"confidence":"claimed",
                "claimed_id":claim,"claim_conflicts":False}
    return {"speaker_id":"unknown","confidence":"unknown",
            "claimed_id":None,"claim_conflicts":False}
