#!/usr/bin/env python3
"""Log only the already-sanitized bridge failure reason, never provider details.

Applied while building the Kitty Open WebUI image. Exact anchors fail closed.
"""
import argparse
from pathlib import Path

OLD = "log.info('Bridge closed: user_id=%s error_type=%s', user.id if user else None, type(exc).__name__)"
NEW = "log.info('Bridge closed: error_type=%s reason=%s', type(exc).__name__, detail)"

def patch(source: str) -> str:
    if NEW in source:
        compile(source, "realtime.py", "exec")
        return source
    if source.count(OLD) != 1 or "if type(exc) is ValueError" not in source:
        raise ValueError("Unsupported realtime error handler; refusing unsafe modification")
    updated = source.replace(OLD, NEW, 1)
    compile(updated, "realtime.py", "exec")
    return updated

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source-root", default="/app")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    a = p.parse_args()
    target = Path(a.source_root) / "backend/open_webui/routers/audio/realtime.py"
    original = target.read_text()
    updated = patch(original)
    if a.apply and updated != original:
        target.write_text(updated)
    print("KITTY_BRIDGE_SAFE_DIAGNOSTICS_" + ("APPLIED" if a.apply else "VALID"))

if __name__ == "__main__":
    main()
