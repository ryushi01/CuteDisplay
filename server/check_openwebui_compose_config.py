#!/usr/bin/env python3
"""Fail-closed validation of the existing Open WebUI Docker Compose service.

Read the JSON from `docker compose config --format json` via stdin. Never log
or print that JSON, because it may contain private environment credentials.
Compose logical volume labels may differ from the real Docker volume name.
"""
import argparse
import json
import sys

EXPECTED_VOLUME = "open-webui"
EXPECTED_TARGET = "/app/backend/data"
EXPECTED_PORT = 8080


def check_compose(cfg, image):
    services = cfg.get("services") or {}
    svc = services.get("open-webui")
    if not isinstance(svc, dict):
        raise ValueError("missing expected open-webui service")
    if svc.get("image") != image:
        raise ValueError("effective Open WebUI image differs from the requested image")
    mounts = [
        v for v in (svc.get("volumes") or [])
        if isinstance(v, dict) and v.get("target") == EXPECTED_TARGET
    ]
    if len(mounts) != 1 or mounts[0].get("type") != "volume":
        raise ValueError("expected exactly one persistent named-volume mount")
    logical = mounts[0].get("source")
    if not isinstance(logical, str) or not logical:
        raise ValueError("missing Compose volume source")
    # Docker Compose permits source=webui_data and volumes.webui_data.name=open-webui.
    # The running Docker mount name, not its logical label, is authoritative.
    vol_cfg = (cfg.get("volumes") or {}).get(logical) or {}
    actual = vol_cfg.get("name", logical)
    if actual != EXPECTED_VOLUME:
        raise ValueError("effective Docker volume is not the verified open-webui volume")
    exposed = svc.get("ports") or []
    def port_matches(port):
        if not isinstance(port, dict):
            return False
        return (str(port.get("published")) == str(EXPECTED_PORT)
                and str(port.get("target")) == str(EXPECTED_PORT)
                and port.get("protocol", "tcp") == "tcp")
    if not any(port_matches(p) for p in exposed):
        raise ValueError("expected existing published port 8080 to be preserved")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-image", required=True)
    args = parser.parse_args()
    try:
        cfg = json.load(sys.stdin)
        check_compose(cfg, args.expected_image)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        # Only static validation text is emitted. Never reveal Compose JSON.
        print(f"FAIL: Compose Open WebUI validation: {error}", file=sys.stderr)
        return 1
    print("PASS: expected image, actual open-webui volume and port 8080 preserved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
