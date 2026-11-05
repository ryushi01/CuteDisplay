"""Nonblocking gateway-side client for speaker-scoped Kitty V6 semantic recall.

Opt-in adapter for text and realtime orchestration. It does NOT persist memory,
authenticate a speaker, or run inside an I2S/WebSocket event handler. The
caller must provide a speaker ID attributed to the *current* turn.
"""
import asyncio
import http.client
import socket
import json
import posixpath
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit

MAX_QUERY = 300
MAX_CONTEXT = 1800
ALLOWED_TIMEOUT = 0.35
SPEAKER_ID = re.compile(r"person:[A-Za-z0-9_-]{1,48}\Z")


def _local_memory_endpoint(url):
    """Validate parsed localhost/Unix-socket destination, not a string prefix."""
    if not isinstance(url, str) or len(url) > 512:
        return False
    try:
        parsed = urlsplit(url)
        if parsed.scheme == "http":
            return (parsed.hostname == "127.0.0.1"
                    and parsed.port is not None
                    and 0 < parsed.port <= 65535
                    and not parsed.username and not parsed.password
                    and parsed.path in ("", "/")
                    and not parsed.query and not parsed.fragment)
        if parsed.scheme == "unix":
            path = parsed.path
            return (parsed.netloc == "" and not parsed.query
                    and not parsed.fragment
                    and path.startswith("/run/kitty-semantic/")
                    and path == posixpath.normpath(path)
                    and not any(c in path for c in ("%", chr(0), chr(92))))
    except ValueError:
        return False
    return False


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward a private API token or owner grant via HTTP redirects."""
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class _UnixHTTPConnection(http.client.HTTPConnection):
    """HTTP/1.1 over a private mounted Unix-domain socket."""
    def __init__(self, path, timeout):
        super().__init__("localhost", timeout=timeout)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


def _read_context(url, token, query, speaker_id, timeout,
                  session_id=None, owner_grant=None):
    payload={"query":query,"speaker_id":speaker_id}
    if session_id is not None and owner_grant is not None:
        payload["session_id"]=session_id
        payload["owner_grant"]=owner_grant
    body = json.dumps(payload,ensure_ascii=False).encode("utf-8")
    if url.startswith("unix:///run/kitty-semantic/"):
        path = url[len("unix://"):]
        conn = _UnixHTTPConnection(path, timeout)
        try:
            conn.request(
                "POST", "/semantic/context", body=body,
                headers={
                    "Authorization": "Bearer " + token,
                    "Content-Type": "application/json",
                },
            )
            response = conn.getresponse()
            if response.status != 200:
                return ""
            result = json.loads(response.read(4096))
            value = result.get("context", "") if isinstance(result, dict) else ""
            return value[:MAX_CONTEXT] if isinstance(value, str) else ""
        finally:
            conn.close()

    request = urllib.request.Request(
        url.rstrip("/") + "/semantic/context",
        data=body, method="POST",
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json"})
    with urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect()).open(request, timeout=timeout) as response:
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
    if not isinstance(speaker_id, str) or not SPEAKER_ID.fullmatch(speaker_id):
        return ""
    if not isinstance(query, str) or not query.strip():
        return ""
    if not _local_memory_endpoint(url):
        # Never send private queries to a host hidden in URL credentials.
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

async def owner_semantic_context(url, token, query, session_id, owner_grant,
                                 *, timeout=ALLOWED_TIMEOUT,
                                 request_fn=_read_context):
    """One-shot owner-only lookup, never automatically called from voice IDs.

    The memory service verifies a cryptographic enrolled-key owner grant for
    this particular session. An S3 API token or spoken name is insufficient.
    No Mac inference or realtime audio worker is involved.
    """
    if (not _local_memory_endpoint(url) or not isinstance(token,str) or not token
            or not isinstance(query,str) or not query.strip()
            or not isinstance(session_id,str) or not 8<=len(session_id)<=100
            or not isinstance(owner_grant,str)
            or not 1<=len(owner_grant)<=1024):
        return ""
    try:
        limit=min(max(float(timeout),0.05),ALLOWED_TIMEOUT)
        return await asyncio.wait_for(
            asyncio.to_thread(request_fn,url,token,query[:MAX_QUERY],
                              "person:owner",limit,session_id,owner_grant),
            timeout=limit)
    except (TimeoutError,OSError,ValueError,TypeError,KeyError,
            json.JSONDecodeError,urllib.error.URLError):
        return ""


def _read_shared_context(url, token, timeout, query=None):
    body=(json.dumps({"query":query},ensure_ascii=False).encode("utf-8")
          if query is not None else b"{}")
    headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"}
    if url.startswith("unix:///run/kitty-semantic/"):
        conn=_UnixHTTPConnection(url[len("unix://"):],timeout)
        try:
            conn.request("POST","/shared/context",body=body,headers=headers)
            response=conn.getresponse()
            if response.status!=200:
                return ""
            obj=json.loads(response.read(2048))
        finally:
            conn.close()
    else:
        request=urllib.request.Request(url.rstrip("/")+"/shared/context",
                                      data=body,method="POST",headers=headers)
        with urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect()).open(request,timeout=timeout) as response:
            if response.status!=200:
                return ""
            obj=json.loads(response.read(2048))
    value=obj.get("context","") if isinstance(obj,dict) else ""
    return value[:640] if isinstance(value,str) else ""


async def shared_context(url, token, *, timeout=0.35,
                         request_fn=_read_shared_context):
    """Read only explicitly approved public snapshot notes; fail closed."""
    if not _local_memory_endpoint(url) or not isinstance(token,str) or not token:
        return ""
    try:
        limit=min(max(float(timeout),0.05),ALLOWED_TIMEOUT)
        return await asyncio.wait_for(
            asyncio.to_thread(request_fn,url,token,limit),timeout=limit)
    except (TimeoutError,OSError,ValueError,TypeError,KeyError,
            json.JSONDecodeError,urllib.error.URLError):
        return ""


async def shared_context_for_query(url, token, query, *, timeout=0.35,
                                   request_fn=_read_shared_context):
    """Best-effort approved-public recall only; never private identity lookup.

    This is an optional per-turn helper and must be called from a separately
    scheduled task, never directly on the realtime WebSocket/audio hot path.
    No query data or results are stored by this client.
    """
    if (not isinstance(query, str) or not query.strip()
            or len(query) > 300 or not _local_memory_endpoint(url)
            or not isinstance(token, str) or not token):
        return ""
    try:
        limit = min(max(float(timeout), 0.05), ALLOWED_TIMEOUT)
        value = await asyncio.wait_for(
            asyncio.to_thread(request_fn, url, token, limit, query),
            timeout=limit)
        return value[:640] if isinstance(value, str) else ""
    except (TimeoutError, OSError, ValueError, TypeError, KeyError,
            json.JSONDecodeError, urllib.error.URLError):
        return ""
