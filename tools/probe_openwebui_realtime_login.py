#!/usr/bin/env python3
"""Prompt for Open WebUI password login, then run the no-audio realtime bridge probe.

The password and returned session token stay in memory. Supports local password
auth only; SSO/MFA accounts need an alternative authenticated test workflow.
Requires tools/probe_openwebui_realtime.py and websockets>=14,<17.
"""
import argparse
from getpass import getpass
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="HTTPS Open WebUI public URL")
    parser.add_argument("--model", required=True, help="Server-configured chat model ID")
    args = parser.parse_args()
    p = urlsplit(args.url.strip())
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.query or p.fragment:
        parser.error("Use the HTTPS Open WebUI base URL, without credentials, query or fragment")
    base = urlunsplit((p.scheme, p.netloc, p.path.rstrip("/"), "", ""))
    email = input("Open WebUI login email: ").strip()
    password = getpass("Open WebUI password (hidden): ")
    if not email or not password:
        parser.error("Login email and password required")

    body = json.dumps({"email": email, "password": password}).encode("utf-8")
    del password
    request = Request(base + "/api/v1/auths/signin", data=body,
                      headers={"Content-Type": "application/json"},
                      method="POST")
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except HTTPError as exc:
        print(f"Login HTTP {exc.code}. Password login may be disabled, or credentials/MFA need attention.", file=sys.stderr)
        return 1
    except (URLError, TimeoutError, ValueError) as exc:
        print(f"Unable to reach or decode login response: {type(exc).__name__}", file=sys.stderr)
        return 1
    token = payload.get("token")
    if not isinstance(token, str) or not token:
        print("Login did not provide a user-session token (possibly MFA/SSO). No probe attempted.", file=sys.stderr)
        return 1
    env = dict(os.environ)
    env["OPENWEBUI_SESSION_JWT"] = token
    script = Path(__file__).with_name("probe_openwebui_realtime.py")
    print("Authenticated; running WebSocket handshake test (no microphone/audio/LLM messages).", flush=True)
    return subprocess.run([sys.executable, str(script), "--url", base, "--model", args.model],
                          env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
