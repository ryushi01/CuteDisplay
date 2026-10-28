#!/usr/bin/env python3
"""Two-turn Mac realtime voice test on ONE authenticated WebSocket.

No device firmware modifications, browser credentials in output, or automatic
chat-model delegation. Speak short small talk in French, pausing between turns.
Example: "Bonjour !" then, after Kitty has stopped speaking, "Ça va ?"
"""
import argparse
import asyncio
import base64
import json
import os
from pathlib import Path
import ssl
import sys
import time
import wave
from urllib.parse import urlsplit, urlunsplit

try:
    import sounddevice as sd
    import truststore
    from websockets.asyncio.client import connect
except ImportError:
    print("Install: python -m pip install sounddevice truststore 'websockets>=14,<17'", file=sys.stderr)
    raise SystemExit(2)

RATE = 24000
CHUNK_FRAMES = 2400
MAX_AUDIO_QUEUE = 48


def ws_url(base):
    url = urlsplit(base)
    if url.scheme not in ("https", "wss") or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError("Expected HTTPS Open WebUI URL without credentials or query")
    path = url.path.rstrip("/")
    if not path.endswith("/api/v1/audio/realtime"):
        path += "/api/v1/audio/realtime"
    return urlunsplit(("wss", url.netloc, path, "", ""))


def device(value):
    return int(value) if value and value.isdecimal() else value


