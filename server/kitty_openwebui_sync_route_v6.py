#!/usr/bin/env python3
"""Version-checked opt-in Open WebUI Kitty snapshot HTTP routes.

Use only with an explicitly configured, trusted private backend. Not activated
by importing this module; a separate integration must call register(app).
"""
import hmac
import os
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse
import httpx

PREFIX = "/kitty-v6/sync"
ROUTES = {PREFIX + "/snapshot/chunk": "/snapshot/chunk",
          PREFIX + "/snapshot/finalize": "/snapshot/finalize"}
MAX_BODY = 16384

def register(app):
    enabled = os.getenv("KITTY_WEBUI_SYNC_ENABLED", "") == "1"
    if not enabled:
        return False
    device_token = os.environ.get("KITTY_WEBUI_SYNC_DEVICE_TOKEN", "")
    upstream_token = os.environ.get("KITTY_WEBUI_SYNC_UPSTREAM_TOKEN", "")
    upstream = os.environ.get("KITTY_WEBUI_SYNC_UPSTREAM_URL", "")
    ca_file = os.environ.get("KITTY_WEBUI_SYNC_CA_FILE", "")
    parts = urlsplit(upstream)
    if (len(device_token) < 32 or len(upstream_token) < 32
            or hmac.compare_digest(device_token, upstream_token)
            or parts.scheme != "https" or parts.hostname not in
            {"10.5.5.245", "kitty-v6-sync"} or parts.path not in {"", "/"}
            or parts.username or parts.password or parts.query or parts.fragment
            or not ca_file or not os.path.isfile(ca_file)):
        raise RuntimeError("Kitty sync security configuration invalid")

    async def relay(request: Request):
        raw_auth = request.headers.get("authorization", "")
        if not hmac.compare_digest(raw_auth, "Bearer " + device_token):
            return JSONResponse({"error":"unauthorized"}, status_code=401)
        length = request.headers.get("content-length", "")
        if not length.isdecimal() or not 2 <= int(length) <= MAX_BODY:
            return JSONResponse({"error":"invalid_length"}, status_code=413)
        if request.headers.get("content-type", "").split(";",1)[0].strip().lower() != "application/json":
            return JSONResponse({"error":"json_required"}, status_code=415)
        body = await request.body()
        if len(body) != int(length) or len(body) > MAX_BODY:
            return JSONResponse({"error":"invalid_length"}, status_code=413)
        path = ROUTES.get(request.url.path)
        if path is None:
            return JSONResponse({"error":"not_found"}, status_code=404)
        try:
            async with httpx.AsyncClient(verify=ca_file, timeout=5, trust_env=False, follow_redirects=False) as client:
                result = await client.post(upstream.rstrip("/") + path,
                    content=body, headers={
                       "Authorization": "Bearer " + upstream_token,
                       "Content-Type": "application/json"})
        except httpx.HTTPError:
            return JSONResponse({"error":"upstream_unavailable"}, status_code=502)
        if result.status_code not in (200,400,401,409,413,415,422,429,500,503):
            return JSONResponse({"error":"upstream_error"}, status_code=502)
        return JSONResponse(
            content=_safe_json(result),
            status_code=result.status_code,
            headers={"Cache-Control":"no-store"})

    # Exact paths only; do not shadow any existing Open WebUI router.
    for public in ROUTES:
        app.add_api_route(public, relay, methods=["POST"], include_in_schema=False)
    return True

def _safe_json(response):
    try:
        obj = response.json()
        return obj if isinstance(obj,dict) else {"error":"bad_upstream_response"}
    except ValueError:
        return {"error":"bad_upstream_response"}
