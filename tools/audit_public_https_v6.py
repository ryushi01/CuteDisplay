#!/usr/bin/env python3
"""Read-only external HTTPS routing audit; does not change proxy or Open WebUI."""
import json
import socket
import ssl
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

HOST = "ragnarok-project.com"
BASE = f"https://{HOST}"
PATHS = ("/", "/api/config", "/api/version")
def probe(path):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "KittyV6-readonly-audit/1", "Accept": "application/json,text/html"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return {"path": path, "status": resp.status, "final_host": urlsplit(resp.url).hostname, "content_type": resp.headers.get("Content-Type", ""), "server": resp.headers.get("Server", "")}
    except urllib.error.HTTPError as exc:
        return {"path": path, "status": exc.code, "content_type": exc.headers.get("Content-Type", ""), "server": exc.headers.get("Server", "")}
    except Exception as exc:
        return {"path": path, "error": f"{type(exc).__name__}: {exc}"}
def main():
    report = {"domain": HOST, "port": 443, "read_only": True}
    try:
        report["dns"] = sorted({row[4][0] for row in socket.getaddrinfo(HOST, 443, type=socket.SOCK_STREAM)})
        with socket.create_connection((HOST, 443), timeout=8) as raw:
            with ssl.create_default_context().wrap_socket(raw, server_hostname=HOST) as tls:
                report["tls"] = {"version": tls.version(), "certificate_verified": True}
    except Exception as exc:
        report["connection_error"] = f"{type(exc).__name__}: {exc}"
    report["paths"] = [probe(path) for path in PATHS]
    print(json.dumps(report, indent=2))
    return 0 if report.get("tls", {}).get("certificate_verified") else 1
if __name__ == "__main__":
    sys.exit(main())
