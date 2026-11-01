#!/usr/bin/env python3
"""Bounded candidate readiness before realtime response.create.

Wait for the existing speaker-recognition task (not audio forwarding).
Do not enable private recall or weaken speaker checks.
"""
import argparse
from pathlib import Path

ANCHOR="                # KITTY_XVECTOR_CONVERSATION_HINT_V6"
INSERT="""                # KITTY_CANDIDATE_RESPONSE_WAIT_V6
                # The CPU recognizer may finish just after a response is
                # requested. Give the current matching turn a bounded chance,
                # without cancelling its task on timeout.
                _kitty_wait_items = command if isinstance(command, list) else [command]
                if (kitty_speaker_observer is not None and any(
                        isinstance(_item, dict) and _item.get('type') == 'response.create'
                        for _item in _kitty_wait_items)):
                    _kitty_recognition_task = getattr(
                        kitty_speaker_observer.session, '_task', None)
                    if (_kitty_recognition_task is not None and
                            not _kitty_recognition_task.done()):
                        try:
                            await asyncio.wait_for(
                                asyncio.shield(_kitty_recognition_task),
                                timeout=1.2)
                        except (asyncio.TimeoutError, asyncio.CancelledError,
                                OSError, ValueError):
                            pass
                    _kitty_candidate = kitty_speaker_observer.candidate_hint
                    print('[KITTY_CANDIDATE_RESPONSE] hint_available=%s' %
                          bool(_kitty_candidate and _kitty_candidate[1] == 'person:shana'),
                          flush=True)
"""

def patch(src):
    if "KITTY_CANDIDATE_RESPONSE_WAIT_V6" in src:
        return src
    if src.count(ANCHOR)!=1 or "command = protocol.command(event)" not in src:
        raise ValueError("Unexpected gateway response path; not patched")
    out=src.replace(ANCHOR,INSERT+ANCHOR,1)
    compile(out,"realtime.py","exec")
    return out

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("route",type=Path)
    path=parser.parse_args().route
    old=path.read_text(encoding="utf-8")
    new=patch(old)
    if new==old:
        print("Candidate response wait already installed")
        return
    backup=path.with_name(path.name+".before-candidate-wait-v6.bak")
    if backup.exists():
        raise SystemExit("Backup already exists; refusing overwrite")
    backup.write_text(old,encoding="utf-8")
    path.write_text(new,encoding="utf-8")
    print("Installed bounded candidate response wait; backup:",backup)

if __name__=="__main__":
    main()
