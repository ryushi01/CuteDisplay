#!/usr/bin/env python3
"""One-time interactive CuteDisplay gateway config writer.

Requires Open WebUI API key (sk-), direct Realtime provider URL/API key, an
existing CA-signed gateway certificate + private key. No password or TOTP.
Written JSON is chmod 0600 and NEVER belongs in Git. Shows 256-bit device
pairing key once so the user can enter it in the iPhone app.
"""
import argparse
from getpass import getpass
import json
import os
from pathlib import Path
import secrets
from urllib.parse import quote, urlsplit


def prompt(label, default=""):
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", default="gateway/private-config.json")
    args = p.parse_args()
    target = Path(args.output).expanduser().resolve()
    if target.exists():
        print("Config already exists. To rotate credentials, use a different output path or safely back up the old file.")
        return 1
    print("Configure persistent call gateway. Do NOT enter WebUI password or 2FA.")
    webui = prompt("Open WebUI public HTTPS base URL")
    model = prompt("Selected Kitty chat model ID", "cutedisplay-ai")
    webui_key = getpass("Dedicated Open WebUI API key (sk-, hidden): ").strip()
    print("Use Audio > Realtime's existing provider settings. The provider MUST expose an")
    print("OpenAI-compatible /realtime WebSocket; do not enter WebUI /api/v1/audio/realtime.")
    api_base = prompt("Upstream provider API base URL (e.g. http://127.0.0.1:8765/v1)")
    provider_model = prompt("Provider model name (e.g. local)", "local")
    provider_key = getpass("Realtime provider API key (hidden, not WebUI key): ").strip()
    voice = prompt("Realtime provider voice ID")
    transcription_model = prompt("Realtime transcription model")
    hostname = prompt("Gateway WSS hostname (must match TLS certificate; NOT 127.0.0.1 for S3)")
    port = prompt("Gateway WSS TCP port", "8766")
    cert = str(Path(prompt("Absolute path to gateway TLS certificate PEM")).expanduser().resolve())
    key = str(Path(prompt("Absolute path to gateway TLS private-key PEM")).expanduser().resolve())
    listen = prompt("Gateway listen address (0.0.0.0 for S3 Wi-Fi access)", "127.0.0.1")
    purl = urlsplit(api_base)
    if purl.scheme not in ("http", "https") or not purl.hostname or purl.query or purl.fragment or purl.username:
        raise SystemExit("Invalid provider base URL.")
    if purl.scheme == "http" and purl.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("Plaintext provider requires loopback on the same Mac. Configure HTTPS for remote provider.")
    if not webui.startswith("https://") or not webui_key.startswith("sk-"):
        raise SystemExit("An HTTPS Open WebUI URL and stable sk- API key are required.")
    if not hostname or not hostname.replace("-", "").replace(".", "").isalnum():
        raise SystemExit("Gateway hostname must be a DNS name matching the certificate.")
    if not cert or not key or not Path(cert).is_file() or not Path(key).is_file():
        raise SystemExit("TLS certificate and private key must already exist.")
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise SystemExit("Bad WSS port.")
    if not voice or not transcription_model:
        raise SystemExit("Voice and transcription model cannot be blank.")
    provider_ws = (
        ("wss" if purl.scheme == "https" else "ws") + "://" + purl.netloc
        + purl.path.rstrip("/") + "/realtime?model=" + quote(provider_model, safe="")
    )
    payload = {
        "device_id": "kitty-s3", "device_key": secrets.token_hex(32),
        "webui_url": webui.rstrip("/"), "webui_api_key": webui_key,
        "webui_model": model, "upstream_url": provider_ws, "upstream_key": provider_key,
        "voice": voice, "transcription_model": transcription_model,
        "tls_cert": cert, "tls_key": key,
        "listen_host": listen, "listen_port": int(port),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    target.chmod(0o600)
    print("\nPrivate gateway config saved at:", target)
    print("iPhone pairing WSS URL:", f"wss://{hostname}:{port}/")
    print("iPhone pairing device key (copy privately; DO NOT share in chat or Git):")
    print(payload["device_key"])
    print("\nPaste the public CA certificate into the iPhone app's CA field.")
    print("Do not paste your private TLS key or Open WebUI API key into that field.")
    print("Start gateway with: python gateway/cute_realtime_gateway.py --config " + str(target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
