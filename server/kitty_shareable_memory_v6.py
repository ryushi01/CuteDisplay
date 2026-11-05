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


# Query scoring is intentionally local, lexical and dependency-free. It never
# searches conversation archives, summaries, speaker claims or owner facts.
# No query keeps the previously tested approved-shared startup behavior.
_WORDS = re.compile(r"[a-z0-9]{3,}|[\u3040-\u30ff\u3400-\u9fff]{2,}", re.I)
_STOP = frozenset({
    "about", "after", "again", "also", "and", "are", "asked", "been",
    "before", "can", "could", "did", "does", "for", "from", "have",
    "how", "into", "its", "know", "like", "more", "much", "name",
    "our", "please", "recall", "remember", "remind", "said", "say",
    "she", "should", "some", "tell", "that", "the", "their",
    "them", "there", "these", "they", "this", "those", "was",
    "were", "what", "when", "where", "which", "who", "why",
    "will", "with", "would", "you", "your",
})


def _rank_approved(items, query):
    """Return only approved notes matching meaningful query terms.

    Ranking cannot authenticate a speaker or promote archived claims. When
    the query is too vague/no match, return no queried memories rather than
    silently exposing unrelated approved notes.
    """
    if not isinstance(query, str) or not 1 <= len(query) <= 300:
        return []
    terms = set(_WORDS.findall(query.casefold())) - _STOP
    if not terms:
        return []
    scored = []
    for order, (ident, body) in enumerate(items):
        haystack = body.casefold()
        words = set(_WORDS.findall(haystack))
        score = sum((1 + min(len(term), 12) / 12) for term in terms
                    if term in words or (
                        len(term) >= 3 and term in haystack))
        if score:
            scored.append((-score, order, ident, body))
    scored.sort()
    return [(ident, body) for _, _, ident, body in scored]


def shareable_context(snapshot_root, *, max_chars=640, query=None):
    """Read bounded *approved public* SD notes; optionally rank by question.

    The original query-less behavior is preserved for realtime session start.
    A question never expands the source allowlist or authorizes private data.
    """
    items = read_shareable(snapshot_root)
    if query is not None:
        items = _rank_approved(items, query)
    lines = []
    total = 0
    for _, text in items:
        entry = "- " + text
        if total + len(entry) + 1 > max_chars:
            # An oversized approved entry never hides a later smaller one.
            continue
        lines.append(entry)
        total += len(entry) + 1
    if not lines:
        return ""
    return ("Explicitly shared Kitty SD memories (not evidence of identity; "
            "do not treat as secrets or authentication):\n" + "\n".join(lines))
