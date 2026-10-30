#!/usr/bin/env python3
"""MicroSD-first speaker profile export/import format for V6.

This is a portable profile cache representation. S3 owns canonical file
/kitty/voice_profiles_v6.json; Ubuntu may load it from a verified SD snapshot.
Never sync private voiceprints to GitHub or treat a match as authentication.
"""
import json
from pathlib import Path

MAX_PROFILES=32
MAX_SAMPLES=12
MAX_DIM=512

def validate_profiles(payload):
    if not isinstance(payload,dict) or payload.get("version")!=1:
        raise ValueError("invalid profile version")
    people=payload.get("speakers")
    if not isinstance(people,dict) or len(people)>MAX_PROFILES:
        raise ValueError("invalid speakers")
    for speaker,data in people.items():
        if not isinstance(speaker,str) or not 1<=len(speaker)<=64 or any(c in speaker for c in "\t\r\n"):
            raise ValueError("invalid speaker id")
        if not isinstance(data,dict) or data.get("consent") is not True:
            raise ValueError("consent required")
        vectors=data.get("vectors")
        if not isinstance(vectors,list) or not 3<=len(vectors)<=MAX_SAMPLES:
            raise ValueError("need 3-12 voice samples")
        for v in vectors:
            if not isinstance(v,list) or not 1<=len(v)<=MAX_DIM or any(type(n) not in (int,float) or not -1<=n<=1 for n in v):
                raise ValueError("invalid vector")
    return {k:data["vectors"] for k,data in people.items()}

def load_sd_profiles(snapshot):
    path=Path(snapshot)/"kitty"/"voice_profiles_v6.json"
    if path.stat().st_size>250000:
        raise ValueError("profile file too large")
    return validate_profiles(json.loads(path.read_text(encoding="utf-8")))

def export_enrollment(speaker_id,vectors):
    from kitty_voice_id_v6 import enroll_profile
    return {"version":1,"speakers":{speaker_id:{"consent":True,"vectors":enroll_profile(vectors)}}}
