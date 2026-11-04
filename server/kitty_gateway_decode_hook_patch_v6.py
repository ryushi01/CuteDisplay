#!/usr/bin/env python3
"""Exact AST-guarded provider *decode* hook, no browser-forward edits.

Input: private Open WebUI realtime.py as UTF-8 string. No side effects.
Only a uniquely identified upstream provider loop with one direct JSON
event decode and exactly one same-function ws.send_json(event) may be patched.
The hook observes provider events without signing, memory injection, request
routing, prompt mutation, logging or altering the event object.

The actual operator's read-only shape (Nov 4):
  provider_events=one, async_for_upstream=one, event_decodes=one,
  provider forwards=one, explicit transcript branch absent.
"""
import ast

MARK = "# KITTY_V6_PROVIDER_DECODE_PASSIVE_HOOK"
_TYPES = (
    "input_audio_buffer.speech_started",
    "input_audio_buffer.speech_stopped",
    "conversation.item.input_audio_transcription.completed",
    "conversation.item.input_audio_transcription.failed",
    "error",
)


class HookRefusal(ValueError):
    pass


def _own_nodes(func):
    pending=list(reversed(func.body))
    while pending:
        node=pending.pop()
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,
                            ast.ClassDef,ast.Lambda)):
            continue
        yield node
        pending.extend(reversed(list(ast.iter_child_nodes(node))))


def _direct_decode(node, loopvar):
    if not isinstance(node,ast.Assign) or len(node.targets)!=1:
        return False
    if not isinstance(node.targets[0],ast.Name) or node.targets[0].id!="event":
        return False
    value=node.value
    if (not isinstance(value,ast.Call)
            or not isinstance(value.func,ast.Attribute)
            or value.func.attr not in ("loads","load")
            or len(value.args)!=1 or value.keywords):
        return False
    # Direct json.loads(raw): strongly bind the decoded event to the single
    # upstream loop, rather than reusing client-supplied objects.
    return isinstance(value.args[0],ast.Name) and value.args[0].id==loopvar


def _is_forward(node):
    if not isinstance(node,ast.Await) or not isinstance(node.value,ast.Call):
        return False
    call=node.value
    return (len(call.args)==1
            and isinstance(call.func,ast.Attribute)
            and call.func.attr=="send_json"
            and isinstance(call.func.value,ast.Name)
            and call.func.value.id=="ws"
            and isinstance(call.args[0],ast.Name)
            and call.args[0].id=="event")


def _target(tree):
    functions=[n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef)]
    provider=[n for n in functions if n.name=="provider_events"]
    if len(provider)!=1 or sum(n.name=="client_events" for n in functions)!=1:
        raise HookRefusal("provider_scope_unrecognized")
    target=provider[0]
    loops=[n for n in _own_nodes(target)
           if isinstance(n,ast.AsyncFor)
           and isinstance(n.iter,ast.Name) and n.iter.id=="upstream"
           and isinstance(n.target,ast.Name)]
    if len(loops)!=1:
        raise HookRefusal("provider_loop_unrecognized")
    loop=loops[0]
    if (len(loop.orelse)>0 or loop.target.id in ("event","ws")
            or len([n for n in _own_nodes(target) if _is_forward(n)])!=1):
        raise HookRefusal("provider_forward_ambiguous")
    # Only direct loop-body event=decoder.loads(raw) is acceptable.
    decode=[n for n in loop.body if _direct_decode(n,loop.target.id)]
    if len(decode)!=1:
        raise HookRefusal("provider_decode_unrecognized")
    stmt=decode[0]
    if any(not isinstance(x,ast.Expr) or x is not loop.body[0]
           for x in (loop.body[0],)) and stmt is not loop.body[0]:
        # Any preceding try/filter means decode is not the obvious origin.
        raise HookRefusal("provider_decode_not_first")
    if stmt is not loop.body[0]:
        raise HookRefusal("provider_decode_not_first")
    if stmt.end_lineno is None or stmt.end_lineno!=stmt.lineno:
        raise HookRefusal("multiline_decode_unrecognized")
    return target,loop,stmt


