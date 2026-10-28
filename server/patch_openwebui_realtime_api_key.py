#!/usr/bin/env python3
"""Version-guarded source patch for direct, unattended Open WebUI realtime calls.

This patches one file of a CHECKED-OUT Open WebUI source tree, NOT a running
server or Docker container. It does not start services. Only use on a pinned
compatible Open WebUI commit, inspect the diff, build a custom image and run
authorization/revocation tests before deploying. --check never writes files.

Effect: /api/v1/audio/realtime accepts existing sk- API keys using the same
get_current_user_by_api_key access checks used for REST (including feature
permission and endpoint restrictions). Non-key JWT behavior remains unchanged.
Per-minute revalidation of API keys allows revocation to end active calls.

There is NO external device gateway or additional URL.
"""
import argparse
from pathlib import Path
import shutil
import sys

TARGET = "backend/open_webui/routers/audio/realtime.py"
MARKER = "# CuteDisplay direct-device realtime API-key support (opt-in server patch)"
OLD = {
    "fastapi": "from fastapi import APIRouter, WebSocket, WebSocketDisconnect",
    "auth": "from open_webui.utils.auth import get_verified_user_by_token",
    "router": "router = APIRouter()\nlog = logging.getLogger(__name__)",
    "initial": "user = await get_verified_user_by_token(token, redis)",
    "renew": "current = await get_verified_user_by_token(token, redis)",
}
NEW = {
    "fastapi": "from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect",
    "auth": "from open_webui.utils.auth import get_current_user_by_api_key, get_verified_user_by_token",
    "router": '''router = APIRouter()
log = logging.getLogger(__name__)

''' + MARKER + '''
async def _cutedisplay_verified_realtime_user(ws: WebSocket, token: str, redis=None):
    """Authenticate either JWT session or user-scoped WebUI API key.

    The API-key helper reads ws.scope["path"] just like it reads an HTTP
    Request's scope and honors the administrator's endpoint allowlist.
    This must be re-run by the websocket authorization heartbeat too.
    """
    if token.startswith("sk-"):
        try:
            user = await get_current_user_by_api_key(ws, token)
        except HTTPException:
            return None
        return user if user and user.role in {"user", "admin"} else None
    return await get_verified_user_by_token(token, redis)
''',
    "initial": "user = await _cutedisplay_verified_realtime_user(ws, token, redis)",
    "renew": "current = await _cutedisplay_verified_realtime_user(ws, token, redis)",
}


def patch(source):
    if MARKER in source:
        raise ValueError("Already patched; verify your deployed server instead")
    for name, old in OLD.items():
        count = source.count(old)
        if count != 1:
            raise ValueError(f"Unsupported Open WebUI version: expected exactly one {name} anchor, found {count}")
    result = source
    for name in ("fastapi", "auth", "router", "initial", "renew"):
        result = result.replace(OLD[name], NEW[name], 1)
    compile(result, TARGET, "exec")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, help="Path to a pinned Open WebUI SOURCE checkout")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="Validate anchors and show patch intent; no writes")
    group.add_argument("--apply", action="store_true", help="Make backup and patch source file in-place")
    args = parser.parse_args()
    root = Path(args.source_root).expanduser().resolve()
    target = root / TARGET
    if not target.is_file():
        parser.error(f"Open WebUI source file not found: {target}")
    original = target.read_text()
    try:
        updated = patch(original)
    except (SyntaxError, ValueError) as exc:
        parser.error(str(exc))
    if args.check:
        print("PASS: source compatible with scoped API-key realtime patch (no changes made)")
        print("Direct device endpoint remains: wss://YOUR-WEBUI-HOST/api/v1/audio/realtime")
        return 0
    backup = target.with_suffix(".py.cutedisplay-original")
    if backup.exists():
        parser.error(f"Refusing to overwrite source backup: {backup}")
    shutil.copy2(target, backup)
    target.write_text(updated)
    print("PATCHED Open WebUI source:", target)
    print("BACKUP of pristine source:", backup)
    print("No running server was modified. Inspect git diff, rebuild and run permissions/revocation tests.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
