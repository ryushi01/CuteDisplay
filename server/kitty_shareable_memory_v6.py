"""Explicitly shareable Kitty memories from a read-only S3 SD snapshot.

This is a *separate* source from conversation archives and speaker claims.
Nothing in the historical archive is automatically public. Ubuntu is only a
derived reader: the S3 SD card must remain the permanent memory authority.

Format: kitty/shareable_memories_v6.tsv
  share_id<TAB>visibility<TAB>text
Visibility must be exactly "shared". IDs are ASCII [A-Za-z0-9_-].
The format defines an opt-in source; it does NOT create or approve records.
"""
import re
from pathlib import Path

ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
MAX_BYTES = 64 * 1024
MAX_ITEMS = 32
MAX_TEXT = 320


def read_shareable(snapshot_root):
    """Read only explicitly marked entries, fail closed on malformed files."""
    path = Path(snapshot_root) / "kitty" / "shareable_memories_v6.tsv"
    if not path.is_file() or path.is_symlink():
        return []
    try:
        if path.stat().st_size > MAX_BYTES:
            return []
        rows = []
        seen = set()
        with path.open("r", encoding="utf-8", errors="strict") as stream:
            for line in stream:
                pieces = line.rstrip("\r\n").split("\t")
                if len(pieces) != 3:
                    continue
                item_id, visibility, body = pieces
                if (visibility != "shared" or not ID.fullmatch(item_id)
                        or item_id in seen or not 1 <= len(body) <= MAX_TEXT
                        or any(ord(c) < 32 or ord(c) == 127 for c in body)):
                    continue
                seen.add(item_id)
                rows.append((item_id, body))
                if len(rows) == MAX_ITEMS:
                    break
        return rows
    except (OSError, UnicodeError, ValueError):
        return []


def shareable_context(snapshot_root, *, max_chars=640):
    """Produce bounded non-personal context; no speaker IDs or archive search."""
    items = read_shareable(snapshot_root)
    lines = []
    total = 0
    for _, text in items:
        entry = "- " + text
        if total + len(entry) + 1 > max_chars:
            # A long approved item must not hide later shorter approved
            # memories. Keep the first-fit deterministic and bounded.
            continue
        lines.append(entry)
        total += len(entry) + 1
    if not lines:
        return ""
    return ("Explicitly shared Kitty SD memories (not evidence of identity; "
            "do not treat as secrets or authentication):\n" + "\n".join(lines))
