#!/usr/bin/env python3
"""Kitty V6 device-facing snapshot ingress. TLS required, default loopback.

Separate device credential from private memory API token. Only snapshot
upload paths may be proxied. No voice vectors, memory recall, or owner
authorization endpoint is exposed by this component.
"""
import argparse
import hmac
import http.client
import json
import os
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ALLOWED = frozenset(("/snapshot/chunk", "/snapshot/finalize"))
MAX_BODY = 16_384
DEVICE_TOKEN = os.environ.get("KITTY_SYNC_DEVICE_TOKEN", "")
MEMORY_TOKEN = os.environ.get("KITTY_MEMORY_TOKEN", "")
UPSTREAM_HOST = "127.0.0.1"
UPSTREAM_PORT = 8766


def valid_config():
    return len(DEVICE_TOKEN) >= 32 and len(MEMORY_TOKEN) >= 32 and not hmac.compare_digest(DEVICE_TOKEN, MEMORY_TOKEN)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def reply(self, status, payload):
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            return self.reply(200, {"ok": True})
        return self.reply(404, {"error": "not_found"})

    def do_POST(self):
        if self.path not in ALLOWED:
            return self.reply(404, {"error": "not_found"})
        provided = self.headers.get("Authorization", "")
        if not valid_config() or not hmac.compare_digest(provided, "Bearer " + DEVICE_TOKEN):
            return self.reply(401, {"error": "unauthorized"})
        raw_length = self.headers.get("Content-Length", "")
        if not raw_length.isdecimal() or not (2 <= int(raw_length) <= MAX_BODY):
            self.close_connection = True
            return self.reply(413, {"error": "invalid_length"})
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            self.close_connection = True
            return self.reply(415, {"error": "json_required"})
        body = self.rfile.read(int(raw_length))
        try:
            message = json.loads(body)
            if not isinstance(message, dict):
                raise ValueError("expected JSON object")
        except (UnicodeDecodeError, ValueError):
            return self.reply(400, {"error": "invalid_json"})
        conn = http.client.HTTPConnection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=3)
        try:
            conn.request("POST", self.path, body, {
                "Authorization": "Bearer " + MEMORY_TOKEN,
                "Content-Type": "application/json",
            })
            response = conn.getresponse()
            data = response.read(MAX_BODY + 1)
            if response.status not in (200, 400, 401, 413, 503) or len(data) > MAX_BODY:
                raise ValueError("invalid upstream response")
            self.send_response(response.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (OSError, ValueError, http.client.HTTPException):
            return self.reply(502, {"error": "memory_api_unavailable"})
        finally:
            conn.close()

    def log_message(self, format, *args):
        # Avoid bearer tokens or personal content entering journald.
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8843)
    parser.add_argument("--cert", required=True)
    parser.add_argument("--key", required=True)
    args = parser.parse_args()
    if not valid_config():
        raise SystemExit("Missing independent strong device/memory credentials")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(args.cert, args.key)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
