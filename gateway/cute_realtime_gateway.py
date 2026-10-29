#!/usr/bin/env python3
"""CuteDisplay experimental *persistent-identity* realtime gateway.

The board authenticates with a revocable 256-bit per-device secret. The gateway
uses a dedicated, revocable Open WebUI API key for model calls, never the user's
password, TOTP seed, or session JWT. It connects to the configured OpenAI-
Realtime-compatible upstream provider, NOT Open WebUI's JWT-only WSS bridge.

Audio protocol (after HMAC auth):
  device -> gateway: 100ms binary PCM16 mono @24kHz (4800 bytes)
  gateway -> device: binary PCM16 mono @24kHz; event JSON: state/caption/error
  control JSON: {"type":"call.stop"} / {"type":"call.mute","muted":true}
  gateway emits auth.challenge and auth.ok before voice upstream creation.

Experimental prototype: no guaranteed 24h chat persistence, no vendor-backed
AEC, no approval/tool UI semantics, no unattended deployment until configured.
All WSS network listening requires a TLS certificate and private key.
"""
import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import ssl
import sys
import time
from urllib.parse import urlsplit

import websockets
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

RATE = 24000
FRAME_LIMIT = 48000
MAX_SESSION_SECONDS = 30 * 60
MAX_MODEL_OUTPUT = 16000
MAX_HTTP_REPLY = 2 * 1024 * 1024

CHAT_TOOL = {
    "type": "function",
    "name": "generate_chat_completion",
    "description": (
        "Use the selected cutedisplay-ai chat model for substantive questions "
        "and requests needing reasoning, information or any action. Always use "
        "for questions about tools, capabilities or model identity. Do not use "
        "for greetings, thanks or simple small talk."
    ),
    "parameters": {
        "type": "object", "properties": {"request": {"type": "string"}},
        "required": ["request"], "additionalProperties": False,
    }
}
INSTRUCTIONS = (
    "You are Kitty-chan, the conversational voice assistant. Respond warmly, "
    "in the speaker's language, usually briefly. Everyday greetings and small "
    "talk can be answered directly. For substantive questions, work requests, "
    "model/tool capabilities, or questions that require new reasoning, invoke "
    "generate_chat_completion and wait for its result. Do not pretend to have "
    "performed actions you did not perform. After a tool result, give its "
    "answer in your own natural voice, preserving factual content. Do not "
    "repeat a completed request."
)


class GatewayError(Exception):
    pass


def demand(condition, reason):
    if not condition:
        raise GatewayError(reason)


def validate_url(url, *, schemes):
    p = urlsplit(url)
    demand(p.scheme in schemes and bool(p.hostname) and
           not p.username and not p.password and not p.fragment,
           "Use a valid TLS URL without credentials")
    if schemes == {"https"}:
        demand(not p.query, "Open WebUI base URL may not contain a query")
    return p


def device_proof(secret_hex, device_id, nonce):
    demand(len(secret_hex) == 64, "Device secret must be 32 bytes / 64 hex chars")
    secret = bytes.fromhex(secret_hex)
    return hmac.new(
        secret, f"CuteDisplay-RT-v1|{device_id}|{nonce}".encode(), hashlib.sha256
    ).hexdigest()


def text_only_answer(reply):
    if isinstance(reply, dict):
        for choice in reply.get("choices", []):
            if not isinstance(choice, dict):
                continue
            msg = choice.get("message") or {}
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
            if isinstance(content, list):
                value = " ".join(
                    x.get("text", "") for x in content if isinstance(x, dict)
                ).strip()
                if value:
                    return value
    raise GatewayError("Selected model produced no plain text")