def patch(source):
    if not isinstance(source,str) or MARK in source:
        raise HookRefusal("already_patched_or_invalid")
    try:
        tree=ast.parse(source)
        target,loop,decode=_target(tree)
    except (SyntaxError,ValueError,TypeError) as exc:
        if isinstance(exc,HookRefusal):
            raise
        raise HookRefusal("gateway_python_invalid") from None
    lines=source.splitlines(keepends=True)
    if not lines or any(not line.endswith("\n") for line in lines[:-1]):
        raise HookRefusal("unsupported_newline_layout")
    first=target.body[0]
    if (isinstance(first,ast.Expr)
            and isinstance(first.value,(ast.Constant,ast.Str))
            and isinstance(getattr(first.value,"value",None),str)):
        insert_init_after=first.end_lineno
        indent=" " * first.col_offset
    else:
        insert_init_after=first.lineno-1
        indent=" " * first.col_offset
    if ("\t" in lines[decode.lineno-1][:decode.col_offset]
            or "\t" in lines[first.lineno-1][:first.col_offset]):
        raise HookRefusal("tabs_unrecognized")
    if lines[decode.lineno-1][:decode.col_offset].strip():
        raise HookRefusal("decode_line_ambiguous")
    # Imports are deliberately lazy and optional: if the passive helper
    # doesn't import, the normal voice relay remains unchanged.
    init=(
        indent+MARK+"\n"
        +indent+"_kitty_v6_passive = None\n"
        +indent+"try:\n"
        +indent+"    from kitty_passive_turn_bridge_v6 import KittyPassiveTurnBridge as _KittyV6Passive\n"
        +indent+"    _kitty_v6_passive = _KittyV6Passive()\n"
        +indent+"except (ImportError, ValueError, TypeError, RuntimeError):\n".replace("except ",indent+"except ",1)
        +indent+"    _kitty_v6_passive = None\n"
    )
    # For performance, parse only five provider event types. No audio delta
    # processing, no prompts, no private lookup and no log output.
    i=" "*decode.col_offset
    hook=(
        i+"if (_kitty_v6_passive is not None and isinstance(event, dict)\n"
        +i+"        and event.get('type') in "+repr(_TYPES)+"):\n"
        +i+"    try:\n"
        +i+"        _kitty_v6_passive.from_provider(event)\n"
        +i+"    except Exception:\n"
        +i+"        _kitty_v6_passive = None\n"
    )
    # Edits are performed from bottom upward to keep precise AST offsets.
    inserts={insert_init_after:[init],decode.end_lineno:[hook]}
    for index in sorted(inserts,reverse=True):
        lines[index:index]=inserts[index]
    candidate="".join(lines)
    try:
        compiled=ast.parse(candidate)
        compile(candidate,"<kitty-guarded-gateway>","exec")
    except (SyntaxError,ValueError):
        raise HookRefusal("candidate_python_invalid") from None
    # Mandatory postcondition: same number of original client->provider and
    # provider->client forwards, and only one isolated lazy provider hook.
    def _counts(t):
        nodes=list(ast.walk(t))
        return (
            sum(_is_forward(n) for n in nodes),
            sum(isinstance(n,ast.AsyncFunctionDef)
                and n.name=="client_events" for n in nodes),
            sum(isinstance(n,ast.AsyncFunctionDef)
                and n.name=="provider_events" for n in nodes)
        )
    if (_counts(tree)!=_counts(compiled)
            or candidate.count(MARK)!=1
            or candidate.count("_kitty_v6_passive.from_provider(event)")!=1):
        raise HookRefusal("postcondition_failed")
    return candidate


def status(source):
    try:
        target,loop,decode=_target(ast.parse(source))
        return "compatible"
    except (SyntaxError,ValueError,TypeError):
        return "incompatible"
