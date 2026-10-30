#!/usr/bin/env python3
"""Read-only S3 capability inventory through existing challenge/HMAC LAN control.

Requires a previously provisioned 32-byte device LAN key (64 hex chars).
Never sends CMD, firmware data or credentials over the network.
The existing S3 LAN protocol is NOT encrypted: restrict use to trusted LAN.
"""
import argparse
import getpass
import hashlib
import hmac
import ipaddress
import json
import socket

FIELDS = {"OTA:FW", "OTA:RUNNING_SIZE", "OTA:NEXT_SIZE", "OTA:RUNNING_SUBTYPE",
          "OTA:BUSY", "OTA:DEPLOY_SUPPORTED"}
MAX_LINE = 256


def authorize(challenge, secret):
    if not challenge.startswith("CHALLENGE "):
        raise ValueError("unexpected challenge")
    nonce = challenge[len("CHALLENGE "):]
    if len(nonce) != 32 or any(c not in "0123456789abcdefABCDEF" for c in nonce):
        raise ValueError("invalid challenge nonce")
    if len(secret) != 64:
        raise ValueError("device LAN key must be 64 hex characters")
    try:
        key = bytes.fromhex(secret)
    except ValueError as exc:
        raise ValueError("device LAN key is not hexadecimal") from exc
    return "AUTH " + hmac.new(key, nonce.encode("ascii"), hashlib.sha256).hexdigest()


def read_line(conn):
    line = conn.readline(MAX_LINE + 1)
    if not line or len(line) > MAX_LINE or not line.endswith(b"\n"):
        raise ValueError("missing, oversized or unterminated device response")
    return line.rstrip(b"\r\n").decode("ascii")


def parse_inventory(lines):
    values = {}
    for line in lines:
        if line == "NACK":
            raise ValueError("device does not support OTA_CAPS")
        if ":" not in line:
            continue
        key, sep, value = line.rpartition(":")
        if key not in FIELDS or key in values:
            continue
        values[key] = value
    if set(values) != FIELDS:
        raise ValueError("incomplete OTA_CAPS response (firmware update needed)")
    for key in ("OTA:RUNNING_SIZE", "OTA:NEXT_SIZE", "OTA:RUNNING_SUBTYPE",
                "OTA:BUSY", "OTA:DEPLOY_SUPPORTED"):
        if not values[key].isdigit():
            raise ValueError("non-numeric OTA capability")
        values[key] = int(values[key])
    return {"firmware": values["OTA:FW"],
            "running_slot_bytes": values["OTA:RUNNING_SIZE"],
            "next_slot_bytes": values["OTA:NEXT_SIZE"],
            "busy": bool(values["OTA:BUSY"]),
            "deploy_supported": bool(values["OTA:DEPLOY_SUPPORTED"]),
            "running_subtype": values["OTA:RUNNING_SUBTYPE"]}


def inventory(host, secret, port=8848, timeout=4):
    address = ipaddress.ip_address(host)
    if not address.is_private:
        raise ValueError("device must use a private LAN address")
    with socket.create_connection((str(address), port), timeout=timeout) as raw:
        raw.settimeout(timeout)
        with raw.makefile("rwb", buffering=0) as conn:
            challenge = read_line(conn)
            conn.write((authorize(challenge, secret) + "\n").encode("ascii"))
            if read_line(conn) != "OK":
                raise ValueError("S3 authentication failed")
            conn.write(b"OTA_CAPS\n")
            lines = [read_line(conn) for _ in range(6)]
            return parse_inventory(lines)


def main():
    ap = argparse.ArgumentParser(description="Read-only S3 OTA partition inventory")
    ap.add_argument("host", help="ESP32-S3 private LAN IP")
    ap.add_argument("--port", type=int, default=8848)
    args = ap.parse_args()
    secret = getpass.getpass("S3 LAN key (64 hex chars, hidden): ")
    result = inventory(args.host, secret, args.port)
    print(json.dumps(result, indent=2))
    if not result["deploy_supported"]:
        print("Deployment unavailable: read-only inventory only.")


if __name__ == "__main__":
    main()
