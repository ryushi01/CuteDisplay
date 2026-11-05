#!/usr/bin/env python3
"""Fail-closed source-only gateway patch for existing response.create events.

IMPORTANT: This is NOT a deployment script. It performs a read-only
compatibility check on the live gateway when run with --check. The pure patch()
transformation is available to offline tests/guarded future rollout only.

No direct provider session.update, conversation.item.create or extra WebSocket
sends. Do not activate until actual route topology is verified, regression
tests pass and rollback is prepared. Never imports speaker-owner grants.
"""
import ast
import argparse
from pathlib import Path

MARK = "# KITTY_V6_RESPONSE_BOUND_CALL_CONTEXT_V6"
PASSIVE = "# KITTY_V6_PROVIDER_DECODE_PASSIVE_HOOK"
SHARED = "# KITTY_SHARED_CONTEXT_PERSIST_RESPONSE_V6"
RESPONSE_ANCHOR = "# KITTY_XVECTOR_CONVERSATION_HINT_V6"
EXPERIMENTAL = "# KITTY_V6_CALL_RAM_ONLY_HOOK"
LIVE = Path("/app/backend/open_webui/routers/audio/realtime.py")


class Refusal(ValueError):
    pass


def _own_nodes(func):
    pending = list(reversed(func.body))
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        yield node
        pending.extend(reversed(list(ast.iter_child_nodes(node))))


def _call_named(node, obj, name):
    return (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == obj and node.func.attr == name)


def _parent_functions(tree):
    parents = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    def parent_function(node):
        p = parents.get(node)
        while p is not None and not isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef)):
            p = parents.get(p)
        return p
    return parent_function


def _indent(line):
    return line[:len(line) - len(line.lstrip(" "))]


def _upstream_sends(nodes):
    return [
        n for n in nodes if isinstance(n, ast.Await)
        and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Attribute)
        and n.value.func.attr in ("send", "send_json", "send_str", "send_text")
        and isinstance(n.value.func.value, ast.Name)
        and n.value.func.value.id == "upstream"
    ]


