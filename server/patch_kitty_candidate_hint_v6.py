#!/usr/bin/env python3
"""Wire existing non-authorizing candidate callbacks into realtime observer.

No speaker authentication change, no private memory, no audio changes.
Requires existing candidate hint callbacks; refuses unknown gateway versions.
"""
import argparse
from pathlib import Path

OLD="""                    on_candidate=None)
                    # Candidate hint expires after 20 seconds"""
NEW="""                    on_candidate=kitty_candidate_hint,
                    on_candidate_clear=kitty_candidate_clear)
                    # Candidate hint expires after 20 seconds"""

def patch(source):
    if NEW in source:
        return source
    if source.count(OLD) != 1:
        raise ValueError("Expected candidate observer hook missing; no change")
    if ("async def kitty_candidate_hint(" not in source or
            "async def kitty_candidate_clear(" not in source or
            "KITTY_CANDIDATE_SESSION_CALLBACK_V6" not in source):
        raise ValueError("Candidate context implementation unavailable")
    updated=source.replace(OLD,NEW,1)
    compile(updated,"realtime.py","exec")
    return updated

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("path",type=Path)
    path=ap.parse_args().path
    original=path.read_text(encoding="utf-8")
    changed=patch(original)
    if changed==original:
        print("Candidate hint callback already wired")
        return
    backup=path.with_name(path.name+".before-candidate-hint-v6.bak")
    if backup.exists():
        raise SystemExit("Backup exists; refusing overwrite")
    backup.write_text(original,encoding="utf-8")
    path.write_text(changed,encoding="utf-8")
    print("Enabled non-authorizing candidate hint; backup:",backup)

if __name__=="__main__":
    main()
