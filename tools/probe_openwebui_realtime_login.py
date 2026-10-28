#!/usr/bin/env python3
"""Prompt for Open WebUI password + authenticator code, then probe Realtime.

The password, MFA code and resulting session token are kept in process memory.
Supports local password + already-enrolled TOTP MFA (or no MFA). SSO,
unconfigured MFA, and administrator MFA resets require separate login workflows.
Requires tools/probe_openwebui_realtime.py, truststore and websockets>=14,<17.
"""
import argparse
from getpass import getpass
import json
import os
import socket
import ssl
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

try:
    import truststore  # macOS Keychain / OS-native certificate verification
except ImportError:
    print("Install TLS dependency first: python -m pip install truststore", file=sys.stderr)
    raise SystemExit(2)


def post_json(url, fields, action):
    body = json.dumps(fields).encode("utf-8")
    request = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=30,
                     context=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)) as response:
            payload = json.load(response)
    except HTTPError as exc:
        print(f"{action} failed (HTTP {exc.code}). Verify account settings and try again; no tokens were printed.",
              file=sys.stderr)
        return None
    except URLError as exc:
        reason = exc.reason
        if isinstance(reason, socket.gaierror):
            msg = "Host name could not be resolved. Use the real Open WebUI URL from Safari."
        elif isinstance(reason, (ssl.SSLError, ssl.SSLCertVerificationError)):
            msg = "TLS certificate validation failed using macOS native trust. Check the server certificate chain, hostname and Keychain trust; never disable TLS verification."
        elif isinstance(reason, (ConnectionRefusedError, ConnectionResetError)):
            msg = "Connection refused or reset. Check server, port, VPN and reverse proxy."
        elif isinstance(reason, (socket.timeout, TimeoutError)):
            msg = "Connection timed out. Check Wi-Fi/VPN and the server."
        else:
            msg = f"Network error ({type(reason).__name__}); check URL, DNS and connectivity."
        print(f"{action} failed: {msg}", file=sys.stderr)
        return None
    except (TimeoutError, ValueError) as exc:
        print(f"{action} failed ({type(exc).__name__}).", file=sys.stderr)
        return None
    if not isinstance(payload, dict):
        print(f"{action} returned an unexpected response.", file=sys.stderr)
        return None
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="HTTPS Open WebUI public URL")
    parser.add_argument("--model", required=True, help="Server-configured chat model ID")
    parser.add_argument("--audio-smoke", action="store_true", help="After 2FA, run a one-turn Mac mic/speaker test instead of ping-only probe")
    parser.add_argument("--two-turn", action="store_true", help="After 2FA, test two sequential speech turns on one WebSocket")
    parser.add_argument("--model-delegation", action="store_true", help="After 2FA, test substantive voice-to-chat-model delegation")
    args = parser.parse_args()
    p = urlsplit(args.url.strip())
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.query or p.fragment:
        parser.error("Use the real HTTPS Open WebUI base URL (from Safari), without credentials, query or fragment")
    if p.hostname.upper() == "YOUR-OPENWEBUI-HOST" or p.hostname.endswith(".example.com"):
        parser.error("The URL is a placeholder. Copy the real Open WebUI HTTPS address from Safari.")
    if args.model.strip().upper().startswith("YOUR-") or not args.model.strip():
        parser.error("The model ID is a placeholder. Use the real selected Kitty model ID.")
    if p.path.rstrip("/").startswith(("/c/", "/chat/", "/admin/")):
        parser.error("Use the Open WebUI base URL, not a chat or admin page URL.")
    base = urlunsplit((p.scheme, p.netloc, p.path.rstrip("/"), "", ""))
    email = input("Open WebUI login email: ").strip()
    password = getpass("Open WebUI password (hidden): ")
    if not email or not password:
        parser.error("Login email and password required")
    payload = post_json(
        base + "/api/v1/auths/signin",
        {"email": email, "password": password},
        "Password login",
    )
    del password
    if payload is None:
        return 1

    if payload.get("next_step") == "verify":
        challenge = payload.get("challenge_token")
        if not isinstance(challenge, str) or not challenge:
            print("Server sent MFA verification without a challenge token.", file=sys.stderr)
            return 1
        print("Password accepted. Open your authenticator app for a fresh one-time code.")
        code = getpass("6-digit authenticator code (hidden): ").strip()
        if len(code) != 6 or not code.isascii() or not code.isdigit():
            print("Expected six digits. No verification request sent.", file=sys.stderr)
            return 1
        payload = post_json(
            base + "/api/v1/auths/mfa/verify",
            {"challenge_token": challenge, "code": code, "recovery": False},
            "2FA verification",
        )
        del code
        if payload is None:
            return 1
        print("2FA verified.")
    elif payload.get("next_step"):
        print("This account needs a different login step ("
              + str(payload.get("next_step"))
              + "). Complete setup or use the normal browser login; do not disable MFA.",
              file=sys.stderr)
        return 1

    token = payload.get("token")
    if not isinstance(token, str) or not token:
        print("Login did not provide a user-session JWT. No probe attempted.", file=sys.stderr)
        return 1
    env = dict(os.environ)
    env["OPENWEBUI_SESSION_JWT"] = token
    if sum((args.audio_smoke, args.two_turn, args.model_delegation)) > 1:
        parser.error("Choose at most one of --audio-smoke, --two-turn, or --model-delegation")
    script_name = ("realtime_model_delegation_smoke.py" if args.model_delegation else
                   "realtime_two_turn_smoke.py" if args.two_turn else
                   "realtime_audio_smoke.py" if args.audio_smoke else
                   "probe_openwebui_realtime.py")
    script = Path(__file__).with_name(script_name)
    task_label = ("spoken selected-chat-model delegation test" if args.model_delegation else
                  "two-turn realtime speech test" if args.two_turn else
                  "one-turn microphone/speaker voice test" if args.audio_smoke else
                  "WebSocket handshake test (no microphone/audio/LLM messages)")
    print("Authenticated; running " + task_label + ".", flush=True)
    return subprocess.run([sys.executable, str(script), "--url", base, "--model", args.model],
                          env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
