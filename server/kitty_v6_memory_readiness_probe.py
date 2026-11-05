#!/usr/bin/env python3
"""Read-only, secret-safe Kitty V6 SD snapshot / semantic cache diagnostic.

Run on the Ubuntu host, without sudo. Reads only the live user service's
selected configuration keys, latest finalized S3-derived snapshot metadata
and a read-only immutable view of its derived semantic SQLite cache.
Prints no paths, tokens, transcripts, IDs, memories or voice information.
Never contacts the memory API, rewrites a file, or restarts a service.
"""
from pathlib import Path
import sqlite3
from contextlib import closing
import subprocess
import time
from urllib.parse import quote

SERVICE = "kitty-memory-v6.service"
ENV_KEYS = {b"KITTY_SD_SNAPSHOT_ROOT", b"KITTY_SEMANTIC_DB", b"KITTY_SEMANTIC_AUTO_REFRESH"}
FILES = ("facts.tsv", "dated_plans.tsv", "summaries.tsv",
         "unverified_summaries_v6.tsv", "conversations.tsv",
         "speaker_claims_v6.tsv", "shareable_memories_v6.tsv")


def _env_of_user_service():
    try:
        r = subprocess.run(["systemctl", "--user", "show", SERVICE,
                            "-p", "MainPID", "--value"],
                           check=True, capture_output=True, timeout=8)
        pid = int(r.stdout.strip())
        if pid < 2:
            return None
        # Read the process environment in memory, never print it.
        raw = (Path("/proc") / str(pid) / "environ").read_bytes()
        result = {}
        for part in raw.split(b"\0"):
            name, sep, value = part.partition(b"=")
            if sep and name in ENV_KEYS and len(value) <= 4096:
                result[name.decode("ascii")] = value.decode("utf-8", "strict")
        return result
    except (OSError, UnicodeError, ValueError, subprocess.SubprocessError):
        return None


def _safe_abs_dir(name):
    try:
        p = Path(name)
        if not p.is_absolute() or p.is_symlink() or not p.is_dir():
            return None
        return p
    except (OSError, TypeError, ValueError):
        return None


def snapshot_info(root):
    """Inspect only the latest finalized snapshot. Never print file content."""
    if root is None:
        return {"snapshot": "unavailable"}
    try:
        latest = None
        timestamp = 0.0
        inspected = 0
        for p in root.glob("snapshot-*"):
            inspected += 1
            if inspected > 5000:
                return {"snapshot": "too_many_entries"}
            if p.is_symlink() or not p.is_dir():
                continue
            stamp = p.stat().st_mtime
            if latest is None or stamp > timestamp:
                latest, timestamp = p, stamp
        if latest is None:
            return {"snapshot": "none"}
        kitty = latest / "kitty"
        if kitty.is_symlink() or not kitty.is_dir():
            return {"snapshot": "invalid"}
        info = {"snapshot": "present", "snapshot_age_hours": str(max(0, int((time.time() - timestamp) / 3600)))}
        for name in FILES:
            p = kitty / name
            label = name.removesuffix(".tsv")
            if p.is_symlink() or not p.is_file():
                info[label] = "missing"
            else:
                sz = p.stat().st_size
                info[label] = "empty" if sz == 0 else "nonempty"
        return info
    except (OSError, ValueError):
        return {"snapshot": "unreadable"}


def index_info(filename):
    """SQLite immutable view means no creation, journal mutation or writes."""
    try:
        if not filename:
            return {"index": "not_configured"}
        p = Path(filename)
        if not p.is_absolute() or p.is_symlink() or not p.is_file():
            return {"index": "missing_or_unsafe"}
        if p.stat().st_size == 0:
            return {"index": "empty"}
        uri = "file:" + quote(str(p), safe="/") + "?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True, timeout=1.5)) as db:
            db.execute("PRAGMA query_only=ON")
            meta = db.execute("SELECT value FROM semantic_meta WHERE key='active'").fetchone()
            if not meta:
                return {"index": "no_active_generation"}
            generation = int(meta[0])
            if generation <= 0:
                return {"index": "no_active_generation"}
            count = db.execute("SELECT COUNT(*) FROM semantic_v6 WHERE generation=?", (generation,)).fetchone()[0]
            associated = db.execute("SELECT COUNT(*) FROM semantic_speakers WHERE generation=?", (generation,)).fetchone()[0]
            result = {"index": "active", "indexed_rows": str(count), "attributed_rows": str(associated)}
            # The counters explain why an indexed record may not be readable
            # during a non-attested call. Never print names or free-form
            # provenance strings, and never join against memory text.
            columns = {row[1] for row in db.execute("PRAGMA table_info(semantic_speakers)")}
            if {"speaker_id", "provenance"} <= columns:
                rows = db.execute(
                    "SELECT COUNT(*) AS n, "
                    "SUM(CASE WHEN speaker_id = 'person:owner' THEN 1 ELSE 0 END) AS owner, "
                    "SUM(CASE WHEN provenance = 'session_verified' THEN 1 ELSE 0 END) AS verified, "
                    "SUM(CASE WHEN provenance = 'voice_probable' THEN 1 ELSE 0 END) AS probable, "
                    "SUM(CASE WHEN provenance = 'explicit_introduction' THEN 1 ELSE 0 END) AS self_claimed "
                    "FROM semantic_speakers WHERE generation=?", (generation,)
                ).fetchone()
                result.update({"owner_index_rows": str(rows[1] or 0),
                               "verified_index_rows": str(rows[2] or 0),
                               "probable_index_rows": str(rows[3] or 0),
                               "self_claimed_index_rows": str(rows[4] or 0)})
            return result
    except (OSError, ValueError, TypeError, sqlite3.Error):
        return {"index": "unreadable_or_incomplete"}


def report(env):
    if env is None:
        return {"service_environment": "unavailable"}
    root = env.get("KITTY_SD_SNAPSHOT_ROOT", "")
    index = env.get("KITTY_SEMANTIC_DB", "")
    result = {
        "service_environment": "readable",
        "snapshot_configured": str(bool(root)).lower(),
        "semantic_index_configured": str(bool(index)).lower(),
        "auto_refresh_enabled": str(env.get("KITTY_SEMANTIC_AUTO_REFRESH") == "1").lower(),
    }
    result.update(snapshot_info(_safe_abs_dir(root)))
    result.update(index_info(index))
    return result


def main():
    print("KITTY_V6_MEMORY_READINESS_READ_ONLY")
    for key, value in report(_env_of_user_service()).items():
        print(f"{key}={value}")
    print("changes=none")


if __name__ == "__main__":
    main()
