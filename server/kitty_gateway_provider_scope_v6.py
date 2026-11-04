#!/usr/bin/env python3
"""Read-only actual-Open-WebUI integration scope check for Kitty V6.

This tool never prints/reveals custom gateway source, model prompts,
transcripts, environment, paths or tokens. It reads only the private
realtime.py and uses Python AST to locate the prospective passive observer
hook in the *provider* receive function. Refuse ambiguous paths; absence of
the expected event loops is NOT a live gateway failure.

Run:
  git show FETCH_HEAD:server/kitty_gateway_provider_scope_v6.py |
    sudo docker exec -i open-webui python3 -

Nothing is deployed by this check.
"""
import ast
from pathlib import Path

REALTIME = Path("/app/backend/open_webui/routers/audio/realtime.py")
TRANSCRIPT = "conversation.item.input_audio_transcription.completed"


def _async_scope(node):
    """Outer direct scope of an async forwarding operation (no nested funcs)."""
    for child in ast.walk(node):
        if isinstance(child,(ast.FunctionDef,ast.AsyncFunctionDef)) and child is not node:
            return False
    return True


def _count_label(value):
    return "none" if value==0 else "one" if value==1 else "multiple"


def _is_send_event(node):
    if not isinstance(node,ast.Await):return False
    call=node.value
    if not isinstance(call,ast.Call) or len(call.args)!=1:return False
    func=call.func
    return (isinstance(func,ast.Attribute) and func.attr=="send_json"
            and isinstance(func.value,ast.Name) and func.value.id=="ws"
            and isinstance(call.args[0],ast.Name)
            and call.args[0].id=="event")


def _provider_receive_clues(func):
    # If the local event comes from the upstream socket, the gateway should
    # contain one of these in the *same* async scope. No raw code is emitted.
    uses_upstream=False
    for n in ast.walk(func):
        if isinstance(n,ast.Call):
            f=n.func
            if (isinstance(f,ast.Attribute)
                    and isinstance(f.value,ast.Name)
                    and f.value.id in ("upstream","provider")
                    and f.attr in ("recv","receive","receive_json","recv_json")):
                uses_upstream=True
        if isinstance(n,ast.AsyncFor):
            if "upstream" in ast.unparse(n.iter):
                uses_upstream=True
    return uses_upstream


def analyze(source):
    if not isinstance(source,str):
        return {"source":"unavailable","syntax":"unknown",
                "provider_scope":"not_verified",
                "passive_hook_safe":"no",
                "live_owner_history_enable":"no"}
    try:
        tree=ast.parse(source)
    except (SyntaxError,ValueError,TypeError):
        return {"source":"readable","syntax":"invalid",
                "provider_scope":"not_verified",
                "passive_hook_safe":"no",
                "live_owner_history_enable":"no"}
    funcs=[f for f in ast.walk(tree) if isinstance(f,ast.AsyncFunctionDef)]
    matches=[]
    for f in funcs:
        if f.name=="client_events":
            continue
        # A nested provider loop may occur in a local route coroutine.
        for n in ast.walk(f):
            if _is_send_event(n):
                matches.append((f,n))
    candidates=[]
    for f,n in matches:
        segment=ast.get_source_segment(source,f) or ""
        if TRANSCRIPT in segment and _provider_receive_clues(f):
            candidates.append((f,n))
    # Multiple line-level forwarding calls may be legitimate, and must never
    # be patched indiscriminately. Require one uniquely identifiable scope.
    unique_scopes={(f.lineno,f.end_lineno) for f,n in candidates}
    safe=(len(unique_scopes)==1 and len(candidates)==1
          and sum(1 for f in funcs if f.name=="client_events")==1)
    return {
        "source":"readable",
        "syntax":"valid",
        "async_handlers":_count_label(len(funcs)),
        "client_handler":_count_label(sum(f.name=="client_events" for f in funcs)),
        "all_ws_event_forwards":_count_label(len(set(n.lineno for f,n in matches))),
        "provider_transcript_scope":_count_label(len(unique_scopes)),
        "provider_forwards_in_scope":_count_label(len(candidates)),
        "provider_receive_clue":"present" if candidates else "not_verified",
        "passive_hook_safe":"yes" if safe else "no",
        "trusted_turn_issuer":"not_verified",
        "live_owner_history_enable":"no",
    }


def main():
    try:
        source=REALTIME.read_text(encoding="utf-8")
    except (OSError,UnicodeError):
        source=None
    result=analyze(source)
    print("KITTY_V6_PROVIDER_SCOPE_READ_ONLY")
    for key,value in result.items():
        print(f"{key}={value}")
    print("No gateway, container, audio, firmware, memory or settings changed.")


if __name__=="__main__":
    main()