class Settings:
    def __init__(self, payload):
        self.device_id = payload.get("device_id", "kitty-s3")
        self.device_key = payload.get("device_key", "")
        self.webui_url = payload.get("webui_url", "").rstrip("/")
        self.webui_api_key = payload.get("webui_api_key", "")
        self.webui_model = payload.get("webui_model", "cutedisplay-ai")
        self.upstream_url = payload.get("upstream_url", "")
        self.upstream_key = payload.get("upstream_key", "")
        self.voice = payload.get("voice", "")
        self.transcription_model = payload.get("transcription_model", "")
        self.cert = payload.get("tls_cert", "")
        self.private_key = payload.get("tls_key", "")
        self.listen_host = payload.get("listen_host", "127.0.0.1")
        self.listen_port = int(payload.get("listen_port", 8766))
        demand(self.device_id.isascii() and 1 <= len(self.device_id) <= 50 and
               self.device_id.replace("-", "").replace("_", "").isalnum(),
               "Invalid device ID")
        demand(len(self.device_key) == 64 and
               all(c in "0123456789abcdefABCDEF" for c in self.device_key),
               "Require a random 32-byte device key")
        validate_url(self.webui_url, schemes={"https"})
        upstream = validate_url(self.upstream_url, schemes={"wss", "ws"})
        # Plaintext is only acceptable on the exact same machine for the
        # private local provider; never over Mac/Ubuntu LAN or the internet.
        demand(upstream.scheme != "ws" or upstream.hostname in {"127.0.0.1", "localhost", "::1"},
               "Plaintext upstream WS is loopback-only; use WSS for network peers")
        demand(self.webui_api_key.startswith("sk-") and len(self.webui_api_key) > 20,
               "Provide a dedicated Open WebUI sk- API key")
        demand(self.voice and self.transcription_model and self.webui_model,
               "Configure upstream voice and transcription_model, plus webui_model")
        demand(bool(self.cert) and bool(self.private_key),
               "TLS certificate+key required even for LAN prototype")
        demand(self.listen_port in range(1, 65536), "Invalid listen_port")
        # Bind loopback by default until a real, hostname-verified TLS deployment.
        # The admin must consciously opt into any LAN/nonloopback bind.


async def chat_model(settings, query, history):
    """Call authenticated Open WebUI REST API using a stable service API key."""
    import urllib.request
    import urllib.error
    model_input = [m for m in history[-8:] if m["role"] in ("user", "assistant")]
    model_input.append({"role": "user", "content": query})
    payload = json.dumps({
        "model": settings.webui_model,
        "messages": model_input,
        "stream": False,
    }).encode()
    def sync():
        req = urllib.request.Request(
            settings.webui_url + "/api/chat/completions",
            data=payload, method="POST",
            headers={
                "Authorization": "Bearer " + settings.webui_api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=100) as response:
            raw = response.read(MAX_HTTP_REPLY + 1)
            demand(len(raw) <= MAX_HTTP_REPLY, "Model response too large")
            mime = response.headers.get("Content-Type", "")
            if "text/event-stream" in mime or raw.startswith(b"data:"):
                chunks = []
                for line in raw.decode("utf-8", "replace").splitlines():
                    if line.startswith("data:") and line[5:].strip() != "[DONE]":
                        try:
                            event = json.loads(line[5:])
                            chunks.extend(
                                x.get("delta", {}).get("content", "")
                                for x in event.get("choices", [])
                                if isinstance(x.get("delta", {}).get("content"), str)
                            )
                        except (ValueError, AttributeError, TypeError):
                            continue
                return "".join(chunks)[:MAX_MODEL_OUTPUT]
            return text_only_answer(json.loads(raw))[:MAX_MODEL_OUTPUT]
    try:
        answer = await asyncio.to_thread(sync)
    except (OSError, TimeoutError, ValueError) as e:
        # Never log upstream response bodies or tokens.
        raise GatewayError("Selected chat model call failed: " + type(e).__name__) from None
    demand(bool(answer), "Empty selected chat model response")
    return answer


async def authenticate_device(ws, settings):
    nonce = secrets.token_hex(24)
    await ws.send(json.dumps({"type": "auth.challenge", "nonce": nonce}))
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=8)
    except asyncio.TimeoutError:
        raise GatewayError("Authentication timed out")
    demand(isinstance(raw, str) and len(raw) <= 1024, "Invalid authentication frame")
    try:
        data = json.loads(raw)
    except ValueError:
        raise GatewayError("Invalid authentication JSON")
    demand(isinstance(data, dict) and data.get("type") == "auth" and
           data.get("device_id") == settings.device_id, "Invalid device identity")
    given = data.get("proof", "")
    demand(isinstance(given, str) and len(given) == 64, "Invalid proof length")
    expected = device_proof(settings.device_key, settings.device_id, nonce)
    demand(hmac.compare_digest(given.lower(), expected), "Invalid device proof")
    await ws.send(json.dumps({"type": "auth.ok", "sample_rate": RATE}))


