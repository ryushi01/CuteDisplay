#!/usr/bin/env python3
"""Bounded realtime utterance collector for existing 24k PCM WebSocket frames.

Called by a patched gateway on input_audio_buffer.append, speech_stopped and
completed transcription events. Processing is scheduled in a separate task.
No archive or raw audio persistence on Ubuntu.
"""
import asyncio, base64, binascii
from collections import deque
from kitty_voice_gateway_adapter_v6 import recognize_completed_utterance

MAX_PCM=24_000*2*12
MAX_ENCODED=48_000
class UtteranceCollector:
    def __init__(self):
        self.parts=deque()
        self.size=0
        self.closed=False
        self.in_speech=False
        self.pending_audio=None
    def add(self,audio_b64):
        if self.closed or not isinstance(audio_b64,str) or len(audio_b64)>MAX_ENCODED:return
        try: audio=base64.b64decode(audio_b64,validate=True)
        except (ValueError,binascii.Error):return
        if not audio or len(audio)%2:return
        self.parts.append(audio);self.size+=len(audio)
        while self.size>MAX_PCM and self.parts:
            self.size-=len(self.parts.popleft())
    def speech_started(self):
        # Do not clear the ring: leading microphone frames are needed.
        self.in_speech=True
    def speech_stopped(self):
        self.in_speech=False
        data=b"".join(self.parts)
        self.parts.clear();self.size=0
        self.pending_audio=data if len(data)>=24_000*2*1.5 else None
    def pop_for_transcript(self):
        result=self.pending_audio
        self.pending_audio=None
        return result
    def clear(self):
        self.parts.clear();self.size=0;self.pending_audio=None
        self.closed=True

async def recognize_turn(collector,item_id,emit,timeout=0.8,transcript=""):
    """Emit only a turn-scoped probable claim or unknown. Never verify owner."""
    pcm=collector.pop_for_transcript()
    if not isinstance(item_id,str) or not 1<=len(item_id)<=160:
        return
    result={"speaker_id":"unknown","confidence":"unknown"}
    if pcm:
        try:
            result=await asyncio.wait_for(recognize_completed_utterance(pcm,timeout=timeout),timeout=timeout+0.1)
        except (Exception,asyncio.CancelledError):
            pass
    # Even if the utterance was too short for a biometric match,
    # preserve an explicit self-introduction as an UNVERIFIED claim.
    from kitty_voice_claims_v6 import reconcile_voice_and_claim
    attributed=reconcile_voice_and_claim(result,transcript)
    await emit({"type":"kitty.speaker.result","item_id":item_id,
        "speaker_id":attributed["speaker_id"],
        "confidence":attributed["confidence"],
        "claim_conflicts":attributed["claim_conflicts"]})