async def get_event(ws, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Timed out waiting for realtime provider")
    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
    obj = json.loads(raw)
    if obj.get("type") == "bridge.error":
        raise RuntimeError("Bridge reported: " + str(obj.get("message", "unknown")))
    return obj


async def capture_audio(ws, halt, seconds, input_device):
    mic = sd.RawInputStream(
        samplerate=RATE, channels=1, dtype="int16",
        blocksize=CHUNK_FRAMES, device=device(input_device)
    )
    mic.start()
    try:
        deadline = time.monotonic() + seconds
        while not halt.is_set() and time.monotonic() < deadline:
            pcm, overflow = await asyncio.to_thread(mic.read, CHUNK_FRAMES)
            if halt.is_set():
                break
            if overflow:
                print("Microphone overflow (input dropped).", flush=True)
            if ws.transport.get_write_buffer_size() > 96000:
                raise RuntimeError("Realtime WebSocket upload too far behind (buffer >96 kB)")
            await ws.send(json.dumps({
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(bytes(pcm)).decode("ascii")
            }))
    finally:
        await asyncio.to_thread(mic.stop)
        mic.close()


async def hear_one_turn(ws, turn, args):
    halt = asyncio.Event()
    recording = asyncio.create_task(capture_audio(
        ws, halt, args.listen_seconds, args.input_device
    ))
    print(f"Turn {turn}/2: speak now, then pause for transcription.", flush=True)
    text = ""
    try:
        deadline = time.monotonic() + args.listen_seconds + 20
        while time.monotonic() < deadline:
            if recording.done() and recording.exception():
                raise recording.exception()
            try:
                event = await asyncio.wait_for(get_event(ws, deadline), timeout=1.0)
            except (asyncio.TimeoutError, TimeoutError):
                continue
            kind = event.get("type")
            if kind == "input_audio_buffer.speech_started":
                print(f"Turn {turn}: server VAD detected speech.", flush=True)
            elif kind == "conversation.item.input_audio_transcription.completed":
                text = event.get("transcript", "").strip()
                if text:
                    halt.set()
                    await asyncio.wait_for(recording, timeout=8)
                    print(f"Turn {turn}: transcribed: {text}", flush=True)
                    await ws.send(json.dumps({
                        "type": "bridge.respond", "item_id": event["item_id"]
                    }))
                    break
            elif kind == "conversation.item.input_audio_transcription.failed":
                print(f"Turn {turn}: transcription failed; try speaking clearly.", flush=True)
        if not text:
            raise RuntimeError(f"Turn {turn}: no completed speech transcription")
    finally:
        halt.set()
        if not recording.done():
            recording.cancel()
        await asyncio.gather(recording, return_exceptions=True)

    playback_q = asyncio.Queue(maxsize=MAX_AUDIO_QUEUE)
    pcm_saved = bytearray()

    async def play_answer():
        speaker = None
        try:
            while True:
                chunk = await playback_q.get()
                try:
                    if chunk is None:
                        break
                    if speaker is None:
                        speaker = sd.RawOutputStream(
                            samplerate=RATE, channels=1, dtype="int16",
                            blocksize=CHUNK_FRAMES, device=device(args.output_device)
                        )
                        speaker.start()
                    await asyncio.to_thread(speaker.write, chunk)
                    pcm_saved.extend(chunk)
                finally:
                    playback_q.task_done()
        finally:
            if speaker:
                await asyncio.to_thread(speaker.stop)
                speaker.close()

    player = asyncio.create_task(play_answer())
    status = ""
    try:
        deadline = time.monotonic() + args.response_timeout
        while time.monotonic() < deadline:
            if player.done() and player.exception():
                raise player.exception()
            try:
                event = await asyncio.wait_for(get_event(ws, deadline), timeout=1.0)
            except (asyncio.TimeoutError, TimeoutError):
                continue
            kind = event.get("type")
            if kind == "response.output_audio.delta":
                chunk = base64.b64decode(event.get("delta", ""), validate=True)
                if len(chunk) % 2:
                    raise RuntimeError("Invalid provider PCM")
                await asyncio.wait_for(playback_q.put(chunk), timeout=10)
            elif kind == "response.output_audio_transcript.delta":
                # Text is available, but this diagnostic avoids duplicating partial output.
                pass
            elif kind == "response.output_item.done" and event.get("item", {}).get("type") == "function_call":
                raise RuntimeError(
                    "Provider requested generate_chat_completion delegation. "
                    "This two-turn smoke test is small talk only; chat-model tools require a separate test."
                )
            elif kind == "response.done":
                status = event.get("response", {}).get("status", "")
                break
        if status != "completed":
            raise RuntimeError(f"Turn {turn}: response not complete, status={status or 'timed_out'}")
        await playback_q.put(None)
        await asyncio.wait_for(player, timeout=45)
        if not pcm_saved:
            raise RuntimeError(f"Turn {turn}: no spoken audio received")
        output = Path(args.output_dir).expanduser() / f"CuteDisplay-realtime-turn{turn}.wav"
        output.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(RATE)
            wav.writeframes(pcm_saved)
        print(f"Turn {turn}: response completed; {len(pcm_saved)/48000:.2f}s audio played and saved: {output}", flush=True)
        return text
    finally:
        if not player.done():
            player.cancel()
        await asyncio.gather(player, return_exceptions=True)


async def main_async(args):
    token = os.environ.get("OPENWEBUI_SESSION_JWT", "").strip()
    if not token:
        raise ValueError("Use probe_openwebui_realtime_login.py --two-turn (interactive password + 2FA)")
    tls = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    async with connect(ws_url(args.url), ssl=tls, max_size=524288, open_timeout=45, close_timeout=5) as ws:
        await ws.send(json.dumps({"type": "auth", "token": token, "model_id": args.model}))
        ready = await get_event(ws, time.monotonic() + 45)
        if ready.get("type") != "bridge.ready" or ready.get("sample_rate") != RATE:
            raise RuntimeError("Unexpected realtime handshake: " + str(ready.get("type")))
        print("Realtime connection ready. One WebSocket will remain open for two turns.", flush=True)
        for turn in (1, 2):
            await hear_one_turn(ws, turn, args)
        print("PASS: two sequential voice turns over one authenticated realtime WebSocket.", flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--listen-seconds", type=float, default=20)
    p.add_argument("--response-timeout", type=float, default=90)
    p.add_argument("--output-dir", default="~/Downloads")
    p.add_argument("--input-device")
    p.add_argument("--output-device")
    args = p.parse_args()
    if not (5 <= args.listen_seconds <= 60 and 15 <= args.response_timeout <= 180):
        p.error("Invalid listen/response timeout")
    try:
        asyncio.run(main_async(args))
    except (OSError, ValueError, RuntimeError, TimeoutError, sd.PortAudioError) as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
