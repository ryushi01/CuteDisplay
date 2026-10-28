#!/usr/bin/env python3
"""Mac diagnostic: speech -> Realtime tool call -> actual Open WebUI chat model -> speech.

Requires the 2FA helper (--model-delegation); no S3 firmware changes. This is
only a minimal model-delegation smoke test: it does NOT save chat history,
execute Open WebUI UI tools or support multi-turn model-context persistence.
Speak: "Demande au modèle de chat : combien font dix-sept fois vingt-trois ?"
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
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

try:
    import sounddevice as sd
    import truststore
    from websockets.asyncio.client import connect
except ImportError:
    print("Install: python -m pip install sounddevice truststore 'websockets>=14,<17'", file=sys.stderr)
    raise SystemExit(2)

from realtime_two_turn_smoke import capture_audio, device, get_event, ws_url, RATE

MAX_REPLY_BYTES = 12 * 1024 * 1024
MAX_CHAT_RESPONSE_BYTES = 2 * 1024 * 1024


def model_completion(base, jwt, model, utterance):
    """Minimal authenticated non-streaming text query for the *selected* model.

    Uses no chat_id or parent_id, hence does not modify an existing chat.
    This is NOT equivalent to the Open WebUI browser's full tool pipeline.
    """
    url = base.rstrip("/") + "/api/chat/completions"
    body = json.dumps({
        "model": model,
        "stream": False,
        "messages": [{"role": "user", "content": utterance}],
    }).encode()
    req = Request(
        url, method="POST", data=body,
        headers={"Authorization": "Bearer " + jwt,
                 "Content-Type": "application/json", "Accept": "application/json"}
    )
    try:
        with urlopen(req, timeout=120, context=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)) as resp:
            raw = resp.read(MAX_CHAT_RESPONSE_BYTES + 1)
            mime = resp.headers.get("Content-Type", "")
    except HTTPError as exc:
        raise RuntimeError(f"Selected model HTTP request rejected: status {exc.code}") from None
    except URLError as exc:
        raise RuntimeError(f"Selected model HTTP request unreachable: {type(exc.reason).__name__}") from None
    if len(raw) > MAX_CHAT_RESPONSE_BYTES:
        raise RuntimeError("Model reply exceeded 2MB diagnostic cap")
    if "text/event-stream" in mime or raw.startswith(b"data:"):
        fragments = []
        for line in raw.decode("utf-8", "replace").splitlines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
                for choice in obj.get("choices", []):
                    fragments.append(choice.get("delta", {}).get("content") or "")
            except (ValueError, AttributeError):
                pass
        answer = "".join(str(x) for x in fragments).strip()
    else:
        try:
            obj = json.loads(raw)
        except ValueError:
            raise RuntimeError("Model did not return valid JSON") from None
        answer = ""
        for choice in obj.get("choices", []):
            content = choice.get("message", {}).get("content")
            if isinstance(content, str):
                answer = content.strip()
                break
            if isinstance(content, list):
                answer = " ".join(x.get("text", "") for x in content if isinstance(x, dict)).strip()
                break
    if not answer:
        raise RuntimeError("Selected model returned no plain text")
    return answer[:16000]


async def run(args):
    token = os.environ.get("OPENWEBUI_SESSION_JWT", "").strip()
    if not token:
        raise ValueError("Launch through probe_openwebui_realtime_login.py --model-delegation")
    p = urlsplit(args.url)
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.query or p.fragment:
        raise ValueError("Use the actual HTTPS base URL")
    base = urlunsplit(("https", p.netloc, p.path.rstrip("/"), "", ""))
    tls = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    async with connect(ws_url(base), ssl=tls, max_size=524288, open_timeout=45, close_timeout=5) as ws:
        await ws.send(json.dumps({"type": "auth", "token": token, "model_id": args.model}))
        event = await get_event(ws, time.monotonic() + 45)
        if event.get("type") != "bridge.ready" or event.get("sample_rate") != RATE:
            raise RuntimeError("Unexpected handshake: " + str(event.get("type")))
        print("Realtime ready. Speak a substantive question in French (not small talk).", flush=True)
        print("Example: Demande au modèle de chat : combien font dix-sept fois vingt-trois ?", flush=True)

        halt = asyncio.Event()
        rec = asyncio.create_task(capture_audio(ws, halt, args.listen_seconds, args.input_device))
        transcript = ""
        try:
            deadline = time.monotonic() + args.listen_seconds + 20
            while time.monotonic() < deadline:
                if rec.done() and rec.exception():
                    raise rec.exception()
                try:
                    event = await asyncio.wait_for(get_event(ws, deadline), timeout=1.0)
                except (TimeoutError, asyncio.TimeoutError):
                    continue
                if event.get("type") == "input_audio_buffer.speech_started":
                    print("Server VAD detected speech.", flush=True)
                elif event.get("type") == "conversation.item.input_audio_transcription.completed":
                    transcript = event.get("transcript", "").strip()
                    if not transcript:
                        continue
                    halt.set()
                    await asyncio.wait_for(rec, timeout=8)
                    print("Transcribed: " + transcript, flush=True)
                    await ws.send(json.dumps({"type": "bridge.respond", "item_id": event["item_id"]}))
                    break
            if not transcript:
                raise RuntimeError("No transcribed question; try speaking again")
        finally:
            halt.set()
            if not rec.done():
                rec.cancel()
            await asyncio.gather(rec, return_exceptions=True)

        func_call = None
        phase = "initial"
        pcm = bytearray()
        first_reply = ""
        deadline = time.monotonic() + args.response_timeout

        while time.monotonic() < deadline:
            try:
                event = await asyncio.wait_for(get_event(ws, deadline), timeout=5.0)
            except asyncio.TimeoutError:
                continue
            typ = event.get("type", "")
            if typ == "response.output_item.done" and event.get("item", {}).get("type") == "function_call":
                item = event["item"]
                if item.get("name") != "generate_chat_completion":
                    raise RuntimeError("Unexpected provider tool: " + str(item.get("name")))
                if func_call:
                    raise RuntimeError("Multiple model delegations not supported by this diagnostic")
                func_call = item.get("call_id")
                if not func_call:
                    raise RuntimeError("Provider omitted function call ID")
                print("PASS: realtime provider requested generate_chat_completion.", flush=True)
            elif typ == "response.output_audio.delta":
                audio = base64.b64decode(event.get("delta", ""), validate=True)
                if len(audio) % 2:
                    raise RuntimeError("Invalid provider PCM length")
                if len(pcm) + len(audio) > MAX_REPLY_BYTES:
                    raise RuntimeError("Voice reply exceeds 12MB limit")
                pcm.extend(audio)
            elif typ == "response.done":
                if phase == "initial":
                    if not func_call:
                        print("INCOMPLETE: provider answered without delegating to cutedisplay-ai.", flush=True)
                        return 1
                    # The original function-call response must finish before creating a reply.
                    print("Requesting answer from Open WebUI chat model: " + args.model, flush=True)
                    answer = await asyncio.to_thread(model_completion, base, token, args.model, transcript)
                    print("PASS: selected model replied. Text preview: " + answer[:200], flush=True)
                    await ws.send(json.dumps({
                        "type": "bridge.result", "call_id": func_call, "status": "completed",
                        "answer": answer,
                    }))
                    await ws.send(json.dumps({"type": "bridge.respond", "call_id": func_call}))
                    phase = "spoken_result"
                    pcm.clear()  # Discard any initial verbal preamble.
                else:
                    if event.get("response", {}).get("status") != "completed":
                        raise RuntimeError("Provider speech was not completed")
                    break

        if phase != "spoken_result" or not pcm:
            raise RuntimeError("No completed spoken model result received")
        # Play only after all websocket messages have arrived, so the microphone
        # is definitely closed and cannot self-trigger.
        with sd.RawOutputStream(samplerate=RATE, channels=1, dtype="int16",
                                device=device(args.output_device)) as speaker:
            for i in range(0, len(pcm), 4800):
                await asyncio.to_thread(speaker.write, bytes(pcm[i:i + 4800]))

        file = Path(args.output).expanduser()
        file.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(file), "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(RATE)
            f.writeframes(pcm)
        print(f"PASS: selected chat model delegation -> realtime spoken reply ({len(pcm)/48000:.2f}s), saved: {file}", flush=True)
        return 0


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--listen-seconds", type=float, default=20)
    p.add_argument("--response-timeout", type=float, default=180)
    p.add_argument("--output", default="~/Downloads/CuteDisplay-model-delegation.wav")
    p.add_argument("--input-device")
    p.add_argument("--output-device")
    args = p.parse_args()
    if not (5 <= args.listen_seconds <= 60 and 30 <= args.response_timeout <= 300):
        p.error("Invalid timeout settings")
    try:
        raise SystemExit(asyncio.run(run(args)))
    except (OSError, ValueError, RuntimeError, TimeoutError, sd.PortAudioError) as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
