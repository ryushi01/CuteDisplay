#!/usr/bin/env python3
"""Safe, one-shot V6 semantic cache refresh from a finalized SD snapshot.

Never reads staging directories, writes to SD or modifies Open WebUI.
Use from an external timer only after verifying receiver and permissions.
"""
import argparse
import json
import os
import shutil
from pathlib import Path
from kitty_sd_semantic_index import build

def newest_finalized(root):
    root = Path(root)
    if root.is_symlink():
        raise ValueError("snapshot root symlink refused")
    root = root.resolve(strict=True)
    candidates = []
    for item in root.iterdir():
        if not item.name.startswith("snapshot-") or item.is_symlink() or not item.is_dir():
            continue
        if (item / "kitty").is_dir() and not (item / "kitty").is_symlink():
            candidates.append(item)
    if not candidates:
        raise ValueError("no finalized SD snapshots")
    return max(candidates, key=lambda p:(p.stat().st_mtime_ns,p.name))

def prune_superseded(root, retain):
    """Keep one finalized recovery snapshot, never touch active staging uploads."""
    parent = Path(root).resolve(strict=True)
    removed = 0
    for candidate in parent.iterdir():
        if (candidate == retain or not candidate.name.startswith("snapshot-")
                or candidate.is_symlink() or not candidate.is_dir()
                or not (candidate / "kitty").is_dir()):
            continue
        # Reject directory links inside finalized copies.
        if any(p.is_symlink() for p in candidate.rglob("*")):
            continue
        shutil.rmtree(candidate)
        removed += 1
    return removed

def refresh(root, db, *, dry_run=False):
    chosen = newest_finalized(root)
    db = Path(db)
    if db.is_symlink():
        raise ValueError("index database symlink refused")
    if dry_run:
        return {"snapshot":chosen.name,"index":str(db),"mode":"dry-run"}
    result = build(str(chosen), str(db))
    # Only prune after a complete successful semantic refresh. SD remains
    # authoritative; keep the newest verified copy as a bounded recovery cache.
    removed = prune_superseded(root, chosen)
    return {"snapshot":chosen.name, "old_snapshots_removed":removed, **result}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",required=True, help="private KITTY_SD_SNAPSHOT_ROOT")
    p.add_argument("--db",required=True,help="private derived SQLite index")
    p.add_argument("--execute",action="store_true")
    args=p.parse_args()
    print(json.dumps(refresh(args.root,args.db,dry_run=not args.execute)))

if __name__=="__main__":
    main()
