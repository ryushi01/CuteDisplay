"""Turn-bounded CPU speaker recognition adapter for the Kitty V6 realtime gateway.

This is not an upstream audio handler. The gateway feeds 24 kHz mono PCM16
microphone chunks to a bounded ring buffer and calls identify() only after
the upstream transcription supplies the matching item_id.
"""
import asyncio
import base64
import collections
import io
import json
import os
import struct
import wave
try:
    from .kitty_semantic_async_client_v6 import _UnixHTTPConnection
except ImportError:
    from kitty_semantic_async_client_v6 import _UnixHTTPConnection

RATE = 24000
MAX_SECONDS = 8
MAX_BYTES = RATE * 2 * MAX_SECONDS
MAX_B64_CHUNK = 65536


class SpeakerTurn:
    def __init__(self):
        self._pcm = bytearray()
        self._closed = False
        self._generation = 0

    def start(self):
        self._generation += 1
        self._pcm.clear()
        self._closed = False
        return self._generation

    def append_base64_pcm16(self, payload):
        if self._closed or not isinstance(payload, str) or len(payload) > MAX_B64_CHUNK:
            return False
        try:
            pcm = base64.b64decode(payload, validate=True)
        except (ValueError, Exception):
            return False
        if not pcm or len(pcm) % 2:
            return False
        # Keep the last 8 seconds, not every utterance in memory.
        self._pcm.extend(pcm)
        if len(self._pcm) > MAX_BYTES:
            del self._pcm[:len(self._pcm)-MAX_BYTES]
        return True

    def stop(self):
        self._closed = True

    def discard(self):
        self._generation += 1
        self._pcm.clear()
        self._closed = True

    def snapshot(self):
        return self._generation, bytes(self._pcm)


def _trim_quiet_edges(pcm):
    """Trim only quiet margins for CPU identification; preserve conversational audio."""
    if len(pcm) < 24000 * 2 * 2 or len(pcm) % 2:
        return pcm
    import math
    frame_bytes = 24000 * 2 // 10  # 100 ms at 24 kHz, mono 16-bit
    energies = []
    for start in range(0, len(pcm) - frame_bytes + 1, frame_bytes):
        frame = pcm[start:start + frame_bytes]
        count = len(frame) // 2
        samples = struct.unpack("<" + "h" * count, frame)
        energies.append(math.sqrt(sum(x * x for x in samples) / count) / 32768.)
    active = [i for i, energy in enumerate(energies) if energy >= 0.012]
    if not active:
        return pcm
    # Keep at least 200 ms around speech; avoid short or aggressively cut samples.
    first = max(0, active[0] - 2)
    last = min(len(energies), active[-1] + 3)
    candidate = pcm[first * frame_bytes:last * frame_bytes]
    return candidate if len(candidate) >= 24000 * 2 * 2 else pcm


def to_16k_wav(pcm24):
    """Pure Python bounded 24 kHz -> 16 kHz linear resample, mono PCM16."""
    if len(pcm24) % 2 or len(pcm24) > MAX_BYTES:
        raise ValueError("invalid_24k_pcm")
    pcm24 = _trim_quiet_edges(pcm24)
    n = len(pcm24) // 2
    if n < RATE * 3 // 2:
        raise ValueError("sample_too_short")
    samples = struct.unpack("<" + "h"*n, pcm24)
    out_n = n * 2 // 3
    out = bytearray(out_n * 2)
    for j in range(out_n):
        pos = j * 1.5
        a = int(pos)
        frac = pos - a
        b = min(a+1, n-1)
        value = round(samples[a]*(1-frac)+samples[b]*frac)
        struct.pack_into("<h", out, j*2, max(-32768, min(32767,value)))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(out)
    return buf.getvalue()


def _request_identify(socket_path, token, audio):
    conn = _UnixHTTPConnection(socket_path, 12.0)
    try:
        payload = json.dumps({"audio_wav_b64": base64.b64encode(audio).decode("ascii")}).encode()
        conn.request("POST", "/speaker/identify", body=payload,
                     headers={"Authorization": "Bearer "+token,
                              "Content-Type": "application/json"})
        res = conn.getresponse()
        if res.status != 200:
            return "unknown"
        obj = json.loads(res.read(4096))
        if obj.get("candidate_only") is True:
            candidate = obj.get("candidate_speaker_id")
            if not (isinstance(candidate,str) and candidate.startswith("person:") and len(candidate)<64):
                candidate = "unknown"
            return {"authorized":"unknown", "candidate":candidate}
        if obj.get("confidence") != "probable":
            return {"authorized":"unknown","candidate":"unknown"}
        sid = obj.get("speaker_id")
        if isinstance(sid,str) and sid.startswith("person:") and len(sid)<64:
            return {"authorized":sid,"candidate":"unknown"}
        return {"authorized":"unknown","candidate":"unknown"}
    except (OSError, ValueError, TimeoutError, KeyError):
        return "unknown"
    finally:
        conn.close()


async def identify_turn(url, token, item_id, pcm24, *, timeout=12.0):
    """Fail closed; never claim owner. Call via task, never await in audio loop."""
    if not (isinstance(item_id,str) and 1 <= len(item_id) <= 120):
        return None
    if not url.startswith("unix:///run/kitty-semantic/") or not token:
        return {"type":"kitty.speaker.result","item_id":item_id,
                "speaker_id":"unknown","confidence":"unknown"}
    try:
        audio = await asyncio.to_thread(to_16k_wav, pcm24)
        match = await asyncio.wait_for(
            asyncio.to_thread(_request_identify, url[len("unix://"):],
                              token, audio),timeout=timeout)
    except (ValueError, OSError, TimeoutError):
        match = {"authorized":"unknown","candidate":"unknown"}
    if not isinstance(match,dict):
        match = {"authorized":"unknown","candidate":"unknown"}
    sid = match.get("authorized","unknown")
    candidate = match.get("candidate","unknown")
    return {"type":"kitty.speaker.result","item_id":item_id,
            "speaker_id":sid,"confidence":"probable" if sid!="unknown" else "unknown",
            "candidate_speaker_id":candidate}
