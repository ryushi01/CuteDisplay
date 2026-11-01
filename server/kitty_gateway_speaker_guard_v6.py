#!/usr/bin/env python3
"""Safely patch the deployed Open WebUI gateway to reject spoofed speaker recall.

This intentionally does NOT enable voice identification or upstream memory
injection. The existing semantic side-channel must fail closed until the
server independently identifies the exact same item. Run --check first.
"""
import argparse
from pathlib import Path

ANCHOR = "                if isinstance(event, dict) and event.get('type') == 'kitty.memory.semantic':"
OLD = """                    # Schedule CPU/HTTP recall separately: never pause the
                    # WebSocket consumer or wait in the audio event loop."""
GUARD = """                    # SECURITY: S3-supplied person:ID is not authentication.
                    # Until a server-observed, item-bound voice result exists,
                    # per-person semantic context MUST NOT be retrieved.
                    # Flag defaults OFF. Do not enable until gateway identity
                    # binding is implemented and tested.
                    if not kitty_server_verified_speaker_turn:
                        continue
"""

def patch(source):
    if "kitty_server_verified_speaker_turn" in source:
        return source
    if source.count(ANCHOR) != 1 or source.count(OLD) != 1:
        raise ValueError("Unexpected gateway layout; refused to patch")
    # Keep a constant false gate rather than accepting client asserted IDs.
    scope = "        async def client_events():"
    if source.count(scope) != 1:
        raise ValueError("Ambiguous client event function")
    source = source.replace(scope,
        "        kitty_server_verified_speaker_turn = False  # fail closed\n" + scope, 1)
    source = source.replace(OLD, GUARD + OLD, 1)
    compile(source, "realtime.py", "exec")
    return source

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if args.check == args.apply:
        ap.error("choose exactly one of --check or --apply")
    path = Path(args.file)
    original = path.read_text()
    modified = patch(original)
    if args.apply and modified != original:
        import os
        from tempfile import NamedTemporaryFile
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as temp:
            temp.write(modified)
            temp.flush()
            os.fsync(temp.fileno())
            tmp = temp.name
        os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    print("KITTY_SPEAKER_GUARD_" + ("PATCHED" if args.apply else "VALID"))

if __name__ == "__main__":
    main()
