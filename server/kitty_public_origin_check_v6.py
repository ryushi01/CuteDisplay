#!/usr/bin/env python3
"""Non-destructive public HTTPS origin check. Does not require credentials."""
import argparse
import json
import socket
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlsplit

def check(origin, timeout=8):
    url = urlsplit(origin)
    if url.scheme != "https" or url.hostname is None or url.username or url.password or url.query or url.fragment or url.path not in ("", "/"):
        raise ValueError("expected HTTPS origin only (no credentials, query or path)")
    port = url.port or 443
    if port != 443:
        raise ValueError("expected external TLS port 443")
    result = {"origin": f"https://{url.hostname}", "port": port, "dns_ipv4": [], "tcp_443": False,
              "tls_valid": False, "http_status": None, "openwebui_confirmed": False}
    ipv4 = socket.getaddrinfo(url.hostname, 443, family=socket.AF_INET, type=socket.SOCK_STREAM)
    result["dns_ipv4"] = sorted({entry[4][0] for entry in ipv4})
    with socket.create_connection((url.hostname, port), timeout=timeout) as connection:
        result["tcp_443"] = True
        with ssl.create_default_context().wrap_socket(connection, server_hostname=url.hostname) as secured:
            result["tls_valid"] = secured.version() is not None
    req = urllib.request.Request(result["origin"] + "/api/version", headers={"User-Agent": "KittyV6-Preflight/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            result["http_status"] = response.status
            content_type = response.headers.get("Content-Type", "")
            body = response.read(4096)
            if response.status == 200 and "json" in content_type.lower():
                data = json.loads(body)
                result["openwebui_confirmed"] = isinstance(data, dict) and "version" in data
    except urllib.error.HTTPError as exc:
        result["http_status"] = exc.code
    return result

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--origin", default="https://ragnarok-project.com")
    args = ap.parse_args()
    try:
        result = check(args.origin)
    except Exception as exc:
        print(json.dumps({"origin": args.origin, "error": type(exc).__name__ + ": " + str(exc)}))
        raise SystemExit(1)
    print(json.dumps(result, indent=2))
    print("NOTE: Ubuntu network test only. S3 Wi-Fi/DNS/TLS and saved URL require device-side verification.")
    if not result["tls_valid"] or result["http_status"] is None:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
