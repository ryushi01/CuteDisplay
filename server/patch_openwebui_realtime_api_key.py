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


# A separate capability, opt-in only for S3 callers. The server source may
# already have the original secure API-key patch deployed, so both base states
# are supported. We never replace, loosen or bypass existing authorization.
EXPRESSION_MARKER = "# CuteDisplay realtime facial expressions (opt-in v1)"
EXPRESSION_MOODS = ("neutral", "happy", "sad", "angry", "hungry", "sleepy", "excited", "shy", "surprised", "confused", "laughing", "worried", "playful", "love", "bored", "proud")
EXPRESSION_TOOL = """
KITTY_EXPRESSIONS = ("neutral", "happy", "sad", "angry", "hungry", "sleepy", "excited", "shy", "surprised", "confused", "laughing", "worried", "playful", "love", "bored", "proud")
KITTY_EXPRESSION_TOOL = {
    'type': 'function',
    'name': 'set_expression',
    'description': (
        'Change your Kitty companion face to match the emotional tone of your '
        'speech. Select from neutral, happy, sad, angry, hungry, sleepy, '
        'excited, shy, surprised, confused, laughing, worried, playful, '
        'love, bored, and proud. React naturally to jokes, surprises, '
        'affection, uncertainty, teasing and the tone of your own words. '
        'Change expression when the emotional beat changes, possibly more '
        'than once within a long response, but do not spam tool calls. '
        'Never narrate an expression command; continue normal speech.'
    ),
    'parameters': {
        'type': 'object',
        'properties': {
            'emotion': {'type': 'string', 'enum': list(KITTY_EXPRESSIONS)}
        },
        'required': ['emotion'],
        'additionalProperties': False,
    },
}
KITTY_EXPRESSION_INSTRUCTIONS = (
    "\\nYou are Kitty-chan, a lively playful animated companion with expressive eyes. "
    "React promptly to the user's feelings and the changing emotional tone. "
    "Use set_expression with one of: neutral, happy, sad, angry, hungry, sleepy, "
    "excited, shy, surprised, confused, laughing, worried, playful, love, bored, proud. "
    "Choose surprised for unexpected news, confused for uncertainty, laughing for jokes, "
    "worried for concern, playful for teasing, love for affection, bored for boredom, "
    "proud for success. Match the scene without making assumptions about the user. "
    "Set the expression early, before the relevant speech when possible; for a long "
    "response, change it again if the emotional tone actually changes. "
    "Do not announce the expression or interrupt the content of your answer. "
    "Speak naturally in the user's language and retain your existing personality."
)
""" + EXPRESSION_MARKER + "\\n"

EXPRESSION_ANCHORS = {
    "call_protocol": "def __init__(self, gestures=()):",
    "call_protocol_state": "self.gesture_names = {gesture.name for gesture in gestures}",
    "observer": "if item.get('name') == 'play_animation':",
    "auth": "token = auth['token']",
    "protocol": "protocol = CallProtocol(\n            model_info.meta.voice_avatar.gestures if model_info and model_info.meta.voice_avatar else ()\n        )",
    "instructions": "+ (AVATAR_CALL_INSTRUCTIONS if protocol.animation_tools else '')",
    "tools": "'tools': [CHAT_TOOL, *protocol.animation_tools],",
}

def patch_expressions(source):
    if EXPRESSION_MARKER in source:
        if '"surprised", "confused", "laughing"' in source:
            return source
        # Upgrade an already-installed v1 expression tool in place.
        # The original auth/observer plumbing stays untouched.
        begin = source.find("KITTY_EXPRESSIONS = (")
        end = source.find(EXPRESSION_MARKER, begin)
        if begin < 0 or end < 0:
            raise ValueError("Previous expression block not found")
        end += len(EXPRESSION_MARKER)
        fresh = EXPRESSION_TOOL.rstrip()
        return source[:begin] + fresh + source[end:]
    for name, anchor in EXPRESSION_ANCHORS.items():
        if source.count(anchor) != 1:
            raise ValueError(
                f"Unsupported Realtime version: expected one {name} anchor, "
                f"found {source.count(anchor)}"
            )
    result = source.replace("class CallProtocol:", EXPRESSION_TOOL + "\nclass CallProtocol:", 1)
    result = result.replace(
        "def __init__(self, gestures=()):",
        "def __init__(self, gestures=(), kitty_expressions=False):",
        1,
    )
    result = result.replace(
        "self.gesture_names = {gesture.name for gesture in gestures}",
        "self.kitty_expressions = bool(kitty_expressions)\n        "
        "self.gesture_names = {gesture.name for gesture in gestures}",
        1,
    )
    result = result.replace(
        "if item.get('name') == 'play_animation':",
        """if item.get('name') == 'set_expression' and self.kitty_expressions:
                    # Reuse the existing validated animation result/continuation
                    # protocol; the ESP32 already supports it. Keep call IDs
                    # scoped to the authenticated WebSocket session.
                    if item['call_id'] in self.animation_seen:
                        return
                    if len(self.animation_seen) >= 4096:
                        raise ValueError('Call limit reached. Start a new call.')
                    try:
                        args = JSONCodec.loads(item.get('arguments', ''))
                        valid = (isinstance(args, dict) and set(args) == {'emotion'}
                                 and type(args['emotion']) is str
                                 and args['emotion'] in KITTY_EXPRESSIONS)
                    except (ValueError, TypeError, KeyError):
                        valid = False
                    event['animation_valid'] = bool(valid)
                    self.animation_seen.add(item['call_id'])
                    self.animation_calls[item['call_id']] = (event['response_id'], bool(valid))
                    self.animation_responses.add(event['response_id'])
                    return
                if item.get('name') == 'play_animation':""",
        1,
    )
    result = result.replace(
        "token = auth['token']",
        """# Optional capability is set only by the authenticated device. Unknown
        # clients (browser and older S3 firmware) keep unchanged behavior.
        kitty_expressions = auth.get('kitty_expressions') is True
        token = auth['token']""",
        1,
    )
    result = result.replace(
        EXPRESSION_ANCHORS["protocol"],
        "protocol = CallProtocol(\n"
        "            model_info.meta.voice_avatar.gestures if model_info and model_info.meta.voice_avatar else (),\n"
        "            kitty_expressions=kitty_expressions,\n"
        "        )",
        1,
    )
    result = result.replace(
        EXPRESSION_ANCHORS["instructions"],
        "+ (AVATAR_CALL_INSTRUCTIONS if protocol.animation_tools else '')\n"
        "                            + (KITTY_EXPRESSION_INSTRUCTIONS if protocol.kitty_expressions else '')",
        1,
    )
    result = result.replace(
        EXPRESSION_ANCHORS["tools"],
        "'tools': [CHAT_TOOL, *protocol.animation_tools, *([KITTY_EXPRESSION_TOOL] if protocol.kitty_expressions else [])],",
        1,
    )
    compile(result, TARGET, "exec")
    return result


