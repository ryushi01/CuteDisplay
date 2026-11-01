#!/usr/bin/env python3
"""Local-only Kitty release intake UI. No deployment or arbitrary command execution."""
import argparse
import hashlib
import html
import json
import os
import secrets
import tempfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(os.environ.get("KITTY_UPDATE_ROOT", str(Path.home() / "kitty-v6/private/releases"))).resolve()
TOKEN = os.environ.get("KITTY_UPDATE_TOKEN", "")
MAX_UPLOAD = 32 * 1024 * 1024
KINDS = {"s3", "c5", "ubuntu", "mac", "bundle"}
MAGIC = {"s3": b"", "c5": b""}


def validate_name(name):
    return (isinstance(name, str) and 1 <= len(name) <= 80
            and all(c.isascii() and (c.isalnum() or c in "._-") for c in name)
            and not name.startswith(".") and ".." not in name)


def store_release(kind, name, content):
    if kind not in KINDS or not validate_name(name):
        raise ValueError("invalid kind or filename")
    if not content or len(content) > MAX_UPLOAD:
        raise ValueError("invalid upload length")
    if not name.lower().endswith((".bin", ".zip", ".tar.gz")):
        raise ValueError("invalid extension")
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    release_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(6)
    directory = ROOT / release_id
    directory.mkdir(mode=0o700)
    payload = directory / name
    with open(payload, "xb") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    digest = hashlib.sha256(content).hexdigest()
    metadata = {"id": release_id, "kind": kind, "filename": name,
                "sha256": digest, "size": len(content), "state": "quarantined"}
    (directory / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def release_health(item):
    """Checksum and image-header checks only; never authorize deployment."""
    try:
        from kitty_release_preflight_v6 import inspect_release
        report=inspect_release(ROOT/item["id"])
        if not report["checksum_valid"]:
            return "INVALID: checksum mismatch"
        if report["image_header_valid"] is False:
            return "INVALID: firmware header"
        if report["release_slot_fit"] is False:
            return "INVALID: exceeds reference slot"
        return "Verified artifact; deployment blocked pending device preflight"
    except (OSError,ValueError,KeyError,TypeError):
        return "INVALID: preflight unavailable"

def list_releases():
    if not ROOT.exists():
        return []
    output = []
    for path in sorted(ROOT.iterdir(), reverse=True):
        if not path.is_dir() or path.is_symlink():
            continue
        try:
            with open(path / "metadata.json", encoding="utf-8") as f:
                item = json.load(f)
            if isinstance(item, dict) and item.get("state") == "quarantined":
                item["health"]=release_health(item)
                output.append(item)
        except (OSError, ValueError):
            continue
    return output[:50]


class Handler(BaseHTTPRequestHandler):
    def authorize(self):
        supplied = self.headers.get("Authorization", "")
        # Browser login is via HTTP Basic; credentials are strictly local.
        import base64
        expected = "Basic " + base64.b64encode(("kitty:" + TOKEN).encode()).decode()
        return len(TOKEN) >= 32 and secrets.compare_digest(supplied, expected)

    def reject(self, status, body):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if status == 401:
            self.send_header("WWW-Authenticate", 'Basic realm="Kitty Update Center"')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self.authorize():
            return self.reject(401, "Authentication required")
        if urlparse(self.path).path != "/":
            return self.reject(404, "Not found")
        rows = "".join("<tr><td>" + html.escape(str(x.get("id", ""))) +
                       "</td><td>" + html.escape(str(x.get("kind", ""))) +
                       "</td><td>" + html.escape(str(x.get("filename", ""))) +
                       "</td><td>" + html.escape(str(x.get("size", ""))) +
                       "</td><td>Quarantined (not deployed)</td></tr>" for x in list_releases())
        page = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kitty Update Center</title><style>body{font:16px system-ui;max-width:850px;margin:4rem auto;padding:0 1rem;background:#101725;color:#e9edf6}
section{background:#1b2638;border-radius:14px;padding:25px;margin:20px 0}input,select,button{padding:10px;margin:8px}table{width:100%;border-collapse:collapse;word-break:break-word}
td,th{text-align:left;padding:8px;border-bottom:1px solid #425069}.warning{color:#ffcd7a}</style>
<h1>Kitty Update Center</h1><p class="warning">Local preview: uploads are quarantined. No flashing, restarts or deployments are enabled.</p>
<section><h2>Upload release artifact</h2><form action="/upload" method="POST" enctype="application/octet-stream" id="f">
<label>Target <select id="kind"><option>s3</option><option>c5</option><option>ubuntu</option><option>mac</option><option>bundle</option></select></label>
<input id="file" type="file" required><button type="submit">Upload to quarantine</button></form><p id="msg"></p></section>
<section><h2>Staged artifacts</h2><table><thead><tr><th>ID</th><th>Target</th><th>Filename</th><th>Bytes</th><th>Artifact verification (no deployment)</th></tr></thead><tbody>""" + rows + """</tbody></table></section>
<script>document.getElementById('f').onsubmit=async(e)=>{e.preventDefault();const file=document.getElementById('file').files[0];if(!file)return;
const m=document.getElementById('msg');m.textContent='Uploading...';try{const r=await fetch('/upload',{method:'POST',headers:{'X-Kitty-Kind':document.getElementById('kind').value,'X-Kitty-Filename':file.name,'Content-Type':'application/octet-stream'},body:file});
m.textContent=await r.text();if(r.ok)location.reload();}catch(err){m.textContent=String(err)}};</script></html>"""
        data = page.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; form-action 'self'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if not self.authorize():
            return self.reject(401, "Authentication required")
        if self.path != "/upload":
            return self.reject(404, "Not found")
        size = self.headers.get("Content-Length", "")
        if not size.isdecimal() or not (1 <= int(size) <= MAX_UPLOAD):
            self.close_connection = True
            return self.reject(413, "Upload too large")
        if self.headers.get("Content-Type", "") != "application/octet-stream":
            self.close_connection = True
            return self.reject(415, "Expected binary upload")
        try:
            result = store_release(self.headers.get("X-Kitty-Kind", ""),
                                   self.headers.get("X-Kitty-Filename", ""), self.rfile.read(int(size)))
        except (ValueError, OSError) as exc:
            return self.reject(400, "Invalid upload")
        return self.reject(201, "Staged: " + result["id"] + " SHA256 " + result["sha256"])

    def log_message(self, fmt, *args):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8890)
    args = parser.parse_args()
    if len(TOKEN) < 32:
        raise SystemExit("KITTY_UPDATE_TOKEN must be at least 32 characters")
    if args.host not in ("127.0.0.1", "::1"):
        raise SystemExit("Refusing non-loopback bind: place behind authenticated TLS proxy later")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
