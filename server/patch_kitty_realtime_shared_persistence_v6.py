#!/usr/bin/env python3
"""Preserve explicitly approved SD context across realtime session and response updates.

Patches only the mounted gateway source, never firmware or audio handling.
Does not change or authorize speaker-scoped private memory.
"""
import argparse
from pathlib import Path

SESSION_ANCHOR = "                # Audio forwarding stays unchanged; observer failures are isolated."
RESPONSE_ANCHOR = "                # KITTY_XVECTOR_CONVERSATION_HINT_V6"
SESSION_CODE = """                # KITTY_SHARED_CONTEXT_PERSIST_SESSION_V6
                # Client session.update may replace earlier instructions. Carry
                # forward only the explicitly approved shared SD context.
                if (_kitty_initial_shared and isinstance(event, dict)
                        and event.get('type') == 'session.update'):
                    _kitty_shared_session = event.get('session')
                    if isinstance(_kitty_shared_session, dict):
                        _kitty_old = _kitty_shared_session.get('instructions')
                        if isinstance(_kitty_old, str) and _kitty_initial_shared not in _kitty_old:
                            event = dict(event)
                            _kitty_shared_session = dict(_kitty_shared_session)
                            _kitty_shared_session['instructions'] = _kitty_old + _kitty_initial_shared
                            event['session'] = _kitty_shared_session
                            raw = JSONCodec.dumps(event)
"""
RESPONSE_CODE = """                # KITTY_SHARED_CONTEXT_PERSIST_RESPONSE_V6
                # A response.create may override session instructions. Append
                # only approved shared context, never speaker-scoped recall.
                if _kitty_initial_shared:
                    _kitty_shared_commands = command if isinstance(command, list) else [command]
                    for _kitty_shared_command in _kitty_shared_commands:
                        if (isinstance(_kitty_shared_command, dict)
                                and _kitty_shared_command.get('type') == 'response.create'
                                and isinstance(_kitty_shared_command.get('response'), dict)):
                            _kitty_response = _kitty_shared_command['response']
                            _kitty_instruction = _kitty_response.get('instructions')
                            if isinstance(_kitty_instruction, str) and _kitty_initial_shared not in _kitty_instruction:
                                _kitty_response['instructions'] = _kitty_instruction + _kitty_initial_shared
"""


def patch(src):
    if ("KITTY_SHARED_CONTEXT_PERSIST_SESSION_V6" in src and
            "KITTY_SHARED_CONTEXT_PERSIST_RESPONSE_V6" in src):
        return src
    if "KITTY_APPROVED_SHARED_INITIAL_CONTEXT_V6" not in src:
        raise ValueError("Initial shared-memory integration missing")
    if ("KITTY_SHARED_CONTEXT_PERSIST_SESSION_V6" in src or
            "KITTY_SHARED_CONTEXT_PERSIST_RESPONSE_V6" in src):
        raise ValueError("Partial patch present; refusing")
    if src.count(SESSION_ANCHOR) != 1 or src.count(RESPONSE_ANCHOR) != 1:
        raise ValueError("Unexpected gateway version; refusing")
    src = src.replace(SESSION_ANCHOR, SESSION_CODE + SESSION_ANCHOR, 1)
    src = src.replace(RESPONSE_ANCHOR, RESPONSE_CODE + RESPONSE_ANCHOR, 1)
    compile(src, "realtime.py", "exec")
    return src


def main():
    arg = argparse.ArgumentParser()
    arg.add_argument("path", type=Path)
    p = arg.parse_args().path
    old = p.read_text(encoding="utf-8")
    new = patch(old)
    if new == old:
        print("Already installed")
        return
    bak = p.with_name(p.name + ".pre-shareable-persist-v6.bak")
    if bak.exists():
        raise SystemExit("Backup exists; refusing to overwrite")
    bak.write_text(old, encoding="utf-8")
    p.write_text(new, encoding="utf-8")
    print("Patched shared context persistence; backup:", bak)


if __name__ == "__main__":
    main()