async def voice_session(device_ws, settings):
    """Isolate the Open WebUI API key and the upstream realtime credential."""
    upstream_headers = (
        {"Authorization": "Bearer " + settings.upstream_key}
        if settings.upstream_key else {}
    )
    async with connect(
        settings.upstream_url, additional_headers=upstream_headers,
        max_size=512 * 1024, open_timeout=20, ping_interval=20,
        close_timeout=5,
    ) as provider:
        created = json.loads(await asyncio.wait_for(provider.recv(), timeout=20))
        demand(created.get("type") == "session.created",
               "Realtime upstream did not create session")

        await provider.send(json.dumps({
            "type": "session.update",
            "session": {
                "type": "realtime",
                "output_modalities": ["audio"],
                "instructions": INSTRUCTIONS,
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": RATE},
                        "transcription": {"model": settings.transcription_model},
                        "turn_detection": {
                            "type": "server_vad",
                            "interrupt_response": False,
                            "create_response": False,
                        },
                    },
                    "output": {"format": {"type": "audio/pcm", "rate": RATE},
                               "voice": settings.voice},
                },
                "tools": [CHAT_TOOL],
                "tool_choice": "auto",
            },
        }))
        updated = json.loads(await asyncio.wait_for(provider.recv(), timeout=20))
        demand(updated.get("type") == "session.updated",
               "Realtime upstream rejected session config")
        await device_ws.send(json.dumps({
            "type": "session.ready",
            "sample_rate": RATE,
            "chat_model": settings.webui_model,
        }))

        stop = asyncio.Event()
        mute = asyncio.Event()
        pending_inputs = {}
        history = []
        started_at = time.monotonic()
        answer_pending = False
        recent_tool = set()
        response_lock = asyncio.Lock()
        last_response_id = ""
        current_audio_bytes = 0

        async def incoming():
            while not stop.is_set():
                raw = await device_ws.recv()
                if isinstance(raw, bytes):
                    demand(not mute.is_set(), "Microphone sent audio while muted")
                    demand(0 < len(raw) <= FRAME_LIMIT and len(raw) % 2 == 0,
                           "Invalid microphone audio frame")
                    await provider.send(json.dumps({
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(raw).decode(),
                    }))
                else:
                    demand(len(raw) <= 4096, "Command too large")
                    try:
                        event = json.loads(raw)
                    except ValueError:
                        raise GatewayError("Invalid control frame")
                    kind = event.get("type")
                    if kind == "call.stop":
                        stop.set()
                        return
                    if kind == "call.mute" and type(event.get("muted")) is bool:
                        if event["muted"]:
                            mute.set()
                        else:
                            mute.clear()
                        await device_ws.send(json.dumps({
                            "type": "state",
                            "value": "MUTED" if mute.is_set() else "LISTENING",
                        }))
                    elif kind == "call.ping":
                        await device_ws.send(json.dumps({"type": "call.pong"}))
                    else:
                        raise GatewayError("Unsupported device command")

        async def provider_events():
            nonlocal answer_pending, last_response_id, current_audio_bytes
            while not stop.is_set():
                raw = await provider.recv()
                demand(isinstance(raw, str) and len(raw) <= 512 * 1024,
                       "Invalid realtime upstream frame")
                event = json.loads(raw)
                kind = event.get("type")
                if kind == "input_audio_buffer.speech_started":
                    await device_ws.send(json.dumps({"type": "state", "value": "USER_SPEAKING"}))
                elif kind == "input_audio_buffer.speech_stopped":
                    await device_ws.send(json.dumps({"type": "state", "value": "THINKING"}))
                elif kind == "conversation.item.input_audio_transcription.completed":
                    text = event.get("transcript", "").strip()
                    item_id = event.get("item_id", "")
                    if text and item_id and len(text) <= 8192:
                        pending_inputs[item_id] = text
                        await device_ws.send(json.dumps({
                            "type": "caption", "speaker": "user", "text": text[:1024]
                        }))
                        async with response_lock:
                            if not answer_pending:
                                answer_pending = True
                                await provider.send(json.dumps({
                                    "type": "response.create",
                                    "response": {"metadata": {"input_item_id": item_id}}
                                }))
                elif kind == "response.created":
                    response = event.get("response") or {}
                    last_response_id = response.get("id", "")
                elif kind == "response.output_audio_transcript.delta":
                    text = event.get("delta", "")
                    if isinstance(text, str) and text:
                        await device_ws.send(json.dumps({
                            "type": "caption", "speaker": "assistant",
                            "text": text[:640], "partial": True
                        }))
                elif kind == "response.output_audio.delta":
                    pcm = base64.b64decode(event.get("delta", ""), validate=True)
                    demand(bool(pcm) and len(pcm) % 2 == 0,
                           "Invalid speaker audio")
                    current_audio_bytes += len(pcm)
                    demand(current_audio_bytes <= RATE * 2 * 180,
                           "Response exceeded 3 minutes")
                    # Bound every outbound binary frame to 100ms of PCM.
                    for offset in range(0, len(pcm), 4800):
                        await device_ws.send(pcm[offset:offset + 4800])
                    await device_ws.send(json.dumps({"type": "state", "value": "SPEAKING"}))
                elif kind == "response.output_item.done":
                    item = event.get("item") or {}
                    if item.get("type") == "function_call":
                        demand(item.get("name") == "generate_chat_completion",
                               "Unsupported provider function")
                        call_id = item.get("call_id", "")
                        demand(call_id and call_id not in recent_tool,
                               "Missing or duplicate function call id")
                        recent_tool.add(call_id)
                        # Confirm the requested text came from a transcribed input.
                        arguments = json.loads(item.get("arguments", "{}"))
                        demand(isinstance(arguments.get("request"), str) and
                               0 < len(arguments["request"].strip()) <= 32000,
                               "Invalid model function arguments")
                        input_id = (event.get("response") or {}).get("metadata", {}).get("input_item_id")
                        # Some OpenAI realtime versions only provide metadata on response.created.
                        query = pending_inputs.get(input_id) if input_id else None
                        if not query:
                            query = list(pending_inputs.values())[-1] if pending_inputs else ""
                        demand(bool(query), "Delegation has no authenticated transcript")
                        # Run in separate task so provider events keep flowing.
                        async def delegate(cid=call_id, prompt=query):
                            nonlocal answer_pending
                            try:
                                answer = await chat_model(settings, prompt, history)
                                history.extend([
                                    {"role": "user", "content": prompt},
                                    {"role": "assistant", "content": answer},
                                ])
                                del history[:-8]
                                output = {"status": "completed", "answer": answer}
                            except GatewayError:
                                output = {"status": "failed", "answer": "The request could not be completed."}
                            # Wait for first response.done before creating result speech.
                            while answer_pending and not stop.is_set():
                                await asyncio.sleep(.05)
                            if not stop.is_set():
                                await provider.send(json.dumps({
                                    "type": "conversation.item.create",
                                    "item": {"type": "function_call_output",
                                             "call_id": cid, "output": json.dumps(output)},
                                }))
                                await provider.send(json.dumps({
                                    "type": "response.create",
                                    "response": {"tools": [], "tool_choice": "none",
                                                 "metadata": {"call_id": cid}},
                                }))
                                answer_pending = True
                        asyncio.create_task(delegate())
                elif kind == "response.done":
                    current_audio_bytes = 0
                    async with response_lock:
                        answer_pending = False
                    await device_ws.send(json.dumps({"type": "state", "value": "LISTENING"}))
                elif kind == "error":
                    await device_ws.send(json.dumps({
                        "type": "error", "code": "REALTIME_UPSTREAM"
                    }))
                if time.monotonic() - started_at > MAX_SESSION_SECONDS:
                    raise GatewayError("Maximum call duration reached")
        workers = [asyncio.create_task(incoming()),
                   asyncio.create_task(provider_events())]
        try:
            done, pending = await asyncio.wait(workers, return_when=asyncio.FIRST_COMPLETED)
            for item in done:
                exc = item.exception()
                if exc:
                    raise exc
        finally:
            stop.set()
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)


