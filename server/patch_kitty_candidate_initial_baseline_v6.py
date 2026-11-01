#!/usr/bin/env python3
"""Capture initial provider instructions for the existing candidate callback.

Never overwrite the initial session; wrapper forwards the identical payload.
Fails if anchors differ, makes backup, validates Python before writing.
"""
import argparse
import ast
import re
import shutil
from pathlib import Path

MARKER = "# KITTY_CAPTURE_INITIAL_PROMPT_V6"
CALLBACK_BASE = "_kitty_base_instructions = ((event.get('session') or {}).get('instructions') or '')"

def patch(src):
    if MARKER in src:
        ast.parse(src)
        return src
    if src.count(CALLBACK_BASE) != 1 or "on_candidate=kitty_candidate_hint" not in src:
        raise ValueError("Candidate callback not deployed as expected")
    # Restrict to the first initial session sent by the server. No client forwarding.
    match = re.search(r"(?m)^(?P<indent> +)await upstream[.]send_json[(]\\s*\\{\\s*"
                      r"['\x22]type['\x22]\\s*:\\s*['\x22]session[.]update['\x22]", src)
    if not match:
        raise ValueError("Server-generated initial session.update not found")
    indent = match.group("indent")
    if len(indent) != 12:
        raise ValueError("Unexpected initial session nesting")
    wrapper = (
        indent + MARKER + "\n"
        + indent + "kitty_initial_instructions = ''\n"
        + indent + "async def _kitty_forward_initial_session(payload):\n"
        + indent + "    nonlocal kitty_initial_instructions\n"
        + indent + "    session = payload.get('session', {})\n"
        + indent + "    if isinstance(session, dict) and isinstance(session.get('instructions'), str):\n"
        + indent + "        kitty_initial_instructions = session['instructions']\n"
        + indent + "    await upstream.send_json(payload)\n"
    )
    src = src[:match.start()] + wrapper + src[match.start():]
    # Re-find and replace only the first exact server initial call.
    pos = src.index(indent + "await upstream.send_json(", match.start() + len(wrapper))
    src = src[:pos] + src[pos:].replace(
        indent + "await upstream.send_json(",
        indent + "await _kitty_forward_initial_session(", 1)
    src = src.replace(CALLBACK_BASE,
        "_kitty_base_instructions = kitty_initial_instructions or "
        "((event.get('session') or {}).get('instructions') or '')", 1)
    ast.parse(src)
    return src

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    old = args.path.read_text(encoding="utf-8")
    new = patch(old)
    if args.apply and new != old:
        shutil.copy2(args.path, args.path.with_name(args.path.name + ".pre-candidate-baseline"))
        args.path.write_text(new, encoding="utf-8")
    print("KITTY_CANDIDATE_BASELINE_" + ("APPLIED" if args.apply else "VALIDATED"))