def patch(source):
    if not isinstance(source, str):
        raise Refusal("gateway_source_invalid")
    if (source.count(PASSIVE) != 1 or source.count(SHARED) != 1
            or source.count(RESPONSE_ANCHOR) != 1):
        raise Refusal("required_gateway_hooks_missing")
    if MARK in source or EXPERIMENTAL in source or "_kitty_v6_callnotes" in source:
        raise Refusal("existing_or_failed_hook_present")
    try:
        tree = ast.parse(source)
    except (SyntaxError, TypeError, ValueError):
        raise Refusal("invalid_gateway_python") from None

    funcs = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)]
    clients = [n for n in funcs if n.name == "client_events"]
    providers = [n for n in funcs if n.name == "provider_events"]
    if len(clients) != 1 or len(providers) != 1:
        raise Refusal("gateway_handlers_ambiguous")
    client, provider = clients[0], providers[0]
    ancestor = _parent_functions(tree)
    if (ancestor(client) is None or ancestor(client) is not ancestor(provider)
            or client.col_offset != provider.col_offset):
        raise Refusal("handlers_not_same_websocket_scope")
    provider_loops = [n for n in _own_nodes(provider)
                      if isinstance(n, ast.AsyncFor)
                      and isinstance(n.iter, ast.Name)
                      and n.iter.id == "upstream"]
    if len(provider_loops) != 1:
        raise Refusal("provider_loop_not_verified")
    loop = provider_loops[0]
    passive_calls = [n for n in ast.walk(loop)
                     if _call_named(n, "_kitty_v6_passive", "from_provider")]
    if len(passive_calls) != 1 or len(passive_calls[0].args) != 1:
        raise Refusal("passive_event_observer_not_verified")
    if not (isinstance(passive_calls[0].args[0], ast.Name)
            and passive_calls[0].args[0].id == "event"):
        raise Refusal("passive_event_scope_mismatch")
    enclosing = [n for n in ast.walk(loop)
                 if isinstance(n, ast.If)
                 and any(c is passive_calls[0] for c in ast.walk(n))]
    if not enclosing:
        raise Refusal("passive_guard_missing")
    guard = min(enclosing, key=lambda n: n.end_lineno - n.lineno)
    if guard.end_lineno >= loop.end_lineno:
        raise Refusal("passive_scope_invalid")
    forwards = [n for n in _own_nodes(provider)
                if isinstance(n, ast.Await)
                and _call_named(n.value, "ws", "send_json")
                and len(n.value.args) == 1
                and isinstance(n.value.args[0], ast.Name)
                and n.value.args[0].id == "event"]
    if len(forwards) != 1 or forwards[0].lineno <= guard.end_lineno:
        raise Refusal("provider_forward_not_verified")

    lines = source.splitlines(keepends=True)
    def marker_index(marker):
        found = [i for i, line in enumerate(lines)
                 if marker in line and line.lstrip().startswith(marker)]
        if len(found) != 1:
            raise Refusal("marker_ambiguous")
        return found[0]
    passive_at = marker_index(PASSIVE)
    shared_at = marker_index(SHARED)
    response_at = marker_index(RESPONSE_ANCHOR)
    if not (provider.lineno - 1 <= passive_at < guard.lineno
            and client.lineno - 1 < shared_at < response_at < client.end_lineno
            and shared_at < response_at):
        raise Refusal("marker_scope_mismatch")
    if response_at <= client.lineno or not any(
            n.lineno > response_at + 1 for n in _upstream_sends(_own_nodes(client))):
        raise Refusal("response_command_forward_not_verified")
    # The existing approved shared-memory hook must be in the same client
    # command scope and already refer to the materialized "command" variable.
    block = "\n".join(lines[shared_at:response_at])
    if ("command" not in block or "response.create" not in block
            or "instructions" not in block):
        raise Refusal("response_command_not_verified")
    if (not 0 < client.col_offset < guard.col_offset
            or "\t" in _indent(lines[guard.lineno-1])
            or "\t" in _indent(lines[response_at])):
        raise Refusal("unrecognized_indentation")
    init_indent = " " * client.col_offset
    provider_indent = _indent(lines[guard.lineno-1])
    client_indent = _indent(lines[response_at])
    if len(client_indent) <= len(init_indent):
        raise Refusal("client_scope_invalid")

    init = (
        init_indent + MARK + "\n"
        + init_indent + "_kitty_v6_callnotes = None\n"
        + init_indent + "try:\n"
        + init_indent + "    from kitty_response_bound_call_context_v6 import ResponseBoundCallContext\n"
        + init_indent + "    _kitty_v6_callnotes = ResponseBoundCallContext()\n"
        + init_indent + "except (ImportError, TypeError, ValueError, RuntimeError):\n"
        + init_indent + "    _kitty_v6_callnotes = None\n"
    )
    provider_hook = (
        provider_indent + "if _kitty_v6_callnotes is not None and isinstance(event, dict):\n"
        + provider_indent + "    try:\n"
        + provider_indent + "        _kitty_v6_callnotes.on_provider_event(event)\n"
        + provider_indent + "    except Exception:\n"
        + provider_indent + "        _kitty_v6_callnotes.close()\n"
    )
    client_hook = (
        client_indent + "if _kitty_v6_callnotes is not None:\n"
        + client_indent + "    try:\n"
        + client_indent + "        command = _kitty_v6_callnotes.on_existing_client_command(command)\n"
        + client_indent + "    except Exception:\n"
        + client_indent + "        _kitty_v6_callnotes.close()\n"
    )
    edits = [(guard.end_lineno, provider_hook),
             (response_at, client_hook),
             (client.lineno - 1, init)]
    if len({a for a, _ in edits}) != 3:
        raise Refusal("insertion_positions_ambiguous")
    for index, addition in sorted(edits, reverse=True):
        lines[index:index] = [addition]
    candidate = "".join(lines)
    try:
        new_ast = ast.parse(candidate)
        compile(candidate, "<kitty-response-bound-call>", "exec")
    except (SyntaxError, ValueError, TypeError):
        raise Refusal("candidate_source_invalid") from None
    # No extra send calls, model commands, provider forwarding or auth paths.
    old_sends = _upstream_sends(ast.walk(tree))
    new_sends = _upstream_sends(ast.walk(new_ast))
    if (len(old_sends) != len(new_sends)
            or candidate.count("await ws.send_json(event)") != source.count("await ws.send_json(event)")
            or candidate.count("_kitty_v6_passive.from_provider(event)") != source.count(
                "_kitty_v6_passive.from_provider(event)")
            or candidate.count("session.update") != source.count("session.update")
            or candidate.count("conversation.item.create") != source.count("conversation.item.create")
            or candidate.count(MARK) != 1):
        raise Refusal("postcondition_failed")
    return candidate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", required=True)
    args = parser.parse_args()
    try:
        original = LIVE.read_text(encoding="utf-8")
        patch(original)
    except Refusal as exc:
        print("response_bound_compatibility=refused")
        print("reason=" + str(exc))
    except (OSError, UnicodeError):
        print("response_bound_compatibility=unreadable")
    else:
        print("response_bound_compatibility=compatible")
    print("deployed=no")
    print("provider_new_commands=none")
    print("private_recall=disabled")
    print("changes=none")


if __name__ == "__main__":
    main()
