#!/usr/bin/env python3
"""CPU-only opt-in voice recognition component for Kitty V6.

Voiceprints are sensitive biometric data: enrollment is explicit and consent-
based. No voice recognition is attempted on ESP32 realtime audio callbacks.
Unknown is a first-class outcome. The threshold MUST be calibrated with the
actual INMP441 microphone and Japanese/English/French speech samples.
"""
import io
import math
import threading
import wave
from dataclasses import dataclass
import numpy as np

SAMPLE_RATE=16000
MIN_SECONDS=1.5
MAX_SECONDS=12.0
LOCK=threading.RLock()
_ENCODER=None

def pcm16_from_wav(blob):
    """Accept bounded mono 16kHz signed PCM WAV only. Caller must cap bytes."""
    if not isinstance(blob,bytes) or len(blob)>SAMPLE_RATE*2*MAX_SECONDS+4096:
        raise ValueError("invalid audio size")
    with wave.open(io.BytesIO(blob),"rb") as w:
        if w.getnchannels()!=1 or w.getframerate()!=SAMPLE_RATE or w.getsampwidth()!=2 or w.getcomptype()!="NONE":
            raise ValueError("expected mono 16kHz PCM16 WAV")
        frames=w.readframes(w.getnframes())
    samples=np.frombuffer(frames,dtype="<i2").astype("float32")/32768.0
    if not MIN_SECONDS<=len(samples)/SAMPLE_RATE<=MAX_SECONDS:
        raise ValueError("voice sample outside duration bounds")
    rms=float(np.sqrt(np.mean(samples*samples)))
    if rms<0.006 or rms>0.95:
        raise ValueError("silence or clipping")
    return samples

def embedding(samples):
    """Warm SpeechBrain ECAPA CPU encoder; actual model loads on first call."""
    global _ENCODER
    with LOCK:
        if _ENCODER is None:
            import torch
            from speechbrain.inference.speaker import EncoderClassifier
            _ENCODER=EncoderClassifier.from_hparams(
                source="speechbrain/spkrec-ecapa-voxceleb",
                savedir="pretrained_models/kitty_ecapa",
                run_opts={"device":"cpu"})
            _ENCODER.eval()
        import torch
        with torch.no_grad():
            value=_ENCODER.encode_batch(torch.from_numpy(samples).unsqueeze(0))
    result=value.detach().cpu().numpy().reshape(-1).astype("float32")
    length=np.linalg.norm(result)
    if not np.isfinite(length) or length<1e-8:
        raise ValueError("invalid embedding")
    return result/length

@dataclass(frozen=True)
class VoiceMatch:
    speaker_id:str
    score:float
    confidence:str

def identify(vector,profiles,threshold=0.72,margin=0.10):
    """Open-set matching: strict rejection on weak or ambiguous matches.

    Thresholds are deliberately NOT claimed to be calibrated or accurate.
    Never grant authorization solely because this function returns a match.
    """
    if not 0<threshold<1 or not 0<margin<1:
        raise ValueError("invalid matching thresholds")
    q=np.asarray(vector,dtype="float32").reshape(-1)
    if not q.size or not np.all(np.isfinite(q)):
        return VoiceMatch("unknown",0.0,"unknown")
    norm=float(np.linalg.norm(q))
    if norm<1e-8:
        return VoiceMatch("unknown",0.0,"unknown")
    q=q/norm
    ranked=[]
    for speaker,exemplars in profiles.items():
        if not speaker or speaker=="unknown":
            continue
        scores=[]
        for ex in exemplars:
            v=np.asarray(ex,dtype="float32").reshape(-1)
            if v.shape!=q.shape or not np.all(np.isfinite(v)):
                continue
            n=float(np.linalg.norm(v))
            if n>1e-8:
                scores.append(float(np.dot(q,v/n)))
        if scores:
            ranked.append((float(np.median(scores)),speaker))
    ranked.sort(reverse=True)
    if not ranked or ranked[0][0]<threshold:
        return VoiceMatch("unknown",round(ranked[0][0],4) if ranked else 0.0,"unknown")
    if len(ranked)>1 and ranked[0][0]-ranked[1][0]<margin:
        return VoiceMatch("unknown",round(ranked[0][0],4),"ambiguous")
    return VoiceMatch(ranked[0][1],round(ranked[0][0],4),"probable")

def enroll_profile(sample_vectors,minimum=3):
    """Caller must obtain explicit consent and stable identity label."""
    if len(sample_vectors)<minimum:
        raise ValueError("need at least three separate enrollment utterances")
    result=[]
    for value in sample_vectors:
        v=np.asarray(value,dtype="float32").reshape(-1)
        norm=float(np.linalg.norm(v))
        if not v.size or not np.isfinite(norm) or norm<1e-8:
            raise ValueError("invalid enrollment vector")
        result.append((v/norm).tolist())
    return result