async def serve_device(ws, settings):
    try:
        await authenticate_device(ws, settings)
        await voice_session(ws, settings)
    except Exception as exc:
        # Return stable codes, no raw backend error data/tokens.
        code = type(exc).__name__
        if isinstance(exc, GatewayError):
            code = "GATEWAY_CONFIG_OR_PROTOCOL"
        elif isinstance(exc, websockets.exceptions.ConnectionClosed):
            return
        print(f"Gateway session ended: {code}", file=sys.stderr)
        try:
            await ws.send(json.dumps({"type": "error", "code": code}))
        except Exception:
            pass
    finally:
        await ws.close()


def load_settings(file):
    path = Path(file).expanduser()
    if path.stat().st_mode & 0o077:
        raise GatewayError("Gateway settings must be chmod 600")
    settings = Settings(json.loads(path.read_text()))
    return settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Private mode-0600 JSON config")
    args = parser.parse_args()
    settings = load_settings(args.config)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(settings.cert, settings.private_key)
    async def run():
        async with serve(
            lambda ws: serve_device(ws, settings),
            settings.listen_host, settings.listen_port,
            ssl=tls, max_size=65536, max_queue=8,
            compression=None, ping_interval=20,
            open_timeout=10,
        ):
            print(f"Gateway listening securely on {settings.listen_host}:{settings.listen_port}; "
                  "requires HMAC device pairing. No Open WebUI user login required.", flush=True)
            await asyncio.Future()
    try:
        asyncio.run(run())
    except (OSError, ValueError, GatewayError) as error:
        print("Gateway setup error: " + str(error), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
