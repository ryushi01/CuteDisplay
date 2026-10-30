#!/usr/bin/env python3
"""Nonblocking gateway adapter for completed S3 microphone utterances.

The caller must supply a *completed* mono 24 kHz PCM16 utterance from the
gateway's already-established audio stream. This module never touches the
S3 mic/audio loop and never blocks a realtime response.
"""
import asyncio
import io
import os
from urllib import request
import wave

MAX_SOURCE_BYTES=24_000*2*12
DEFAULT_TIMEOUT=0.8

def wav16k_from_pcm24k(pcm):
    if not isinstance(pcm,bytes) or len(pcm)>MAX_SOURCE_BYTES or len(pcm)%2:
        raise ValueError("invalid 24k PCM")
    if len(pcm)<24_000*2*1.5:
        raise ValueError("too short")
    import numpy as np
    from scipy.signal import resample_poly
    samples=np.frombuffer(pcm,dtype="<i2").astype("float32")
    converted=resample_poly(samples,2,3)
    converted=np.clip(np.rint(converted),-32768,32767).astype("<i2").tobytes()
    buf=io.BytesIO()
    with wave.open(buf,"wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(converted)
    return buf.getvalue()

def _post(url,token,wav,timeout):
    r=request.Request(url.rstrip("/")+"/identify",data=wav,
        headers={"Content-Type":"audio/wav","Authorization":"Bearer "+token},
        method="POST")
    with request.urlopen(r,timeout=timeout) as response:
        if response.status!=200:
            raise ValueError("identify unavailable")
        import json
        return json.loads(response.read(2048))

async def recognize_completed_utterance(pcm24k, *, url=None,token=None,timeout=DEFAULT_TIMEOUT):
    """Fail to unknown; caller may attach result to an exact transcript turn.

    A timeout does not cancel a running CPU/network thread. Do not call this
    for every audio frame; enqueue only bounded, completed utterances.
    """
    url=url or os.getenv("KITTY_VOICE_URL","")
    token=token or os.getenv("KITTY_VOICE_TOKEN","")
    if not url or not token:
        return {"speaker_id":"unknown","confidence":"unknown"}
    timeout=max(0.05,min(float(timeout),1.5))
    try:
        wav=await asyncio.to_thread(wav16k_from_pcm24k,pcm24k)
        result=await asyncio.wait_for(
            asyncio.to_thread(_post,url,token,wav,timeout),timeout=timeout)
        if not isinstance(result,dict) or result.get("confidence")!="probable":
            return {"speaker_id":"unknown","confidence":"unknown"}
        sid=result.get("speaker_id")
        if not isinstance(sid,str) or not 1<=len(sid)<=64:
            return {"speaker_id":"unknown","confidence":"unknown"}
        return {"speaker_id":sid,"confidence":"probable"}
    except (Exception,asyncio.CancelledError):
        return {"speaker_id":"unknown","confidence":"unknown"}
