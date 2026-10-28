#!/usr/bin/env python3
"""One-turn Mac microphone/speaker smoke test for Open WebUI Realtime.

Not production firmware. Captures 24 kHz microphone input, waits for VAD/STT,
requests one spoken reply, then plays and saves its PCM locally. Say a short
ordinary greeting (e.g. "こんにちは、キティちゃん。元気？"); this diagnostic does
not execute Open WebUI model-tool delegation. No microphone audio is saved.
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
FRAME = 2400  # 100 ms signed mono 16-bit PCM. Below the 48 kB event limit.


def websocket_url(base):
    p = urlsplit(base)
    if p.scheme not in ("https", "wss") or not p.hostname or p.username or p.password or p.query or p.fragment:
        raise ValueError("Open WebUI must use a valid HTTPS/WSS address")
    path = p.path.rstrip("/")
    if not path.endswith("/api/v1/audio/realtime"):
        path += "/api/v1/audio/realtime"
    return urlunsplit(("wss", p.netloc, path, "", ""))


def device(value):
    return int(value) if value and value.isdigit() else value


async def run(args):
    token = os.environ.get("OPENWEBUI_SESSION_JWT", "").strip()
    if not token:
        raise ValueError("Run through probe_openwebui_realtime_login.py --audio-smoke")
    endpoint = websocket_url(args.url)
    tls = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    async with connect(endpoint, ssl=tls, max_size=524288, open_timeout=45, close_timeout=5) as ws:
        await ws.send(json.dumps({"type": "auth", "token": token, "model_id": args.model}))
        response = json.loads(await asyncio.wait_for(ws.recv(), timeout=45))
        if response.get("type") != "bridge.ready" or response.get("sample_rate") != RATE:
            raise RuntimeError("Realtime not ready: " + str(response.get("message", response.get("type"))))
        print("Voice bridge ready at 24 kHz. Say: こんにちは、キティちゃん。元気？", flush=True)
        print("After speaking, pause briefly so server VAD can finish the sentence.", flush=True)

        mic = sd.RawInputStream(samplerate=RATE, channels=1, dtype="int16",
                                blocksize=FRAME, device=device(args.input_device))
        stop_capture = asyncio.Event()
        playback_queue = asyncio.Queue(maxsize=48)
        received_pcm = bytearray()
        transcription = ""
        reply_done = False
        deadline = time.monotonic() + args.listen_seconds + args.response_timeout

        async def record_and_send():
            mic.start()
            try:
                capture_until = time.monotonic() + args.listen_seconds
                while not stop_capture.is_set() and time.monotonic() < capture_until:
                    pcm, overflow = await asyncio.to_thread(mic.read, FRAME)
                    if stop_capture.is_set():
                        break
                    if overflow:
                        print("Warning: microphone overflow", flush=True)
                    await ws.send(json.dumps({
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(bytes(pcm)).decode("ascii"),
                    }))
            finally:
                await asyncio.to_thread(mic.stop)
                mic.close()

        async def play():
            speaker = None
            try:
                while True:
                    pcm = await playback_queue.get()
                    try:
                        if pcm is None:
                            break
                        if speaker is None:
                            speaker = sd.RawOutputStream(
                                samplerate=RATE, channels=1, dtype="int16",
                                blocksize=FRAME, device=device(args.output_device)
                            )
                            speaker.start()
                        received_pcm.extend(pcm)
                        await asyncio.to_thread(speaker.write, pcm)
                    finally:
                        playback_queue.task_done()
            finally:
                if speaker is not None:
                    speaker.stop()
                    speaker.close()

        recorder = asyncio.create_task(record_and_send())
        player = asyncio.create_task(play())
        try:
            requested = False
            while time.monotonic() < deadline:
                for task in (recorder, player):
                    if task.done() and not task.cancelled() and task.exception():
                        raise task.exception()
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=min(5, max(.1, deadline-time.monotonic())))
                except asyncio.TimeoutError:
                    continue
                event = json.loads(message)
                kind = event.get("type", "")
                if kind == "bridge.error":
                    raise RuntimeError("Bridge reported: " + str(event.get("message", "unknown")))
                if kind == "input_audio_buffer.speech_started":
                    print("Server detected speech.", flush=True)
                elif kind == "conversation.item.input_audio_transcription.completed" and not requested:
                    transcript = event.get("transcript", "").strip()
                    if transcript:
                        transcription = transcript
                        print("Transcribed: " + transcript, flush=True)
                        stop_capture.set()  # Avoid echo when server starts speaking.
                        await ws.send(json.dumps({"type": "bridge.respond", "item_id": event["item_id"]}))
                        requested = True
                        print("Requested voice reply.", flush=True)
                elif kind == "conversation.item.input_audio_transcription.failed":
                    print("Server could not transcribe this segment.", flush=True)
                elif kind == "response.output_audio.delta":
                    pcm = base64.b64decode(event.get("delta", ""), validate=True)
                    if len(pcm) % 2:
                        raise RuntimeError("Invalid PCM response")
                    await asyncio.wait_for(playback_queue.put(pcm), timeout=10)
                elif kind == "response.output_item.done" and event.get("item", {}).get("type") == "function_call":
                    print("The provider requested a chat-model tool. This one-turn smoke test only handles small talk.", flush=True)
                    break
                elif kind == "response.done" and requested:
                    print("Voice response status: " + str(event.get("response", {}).get("status")), flush=True)
                    reply_done = True
                    break

            stop_capture.set()
            await asyncio.wait_for(recorder, timeout=8)
            await playback_queue.put(None)
            await asyncio.wait_for(player, timeout=45)
            if received_pcm:
                output = Path(args.output).expanduser()
                output.parent.mkdir(parents=True, exist_ok=True)
                with wave.open(str(output), "wb") as f:
                    f.setnchannels(1)
                    f.setsampwidth(2)
                    f.setframerate(RATE)
                    f.writeframes(received_pcm)
                print(f"Played and saved {len(received_pcm)/(RATE*2):.2f}s response audio: {output}", flush=True)
            if transcription and reply_done and received_pcm:
                print("PASS: microphone -> VAD/STT -> realtime voice -> Mac speaker", flush=True)
                return 0
            print(f"INCOMPLETE: transcript={bool(transcription)}, response={reply_done}, audio={bool(received_pcm)}", flush=True)
            return 1
        finally:
            stop_capture.set()
            for task in (recorder, player):
                if not task.done():
                    task.cancel()
            await asyncio.gather(recorder, player, return_exceptions=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--listen-seconds", type=float, default=25)
    p.add_argument("--response-timeout", type=float, default=75)
    p.add_argument("--output", default="~/Downloads/CuteDisplay-realtime-smoke.wav")
    p.add_argument("--input-device", help="Optional sounddevice input name or number")
    p.add_argument("--output-device", help="Optional sounddevice output name or number")
    args = p.parse_args()
    if not (5 <= args.listen_seconds <= 60 and 15 <= args.response_timeout <= 180):
        p.error("listen-seconds must be 5–60, response-timeout 15–180")
    try:
        raise SystemExit(asyncio.run(run(args)))
    except (OSError, RuntimeError, ValueError, TimeoutError, sd.PortAudioError) as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("If audio initialization failed: check macOS Privacy & Security > Microphone for Terminal; "
              "run python -m sounddevice to list devices.", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