def patch_sd_memory_instructions(source):
    # In-memory context only: the archive and fact store stay on the S3 SD.
    marker = "# CuteDisplay SD memory context relay v1"
    if marker in source:
        return source
    auth_anchor = "kitty_expressions = auth.get('kitty_expressions') is True"
    prompt_anchor = "+ (KITTY_EXPRESSION_INSTRUCTIONS if protocol.kitty_expressions else '')"
    if source.count(auth_anchor) != 1 or source.count(prompt_anchor) != 1:
        raise ValueError("SD memory context patch: incompatible realtime source")
    source = source.replace(
        auth_anchor,
        auth_anchor + "\n        " + marker + "\n        "
        + "kitty_sd_memory = auth.get('kitty_sd_memory', '')\n        "
        + "if not isinstance(kitty_sd_memory, str) or len(kitty_sd_memory.encode('utf-8')) > 850:\n"
        + "            kitty_sd_memory = ''",
        1,
    )
    source = source.replace(
        prompt_anchor,
        prompt_anchor
        + "\n                            + ('\\\nKnown user facts supplied by Kitty device (may be corrected by the user):\\\n' + kitty_sd_memory if protocol.kitty_expressions and kitty_sd_memory else '')",
        1,
    )
    compile(source, TARGET, "exec")
    return source


def patch_authentication(source):
    # Auth security can be unit-tested on its own minimal fixture. The full
    # realtime/gesture integration gets separate upstream protocol tests.
    if MARKER in source:
        if source.count(MARKER) != 1:
            raise ValueError("Multiple authorization patch markers")
        result = source
    else:
        for name, old in OLD.items():
            count = source.count(old)
            if count != 1:
                raise ValueError(
                    f"Unsupported Open WebUI version: expected exactly one "
                    f"{name} anchor, found {count}"
                )
        result = source
        for name in ("fastapi", "auth", "router", "initial", "renew"):
            result = result.replace(OLD[name], NEW[name], 1)
    compile(result, TARGET, "exec")
    return result


def patch(source):
    result = patch_authentication(source)
    result = patch_expressions(result)
    result = patch_sd_memory_instructions(result)
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
        print("PASS: source compatible with existing API-key authentication and opt-in Kitty expressions (no changes made)")
        print("Direct device endpoint remains: wss://YOUR-WEBUI-HOST/api/v1/audio/realtime")
        return 0
    # When extending an already-auth-patched Open WebUI image, the original
    # pristine auth backup may already exist from its first Docker build.
    # Preserve it untouched and create a separate expression rollback copy.
    backup = target.with_suffix(
        ".py.cutedisplay-pre-sd-memory" if "KITTY_EXPRESSION_TOOL" in original and "SD memory context relay v1" not in original
        else ".py.cutedisplay-pre-expression-v2" if EXPRESSION_MARKER in original
        else ".py.cutedisplay-pre-expression" if MARKER in original
        else ".py.cutedisplay-original"
    )
    if backup.exists() and updated != original:
        parser.error(f"Refusing to overwrite source backup: {backup}")
    if updated == original:
        print("PASS: realtime auth and expression capability already installed")
        return 0
    shutil.copy2(target, backup)
    target.write_text(updated)
    print("PATCHED Open WebUI source (auth preserved, Kitty expressions opt-in):", target)
    print("BACKUP of pristine source:", backup)
    print("No running server was modified. Inspect git diff, rebuild and run permissions/revocation tests.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
