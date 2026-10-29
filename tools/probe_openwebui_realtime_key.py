#!/usr/bin/env python3
"""Verify one Open WebUI origin's Realtime WebSocket with a dedicated sk- key.

No password, no TOTP, no user JWT; an already-patched and permission-checked
Open WebUI server is required. The key is entered with a hidden prompt, never
written to Git or disk. The normal Open WebUI HTTPS address is the only URL.
"""
import argparse
import asyncio
from getpass import getpass
import json
import ssl
from urllib.parse import urlsplit, urlunsplit

import truststore
from websockets.asyncio.client import connect


async def probe(url, model, secret):
    p = urlsplit(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.query or p.fragment:
        raise ValueError("Use the HTTPS Open WebUI base URL from Safari")
    path = p.path.rstrip("/") + "/api/v1/audio/realtime"
    wss = urlunsplit(("wss", p.netloc, path, "", ""))
    async with connect(wss, ssl=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
                       max_size=524288, open_timeout=40, close_timeout=5) as ws:
        await ws.send(json.dumps({"type": "auth", "token": secret, "model_id": model}))
        event = json.loads(await asyncio.wait_for(ws.recv(), timeout=50))
        if event.get("type") != "bridge.ready":
            print("FAIL: Open WebUI did not authorize realtime using the API key.")
            print("Response category:", event.get("type", "unknown"))
            return 1
        if event.get("sample_rate") != 24000:
            print("FAIL: unexpected realtime sample rate.")
            return 1
        print("PASS: one WebUI URL, persistent API key -> 24 kHz realtime session.")
        await ws.send(json.dumps({"type": "bridge.ping"}))
        event = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
        if event.get("type") != "bridge.pong":
            print("FAIL: realtime session ping was not accepted.")
            return 1
        print("PASS: authenticated WebUI realtime ping/pong without password or 2FA.")
        return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", required=True)
    ap.add_argument("--model", default="cutedisplay-ai")
    args = ap.parse_args()
    secret = getpass("Dedicated Open WebUI API key (hidden, sk-): ")
    if not (secret.startswith("sk-") and len(secret) > 20):
        ap.error("Use a revocable Open WebUI sk- API key, not a human password")
    try:
        raise SystemExit(asyncio.run(probe(args.url, args.model, secret)))
    except (ValueError, TimeoutError, OSError, ssl.SSLError) as err:
        print("FAIL:", type(err).__name__, "(verify WebUI patch, call permissions, certificate)")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
