#!/usr/bin/env python3
"""Read-only handshake check for Open WebUI's *Realtime* call bridge.

No microphone, audio playback, chat completion, or device firmware modification.
Requires: python -m pip install 'websockets>=14,<17' truststore
"""
import argparse
import asyncio
import json
import os
import sys
import ssl
from urllib.parse import urlsplit, urlunsplit

try:
    import truststore  # OS-native certificate validation (macOS Keychain)
except ImportError:
    print("Install TLS dependency first: python -m pip install truststore", file=sys.stderr)
    raise SystemExit(2)

try:
    from websockets.asyncio.client import connect
except ImportError:
    print("Install dependency: python -m pip install 'websockets>=14,<17'", file=sys.stderr)
    raise SystemExit(2)


def websocket_url(base):
    parts = urlsplit(base.strip())
    if parts.scheme not in ("https", "wss") or not parts.hostname:
        raise ValueError("Provide a valid HTTPS or WSS Open WebUI URL; never send session JWT over plaintext WebSocket")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Do not put credentials or query strings in the URL")
    scheme = "wss" if parts.scheme in ("https", "wss") else "ws"
    path = parts.path.rstrip("/")
    if path.endswith("/api/v1/audio/realtime"):
        return urlunsplit((scheme, parts.netloc, path, "", ""))
    return urlunsplit((scheme, parts.netloc, path + "/api/v1/audio/realtime", "", ""))


async def probe(args):
    token = os.environ.get("OPENWEBUI_SESSION_JWT", "").strip()
    model = args.model or os.environ.get("OPENWEBUI_MODEL_ID", "").strip()
    if not token or not model:
        raise ValueError("Set OPENWEBUI_SESSION_JWT and OPENWEBUI_MODEL_ID (or --model)")
    endpoint = websocket_url(args.url)
    # Do not print the token or URL credentials. TLS verification is on by default.
    print("Connecting to Open WebUI Realtime voice bridge (no audio will be sent).")
    secure_ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    async with connect(endpoint, ssl=secure_ctx, open_timeout=args.timeout, close_timeout=5, max_size=524288) as ws:
        auth = {"type": "auth", "token": token, "model_id": model}
        if args.chat_id:
            auth["chat_id"] = args.chat_id
        await ws.send(json.dumps(auth))
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=args.timeout)
        except asyncio.TimeoutError as exc:
            raise RuntimeError("No bridge response before timeout") from exc
        event = json.loads(raw)
        if event.get("type") == "bridge.error":
            raise RuntimeError("Bridge rejected connection: " + str(event.get("message", "unknown error")))
        if event.get("type") != "bridge.ready" or event.get("sample_rate") != 24000:
            raise RuntimeError("Unexpected bridge response type or sample rate: " + str(event.get("type")))
        print("PASS: bridge.ready; sample rate 24000 Hz; model " + str(event.get("model", "?")))
        await ws.send(json.dumps({"type": "bridge.ping"}))
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
        except asyncio.TimeoutError as exc:
            raise RuntimeError("No bridge.pong response") from exc
        event = json.loads(raw)
        if event.get("type") != "bridge.pong":
            raise RuntimeError("Unexpected ping reply: " + str(event.get("type")))
        print("PASS: bridge.pong; authenticated realtime transport is available.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Open WebUI base URL, HTTPS recommended")
    parser.add_argument("--model", help="Server-configured chat model ID; defaults to OPENWEBUI_MODEL_ID")
    parser.add_argument("--chat-id", help="Optional existing chat ID belonging to the authenticated user")
    parser.add_argument("--timeout", type=float, default=45.0, help="Connection/handshake timeout")
    args = parser.parse_args()
    if args.timeout <= 0 or args.timeout > 120:
        parser.error("--timeout must be between 0 and 120 seconds")
    try:
        asyncio.run(probe(args))
    except (ValueError, RuntimeError, OSError, TimeoutError, ConnectionError) as exc:
        print("FAIL: " + str(exc), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
