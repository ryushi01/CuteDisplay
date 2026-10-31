#!/usr/bin/env python3
"""Conservative retention of finalized Kitty SD-export copies.

Dry run by default. Does not touch staging uploads, voice enrollments,
the live/semantic SQLite databases, deployment files, or arbitrary backups.
Use only after confirming the actual private snapshot root and a restorable SD.
"""
import argparse
from pathlib import Path
import shutil

def candidates(root: Path, keep: int):
    root = root.resolve(strict=True)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("invalid snapshot root")
    finalized = []
    for path in root.iterdir():
        if not path.name.startswith("snapshot-") or path.is_symlink() or not path.is_dir():
            continue
        kitty = path / "kitty"
        if kitty.is_symlink() or not kitty.is_dir():
            continue
        # Never recurse into an unexpected symlink.
        if any(p.is_symlink() for p in path.rglob("*")):
            continue
        finalized.append(path)
    finalized.sort(key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
    return finalized[keep:]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, help="Existing private snapshot directory")
    parser.add_argument("--keep", type=int, default=10)
    parser.add_argument("--apply", action="store_true", help="Explicitly delete eligible old finalized copies")
    args = parser.parse_args()
    if args.keep < 3:
        parser.error("retain at least 3 finalized copies")
    root = Path(args.root).expanduser()
    for path in candidates(root, args.keep):
        print(("DELETE " if args.apply else "WOULD_DELETE ") + str(path))
        if args.apply:
            shutil.rmtree(path)
    print("No staging directories, SQLite databases, enrollment profiles, or backups selected.")

if __name__ == "__main__":
    main()
