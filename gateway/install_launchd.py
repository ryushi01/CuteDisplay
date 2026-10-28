#!/usr/bin/env python3
"""Install a per-user macOS LaunchAgent for the persistent CuteDisplay gateway.

The agent runs from the current Python virtualenv with private config file.
No credentials in command line, environment, plist, logs or Git. LaunchAgent
is active only while this macOS user is logged in; Mac must remain powered and
awake for the S3 to connect. Requires an already-tested --config JSON.
"""
import argparse
import os
from pathlib import Path
import plistlib
import sys

LABEL = "local.cutedisplay.realtime-gateway"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Private chmod-600 JSON config")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()
    dest = Path.home() / "Library" / "LaunchAgents" / (LABEL + ".plist")
    if args.uninstall:
        print("To remove this agent:")
        print(f"launchctl bootout gui/$(id -u) '{dest}'")
        print(f"rm -f '{dest}'")
        return 0

    config = Path(args.config).expanduser().resolve()
    if not config.is_file() or (config.stat().st_mode & 0o077):
        parser.error("Config must exist and have mode 0600")
    source = Path(__file__).with_name("cute_realtime_gateway.py").resolve()
    python = Path(sys.executable).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    log_dir = Path.home() / "Library" / "Logs" / "CuteDisplay"
    log_dir.mkdir(parents=True, exist_ok=True)
    plist = {
        "Label": LABEL,
        "ProgramArguments": [str(python), str(source), "--config", str(config)],
        "WorkingDirectory": str(source.parent.parent),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 15,
        "StandardOutPath": str(log_dir / "gateway.out.log"),
        "StandardErrorPath": str(log_dir / "gateway.error.log"),
    }
    with dest.open("wb") as f:
        plistlib.dump(plist, f)
    dest.chmod(0o600)
    print(f"Installed LaunchAgent: {dest}")
    print("Start now (Mac Terminal):")
    print(f"launchctl bootstrap gui/$(id -u) '{dest}'")
    print(f"launchctl kickstart -k gui/$(id -u)/{LABEL}")
    print("Check status:")
    print(f"launchctl print gui/$(id -u)/{LABEL}")
    print("macOS must remain awake and this user must stay logged in.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
