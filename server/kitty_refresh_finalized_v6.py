#!/usr/bin/env python3
"""Safe, one-shot V6 semantic cache refresh from a finalized SD snapshot.

Never reads staging directories, writes to SD or modifies Open WebUI.
Use from an external timer only after verifying receiver and permissions.
"""
import argparse
import json
import os
from pathlib import Path
from kitty_sd_semantic_index import build

def newest_finalized(root):
    root = Path(root).resolve(strict=True)
    if root.is_symlink():
        raise ValueError("snapshot root symlink refused")
    candidates = []
    for item in root.iterdir():
        if not item.name.startswith("snapshot-") or item.is_symlink() or not item.is_dir():
            continue
        if (item / "kitty").is_dir() and not (item / "kitty").is_symlink():
            candidates.append(item)
    if not candidates:
        raise ValueError("no finalized SD snapshots")
    return max(candidates, key=lambda p:(p.stat().st_mtime_ns,p.name))

def refresh(root, db, *, dry_run=False):
    chosen = newest_finalized(root)
    db = Path(db)
    if db.is_symlink():
        raise ValueError("index database symlink refused")
    if dry_run:
        return {"snapshot":chosen.name,"index":str(db),"mode":"dry-run"}
    result = build(str(chosen), str(db))
    return {"snapshot":chosen.name, **result}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",required=True, help="private KITTY_SD_SNAPSHOT_ROOT")
    p.add_argument("--db",required=True,help="private derived SQLite index")
    p.add_argument("--execute",action="store_true")
    args=p.parse_args()
    print(json.dumps(refresh(args.root,args.db,dry_run=not args.execute)))

if __name__=="__main__":
    main()
