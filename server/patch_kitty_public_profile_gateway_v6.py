#!/usr/bin/env python3
"""Strict, idempotent opt-in patch for realtime session.update instructions.

Only appends non-authorizing public profile text to an EXISTING session
instructions string. Never touches PCM events, memory authorization, or
user messages. Refuses unrecognized gateway layouts.
"""
import argparse
import ast
from pathlib import Path

MARKER = "# KITTY_PUBLIC_PROFILE_SESSION_V6"
ANCHOR = "                event = JSONCodec.loads(raw)"
HOOK = '''\n                # KITTY_PUBLIC_PROFILE_SESSION_V6
                if isinstance(event, dict) and event.get("type") == "session.update":
                    try:
                        from open_webui.kitty_public_profile_v6 import public_profile_instruction
                        session = event.get("session")
                        if isinstance(session, dict):
                            instructions = session.get("instructions")
                            addition = public_profile_instruction()
                            if (addition and isinstance(instructions, str)
                                    and addition not in instructions):
                                # Never overwrite instructions that the client set.
                                event = dict(event)
                                session = dict(session)
                                session["instructions"] = instructions + addition
                                event["session"] = session
                                raw = JSONCodec.dumps(event)
                    except Exception:
                        pass  # Public profile must never disrupt a voice call
'''

def patch(src):
    if MARKER in src:
        ast.parse(src)
        return src
    if src.count(ANCHOR) != 1:
        raise ValueError("Unexpected gateway event decoding layout")
    result = src.replace(ANCHOR, ANCHOR + HOOK, 1)
    ast.parse(result)
    return result

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    old = args.path.read_text()
    new = patch(old)
    if args.apply and new != old:
        import shutil
        shutil.copy2(args.path, args.path.with_name(args.path.name + ".pre-public-profile"))
        args.path.write_text(new)
    print("PUBLIC_PROFILE_GATEWAY_" + ("APPLIED" if args.apply else "VALIDATED"))
