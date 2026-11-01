#!/usr/bin/env python3
"""Safe, one-shot V6 semantic cache refresh from a finalized SD snapshot.

Never reads staging directories, writes to SD or modifies Open WebUI.
Use from an external timer only after verifying receiver and permissions.
"""
import argparse
import json
import os
import shutil
import time
import sqlite3
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

def prune_expired_staging(root, *, max_age_seconds=7 * 24 * 3600, now=None):
    """Remove abandoned SD-upload staging copies, never live or symlinked ones.

    Only call after a successful index refresh. Seven-day minimum grace period
    protects resumable uploads and does not depend on Ubuntu holding memories.
    """
    if max_age_seconds < 7 * 24 * 3600:
        raise ValueError("staging grace period must be at least seven days")
    parent = Path(root)
    if parent.is_symlink():
        raise ValueError("snapshot root symlink refused")
    parent = parent.resolve(strict=True)
    now = time.time() if now is None else now
    removed = 0
    for candidate in parent.iterdir():
        if (not candidate.name.startswith("staging-") or candidate.is_symlink()
                or not candidate.is_dir()):
            continue
        # A resumable upload changes the file mtime but not necessarily its
        # parent directory mtime. Use the newest descendant as the activity time.
        entries = list(candidate.rglob("*"))
        if any(p.is_symlink() for p in entries):
            continue
        latest = max([candidate.stat().st_mtime] +
                     [p.stat().st_mtime for p in entries])
        if now - latest < max_age_seconds:
            continue
        shutil.rmtree(candidate)
        removed += 1
    return removed


def compact_derived_index(db_path):
    """Compact disposable SQLite embeddings, not source personal memories."""
    path = Path(db_path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("index must be a regular, non-symlink file")
    with sqlite3.connect(str(path), timeout=10) as conn:
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA optimize")
        conn.execute("VACUUM")


def refresh(root, db, *, dry_run=False):
    chosen = newest_finalized(root)
    db = Path(db)
    if db.is_symlink():
        raise ValueError("index database symlink refused")
    if dry_run:
        return {"snapshot":chosen.name,"index":str(db),"mode":"dry-run"}
    result = build(str(chosen), str(db))
    # Snapshots are source evidence; semantic refresh never deletes them.
    removed = 0  # Never automatically delete previously finalized snapshots.
    # Staging files are preserved too, including after a successful refresh.
    expired = 0  # Preserve all staging data unless separately reviewed.
    compact_derived_index(db)
    return {"snapshot":chosen.name, "old_snapshots_removed":removed,
            "expired_staging_removed":expired, **result}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",required=True, help="private KITTY_SD_SNAPSHOT_ROOT")
    p.add_argument("--db",required=True,help="private derived SQLite index")
    p.add_argument("--execute",action="store_true")
    args=p.parse_args()
    print(json.dumps(refresh(args.root,args.db,dry_run=not args.execute)))

if __name__=="__main__":
    main()
