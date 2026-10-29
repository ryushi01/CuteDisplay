#!/usr/bin/env python3
"""User-invoked smoke test: simulate a paired S3 without exposing device key.

This requires the WSS gateway already running, an appropriate certificate,
and realtime upstream provider configured. Sends NO audio / chat requests.
"""
import argparse
import asyncio
import json
from pathlib import Path
import ssl
import sys

from websockets.asyncio.client import connect
from cute_realtime_gateway import device_proof, load_settings


async def run(url, settings):
    ctx = ssl.create_default_context(cafile=settings.cert)
    async with connect(url, ssl=ctx, open_timeout=15, close_timeout=5) as ws:
        event = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if event.get("type") != "auth.challenge":
            raise RuntimeError("Missing secure device challenge")
        proof = device_proof(settings.device_key, settings.device_id, event["nonce"])
        await ws.send(json.dumps({
            "type": "auth", "device_id": settings.device_id, "proof": proof,
        }))
        event = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if event.get("type") != "auth.ok":
            raise RuntimeError("Device pairing rejected by gateway: " + event.get("type", "?"))
        print("PASS: gateway accepted the stored device HMAC key over verified TLS.", flush=True)
        event = json.loads(await asyncio.wait_for(ws.recv(), timeout=35))
        if event.get("type") != "session.ready":
            raise RuntimeError("Realtime provider did not become ready: " + event.get("type", "?"))
        if event.get("sample_rate") != 24000:
            raise RuntimeError("Unexpected audio rate")
        print("PASS: direct realtime provider session ready for selected chat model "
              + str(event.get("chat_model", "?")), flush=True)
        await ws.send(json.dumps({"type": "call.ping"}))
        event = json.loads(await asyncio.wait_for(ws.recv(), timeout=8))
        if event.get("type") != "call.pong":
            raise RuntimeError("Device-level ping/pong failed")
        print("PASS: secure persistent-identity device transport and keepalive (no audio).", flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", required=True, help="WSS hostname configured in the gateway certificate")
    p.add_argument("--config", required=True, help="Private gateway config, read locally only")
    args = p.parse_args()
    if not args.url.startswith("wss://"):
        p.error("Use WSS with hostname matching TLS certificate")
    try:
        asyncio.run(run(args.url, load_settings(args.config)))
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
