#!/usr/bin/env python3
"""Non-destructive Kitty V6 OTA deployment plan.

Validates the quarantined image against *reported* installed S3 slot sizes.
Does not modify S3 flash, C5, update-center releases, or running services.
Requires actual device OTA receiver support before a deploy action can exist.
"""
import argparse
import json
from pathlib import Path
from kitty_release_preflight_v6 import inspect_release

def create_plan(release_dir, device):
    size = device.get("next_slot_bytes")
    if type(size) is not int or size <= 0:
        size = None
    result = inspect_release(release_dir, installed_next_slot=size)
    blockers = list(result["blockers"])
    if not device.get("authenticated"):
        blockers.append("S3 LAN inventory has not been authenticated")
    if device.get("busy") is not False:
        blockers.append("S3 idle state is not confirmed")
    if device.get("deploy_supported") is not True:
        blockers.append("S3 does not advertise tested OTA receiver support")
    if device.get("firmware") in ("", None):
        blockers.append("running firmware version unavailable")
    if not device.get("rollback_verified"):
        blockers.append("S3 rollback recovery not confirmed")
    # Deployment intentionally cannot be authorized by this read-only planner.
    return {
        "release": result,
        "device": {k: device.get(k) for k in
                   ("firmware", "running_slot_bytes", "next_slot_bytes",
                    "busy", "deploy_supported", "rollback_verified")},
        "operation": "read_only_preflight",
        "deploy_allowed": False,
        "blockers": sorted(set(blockers)),
        "next_action": "Implement and test secure OTA receiver/rollback before deployment",
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("release_dir")
    ap.add_argument("--inventory-json", type=Path,
                    help="Device inventory JSON (never accepts credentials)")
    args = ap.parse_args()
    inventory = json.loads(args.inventory_json.read_text()) if args.inventory_json else {}
    print(json.dumps(create_plan(args.release_dir, inventory), indent=2))
if __name__ == "__main__":
    main()
