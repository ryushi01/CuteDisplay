#!/usr/bin/env python3
"""Kitty V6 voice-speaker matching, CPU backend independent.

All embeddings must come from the same pinned speaker encoder/model version.
Unknown is the default. Enrollment requires explicit consent, >=3 separate
speech samples, and a non-owner-restricted stable ID. Caller supplies speech
embeddings after voice-activity and speech-quality checks. This module DOES
NOT perform biometric authentication or silently enroll anyone.
"""
import math
from dataclasses import dataclass

UNKNOWN="unknown"

def normalize(values):
    if not isinstance(values,(list,tuple)) or not 8<=len(values)<=4096:
        raise ValueError("invalid voice embedding")
    floats=[float(x) for x in values]
    if not all(math.isfinite(x) for x in floats):
        raise ValueError("nonfinite voice embedding")
    norm=math.sqrt(sum(x*x for x in floats))
    if norm<1e-8:
        raise ValueError("zero voice embedding")
    return tuple(x/norm for x in floats)

def similarity(a,b):
    if len(a)!=len(b):
        raise ValueError("different speaker model dimensions")
    return sum(x*y for x,y in zip(a,b))

@dataclass(frozen=True)
class VoiceMatch:
    speaker_id: str=UNKNOWN
    score: float=0.0
    margin: float=0.0
    recognized: bool=False
    provenance: str="voice_match_unverified"

class VoiceRegistry:
    """In-memory prototype; persistent voiceprints must use private encrypted
    storage, opt-in enrollment, deletion and model-version migration.
    """
    def __init__(self, model_id, threshold=0.78, margin=0.08):
        if not model_id:
            raise ValueError("model identity required")
        self.model_id=model_id
        self.threshold=threshold
        self.margin=margin
        self.profiles={}
    def enroll(self,speaker_id,samples,consented=False):
        if not consented:
            raise PermissionError("explicit speaker consent required")
        if not isinstance(speaker_id,str) or not speaker_id.startswith("voice:") or len(speaker_id)>80:
            raise ValueError("invalid voice id")
        if len(samples)<3:
            raise ValueError("three independent clean utterances required")
        embeddings=[normalize(x) for x in samples]
        if len({len(v) for v in embeddings})!=1:
            raise ValueError("different embedding dimensions")
        # Avoid pooled recordings silently creating a profile for more than
        # one speaker. This is only a coarse quality guard, not diarization.
        if min(similarity(a,b) for i,a in enumerate(embeddings) for b in embeddings[i+1:])<0.55:
            raise ValueError("inconsistent enrollment utterances")
        mean=normalize([sum(x[i] for x in embeddings)/len(embeddings) for i in range(len(embeddings[0]))])
        self.profiles[speaker_id]=mean
    def forget(self,speaker_id):
        self.profiles.pop(speaker_id,None)
    def identify(self,embedding,model_id,quality_ok=False):
        if not quality_ok or model_id!=self.model_id or not self.profiles:
            return VoiceMatch()
        candidate=normalize(embedding)
        scores=sorted(((similarity(candidate,v),k) for k,v in self.profiles.items()
                       if len(v)==len(candidate)),reverse=True)
        if not scores:
            return VoiceMatch()
        best,speaker=scores[0]
        runner=scores[1][0] if len(scores)>1 else -1.0
        gap=best-runner
        if best<self.threshold or gap<self.margin:
            return VoiceMatch(score=round(best,4),margin=round(gap,4))
        return VoiceMatch(speaker_id=speaker,score=round(best,4),
                          margin=round(gap,4),recognized=True)

def owner_fact_permission(match):
    """Voice recognition is NOT authentication; no privileged owner writes."""
    return False
