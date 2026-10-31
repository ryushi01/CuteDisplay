"""Nonblocking gateway-side client for speaker-scoped Kitty V6 semantic recall.

Opt-in adapter for text and realtime orchestration. It does NOT persist memory,
authenticate a speaker, or run inside an I2S/WebSocket event handler. The
caller must provide a speaker ID attributed to the *current* turn.
"""
import asyncio
import json
import urllib.error
import urllib.request

MAX_QUERY = 300
MAX_CONTEXT = 1800
ALLOWED_TIMEOUT = 0.35


def _read_context(url, token, query, speaker_id, timeout):
    body = json.dumps({"query": query, "speaker_id": speaker_id},
                      ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url.rstrip("/") + "/semantic/context",
        data=body, method="POST",
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            return ""
        payload = response.read(4096)
    result = json.loads(payload)
    value = result.get("context", "") if isinstance(result, dict) else ""
    return value[:MAX_CONTEXT] if isinstance(value, str) else ""


async def semantic_context(url, token, query, speaker_id, *, timeout=ALLOWED_TIMEOUT,
                           request_fn=_read_context):
    """Obtain disposable recall without blocking an async voice event loop.

    Unknown speaker identity, lack of configuration or timeout means no memory.
    Caller must never treat a claimed name as authenticated owner identity.
    """
    if (not isinstance(speaker_id, str) or speaker_id in ("", "unknown")
            or not speaker_id.strip() or len(speaker_id) > 128
            or any(ord(char) < 32 for char in speaker_id)):
        return ""
    if not isinstance(query, str) or not query.strip():
        return ""
    if not isinstance(url, str) or not url.startswith("http://127.0.0.1:"):
        # Only loopback memory service; no remote forwarding of private queries.
        return ""
    if not isinstance(token, str) or not token:
        return ""
    try:
        limit = min(max(float(timeout), 0.05), ALLOWED_TIMEOUT)
        return await asyncio.wait_for(
            asyncio.to_thread(request_fn, url, token, query[:MAX_QUERY],
                              speaker_id, limit), timeout=limit)
    except (TimeoutError, OSError, ValueError, TypeError, KeyError,
            json.JSONDecodeError, urllib.error.URLError):
        return ""
