#!/usr/bin/env python3
"""Read-only private Open WebUI owner receipt integration preflight.

Run inside the open-webui container:
  git show FETCH_HEAD:server/kitty_owner_gateway_preflight_v6.py |
      sudo docker exec -i open-webui python3 -

This reads a single fixed private realtime.py file but outputs only
closed-vocabulary statuses, NEVER source excerpts, source hashes, paths,
prompts, transcript text, credentials, environment variables or secrets.
No imports from the deployed gateway and no container/route mutations.

A static AST can identify *candidate* provider/client receive scopes, not
prove actual S3-device authentication, microphone provenance, anti-spoofing,
owner consent or operational model/receipt deployment. Those stay unverified.
"""
import ast
from pathlib import Path

LIVE = Path("/app/backend/open_webui/routers/audio/realtime.py")


def _scope_nodes(fn):
    stack = list(reversed(fn.body))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Lambda)):
            continue
        yield node
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _count(n):
    return "none" if n == 0 else "one" if n == 1 else "multiple"


def _owners(tree):
    parents = {}
    for p in ast.walk(tree):
        for child in ast.iter_child_nodes(p):
            parents[child] = p
    def enclosing(node):
        p = parents.get(node)
        while p is not None and not isinstance(
                p, (ast.AsyncFunctionDef, ast.FunctionDef)):
            p = parents.get(p)
        return p
    return enclosing


def _provider_candidate(tree):
    # Self-contained inside Docker: no dependency on deployed helper paths.
    # A strict candidate needs exactly one upstream loop, one direct decode
    # from that loop item and one observed provider->device forward.
    providers = [n for n in ast.walk(tree)
                 if isinstance(n, ast.AsyncFunctionDef)
                 and n.name == "provider_events"]
    if len(providers) != 1:
        return "not_verified"
    own = list(_scope_nodes(providers[0]))
    loops = [n for n in own if isinstance(n, ast.AsyncFor)
             and isinstance(n.iter, ast.Name) and n.iter.id == "upstream"
             and isinstance(n.target, ast.Name)]
    if len(loops) != 1:
        return "not_verified"
    loop = loops[0]
    decodes, forwards = 0, 0
    for n in _scope_nodes(providers[0]):
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(
                n.targets[0], ast.Name) and n.targets[0].id == "event":
            val = n.value.value if isinstance(n.value, ast.Await) else n.value
            if isinstance(val, ast.Call) and isinstance(val.func, ast.Attribute):
                func = val.func
                if (func.attr == "json" and not val.args
                        and isinstance(func.value, ast.Name)
                        and func.value.id == loop.target.id):
                    decodes += 1
                elif (func.attr == "loads" and len(val.args) == 1
                      and isinstance(func.value, ast.Name)
                      and func.value.id in ("json", "orjson")
                      and isinstance(val.args[0], ast.Name)
                      and val.args[0].id == loop.target.id):
                    decodes += 1
        if isinstance(n, ast.Await) and isinstance(n.value, ast.Call):
            call = n.value
            if (len(call.args) == 1 and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "send_json"
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == "ws"
                    and isinstance(call.args[0], ast.Name)
                    and call.args[0].id == "event"):
                forwards += 1
    return "candidate" if decodes == 1 and forwards == 1 else "not_verified"


def _client_receive_count(client):
    modes = set()
    for n in _scope_nodes(client):
        if isinstance(n, ast.AsyncFor):
            # The awaited websocket source must literally be ws, not a
            # client-supplied alias or a nested provider socket.
            if isinstance(n.iter, ast.Name) and n.iter.id == "ws":
                modes.add("async_for_ws")
        if not isinstance(n, ast.Call):
            continue
        func = n.func
        if (isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "ws"
                and func.attr in ("receive", "receive_json",
                                  "receive_text", "receive_bytes")):
            modes.add("ws_receive_method")
    return len(modes)


def analyze(source):
    result = {
        "source": "unavailable",
        "syntax": "unknown",
        "client_handler": "not_verified",
        "provider_handler": "not_verified",
        "common_route_scope": "not_verified",
        "provider_decode_scope": "not_verified",
        "s3_device_receive_scope": "not_verified",
        "authenticated_s3_device": "not_verified",
        "provider_to_s3_item_binding": "not_verified",
        "trusted_s3_microphone_capture": "not_verified",
        "owner_model_calibrated": "not_verified",
        "receipt_sd_write_confirmed": "not_verified",
        "live_owner_private_recall": "no",
        "deployment_ready": "no",
    }
    if not isinstance(source, str):
        return result
    result["source"] = "readable"
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, TypeError):
        result["syntax"] = "invalid"
        return result
    result["syntax"] = "valid"
    funcs = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)]
    providers = [f for f in funcs if f.name == "provider_events"]
    clients = [f for f in funcs if f.name == "client_events"]
    result["provider_handler"] = _count(len(providers))
    result["client_handler"] = _count(len(clients))
    if len(providers) != 1 or len(clients) != 1:
        return result
    parent = _owners(tree)
    if parent(providers[0]) is not parent(clients[0]) or parent(providers[0]) is None:
        return result
    result["common_route_scope"] = "candidate"
    result["provider_decode_scope"] = _provider_candidate(tree)
    modes = _client_receive_count(clients[0])
    if modes == 1:
        result["s3_device_receive_scope"] = "candidate"
    elif modes > 1:
        result["s3_device_receive_scope"] = "ambiguous"
    # Intentionally never say ready on AST alone. Even the most favorable
    # shape cannot prove that ws is authenticated as the original S3 device
    # rather than a browser, nor that exact S3 WAV and provider item exist.
    return result


def main():
    try:
        source = LIVE.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        source = None
    print("KITTY_V6_OWNER_GATEWAY_READ_ONLY")
    for name, value in analyze(source).items():
        print(name + "=" + value)
    print("No gateway, services, firmware, voice, storage, or secrets changed.")


if __name__ == "__main__":
    main()
