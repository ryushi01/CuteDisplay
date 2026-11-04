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


def _own_nodes(func):
    """Only a function's own scope, never enclosing route / nested callbacks."""
    pending=list(reversed(func.body))
    while pending:
        node=pending.pop()
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,
                            ast.ClassDef,ast.Lambda)):
            continue
        yield node
        pending.extend(reversed(list(ast.iter_child_nodes(node))))


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
    for n in _own_nodes(func):
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


def _decoded_event_assignment(node):
    """Identify an assignment to the event object from a JSON decode.

    This is a structural clue, not proof of which socket supplied its bytes.
    """
    if isinstance(node,ast.Assign):
        targets=node.targets
        value=node.value
    elif isinstance(node,ast.AnnAssign):
        targets=[node.target]
        value=node.value
    else:
        return False
    if value is None or not any(isinstance(t,ast.Name) and t.id=="event"
                                for t in targets):
        return False
    if isinstance(value,ast.Await):
        value=value.value
    return (isinstance(value,ast.Call) and isinstance(value.func,ast.Attribute)
            and value.func.attr in ("loads","load","receive_json",
                                    "recv_json","json"))


def _kind_of_upstream_receive(func):
    """Fixed categories only; do not display variables, code or credentials."""
    modes=set()
    for n in _own_nodes(func):
        if isinstance(n,ast.AsyncFor):
            value=n.iter
            if isinstance(value,ast.Name) and value.id=="upstream":
                modes.add("async_for_upstream")
            elif isinstance(value,ast.Call):
                call=value.func
                if (isinstance(call,ast.Attribute)
                        and isinstance(call.value,ast.Name)
                        and call.value.id in ("upstream","provider")):
                    modes.add("async_for_provider_method")
        elif isinstance(n,ast.Call):
            call=n.func
            if (isinstance(call,ast.Attribute)
                    and isinstance(call.value,ast.Name)
                    and call.value.id in ("upstream","provider")
                    and call.attr in ("recv","receive","receive_json",
                                      "recv_json","iter_json","iter_text")):
                modes.add("provider_receive_method")
        elif isinstance(n,ast.Await):
            call=n.value
            if (isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute)
                    and call.func.attr in ("recv","receive","receive_json",
                                           "recv_json")
                    and isinstance(call.func.value,ast.Attribute)
                    and call.func.value.attr in ("ws","websocket")):
                modes.add("nested_provider_socket")
    return modes


def _gateway_topology(source, tree):
    """Read-only shape metadata. No raw source, paths, names or hashes returned."""
    funcs=[n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef)]
    providers=[f for f in funcs if f.name=="provider_events"]
    if len(providers)!=1:
        return {
            "named_provider_handler":_count_label(len(providers)),
            "provider_receive_shape":"not_verified",
            "provider_json_event_decodes":"not_verified",
            "provider_ws_event_forwards":"not_verified",
            "provider_transcript_literal":"not_verified",
            "event_decode_hook_candidate":"no",
        }
    func=providers[0]
    nodes=list(_own_nodes(func))
    receivers=_kind_of_upstream_receive(func)
    decoded=sum(_decoded_event_assignment(n) for n in nodes)
    forwarded=sum(_is_send_event(n) for n in nodes)
    transcript=TRANSCRIPT in (ast.get_source_segment(source,func) or "")
    shape=(
        "async_for_upstream" if "async_for_upstream" in receivers else
        "upstream_method" if "provider_receive_method" in receivers else
        "async_for_method" if "async_for_provider_method" in receivers else
        "nested_socket" if "nested_provider_socket" in receivers else
        "unrecognized")
    # This is a CANDIDATE only. A later patch still requires exact AST guards
    # and a dry-run; no source is modified, and no owner identity is inferred.
    candidate=(len(receivers)==1 and decoded==1 and forwarded>=1
               and sum(f.name=="client_events" for f in funcs)==1)
    return {
        "named_provider_handler":"one",
        "provider_receive_shape":shape,
        "provider_receive_modes":_count_label(len(receivers)),
        "provider_json_event_decodes":_count_label(decoded),
        "provider_ws_event_forwards":_count_label(forwarded),
        "provider_transcript_literal":"present" if transcript else "absent",
        "event_decode_hook_candidate":"yes" if candidate else "no",
    }


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
        for n in _own_nodes(f):
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
    extra=_gateway_topology(source,tree)
    return {
        **extra,
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
