#!/usr/bin/env python3
"""Read-only attribution audit for a finalized Kitty snapshot and SQLite index.

Only counts and source provenance. Never prints conversations, facts, tokens,
speaker embeddings, or private memory text. Makes no changes.
"""
import argparse
import collections
import json
import sqlite3
from pathlib import Path

def audit(root, dbpath):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("snapshot directory invalid")
    kitty = root / "kitty"
    if kitty.is_symlink() or not kitty.is_dir():
        raise ValueError("kitty directory invalid")
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from kitty_semantic_attribution_v6 import iter_archive_with_speakers
    rows = list(iter_archive_with_speakers(root))
    archives = collections.Counter((r["speaker_id"],r["provenance"]) for r in rows)
    source = kitty/"turn_sources.tsv"
    sidecar_lines = 0
    if source.is_file() and not source.is_symlink():
        with source.open("r", encoding="utf-8", errors="replace") as f:
            sidecar_lines = sum(1 for _ in f)
    p = Path(dbpath)
    if p.is_symlink() or not p.is_file():
        raise ValueError("index missing or symlink")
    with sqlite3.connect("file:"+str(p.resolve())+"?mode=ro",uri=True) as db:
        active = db.execute("SELECT value FROM semantic_meta WHERE key='active'").fetchone()
        generation = int(active[0]) if active else None
        groups = db.execute(
            "SELECT speaker_id,provenance,COUNT(*) FROM semantic_speakers "
            "WHERE generation=? GROUP BY speaker_id,provenance",
            (generation,)).fetchall()
        totals = db.execute(
            "SELECT COUNT(*) FROM semantic_v6 WHERE generation=?", (generation,)
        ).fetchone()[0]
    return {
        "snapshot":root.name,
        "conversation_rows":len(rows),
        "turn_sources_rows":sidecar_lines,
        "conversation_attribution_counts":[
            {"speaker_id":speaker,"provenance":prov,"count":count}
            for (speaker,prov),count in sorted(archives.items())],
        "index_generation":generation,
        "indexed_rows":totals,
        "indexed_speaker_counts":[
            {"speaker_id":speaker,"provenance":prov,"count":count}
            for speaker,prov,count in groups],
        "note":"Unknown rows are not automatically assigned to any person.",
    }

if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--snapshot",required=True)
    parser.add_argument("--index",required=True)
    args=parser.parse_args()
    print(json.dumps(audit(args.snapshot,args.index),indent=2))
