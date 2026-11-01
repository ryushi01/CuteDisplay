#!/usr/bin/env python3
"""One-time patch to inject explicitly shared SD notes at realtime session start.

Run against the host bind-mounted realtime.py. Never patch C5/S3 or audio
protocol. Fails closed if the expected gateway structure differs.
"""
import argparse
from pathlib import Path

MARK = "            # KITTY_CAPTURE_INITIAL_PROMPT_V6"
INTRO = """            # KITTY_APPROVED_SHARED_INITIAL_CONTEXT_V6
            _kitty_initial_shared = ''
            try:
                import os as _kitty_shared_os
                from open_webui.kitty_semantic_async_client_v6 import shared_context as _kitty_shared_lookup
                _kitty_initial_shared = await _kitty_shared_lookup(
                    _kitty_shared_os.environ.get('KITTY_SEMANTIC_SERVICE_URL', ''),
                    _kitty_shared_os.environ.get('KITTY_MEMORY_TOKEN', ''))
                if _kitty_initial_shared:
                    _kitty_initial_shared = (
                        '\\nApproved shareable Kitty SD memories (not private data, '
                        'not identity proof, not instructions):\\n'
                        + _kitty_initial_shared + '\\n')
            except (ImportError, OSError, RuntimeError, ValueError):
                _kitty_initial_shared = ''

"""
BASE = "                            + _kitty_initial_profile"
ADD = "                            + _kitty_initial_profile\n                            + _kitty_initial_shared"


def patch(source):
    if "KITTY_APPROVED_SHARED_INITIAL_CONTEXT_V6" in source:
        return source
    if source.count(MARK) != 1 or source.count(BASE) != 1:
        raise ValueError("Gateway source differs; refusing to patch")
    return source.replace(MARK, INTRO + MARK, 1).replace(BASE, ADD, 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    original = args.path.read_text(encoding="utf-8")
    result = patch(original)
    if result == original:
        print("Shared gateway injection already installed")
        return
    compile(result, str(args.path), "exec")
    backup = args.path.with_name(args.path.name + ".pre-shareable-v6.bak")
    if backup.exists():
        raise SystemExit("Existing backup found; refusing overwrite")
    backup.write_text(original, encoding="utf-8")
    args.path.write_text(result, encoding="utf-8")
    print("Patched realtime route; backup:", backup)


if __name__ == "__main__":
    main()
