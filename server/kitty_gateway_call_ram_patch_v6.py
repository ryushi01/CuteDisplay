#!/usr/bin/env python3
"""Exact-once source patch for the already-installed Kitty passive provider hook.

Pure transformation only. No disk/network/process access. Fail closed on
unknown gateway topology; never alter incoming audio, browser forwarding,
private memory, prompts, tools or persistent storage. This patch only adds
per-connection RAM context and an optional provider session.update after a
trusted upstream completed transcript.
"""
import ast

MARK = "# KITTY_V6_CALL_RAM_ONLY_HOOK"
EXISTING = "# KITTY_V6_PROVIDER_DECODE_PASSIVE_HOOK"


class Refusal(ValueError):
    pass


def _owner_nodes(func):
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
            and node.func.value.id == obj
            and node.func.attr == name)


def _indent(line):
    return line[:len(line) - len(line.lstrip(" "))]


def patch(source):
    if not isinstance(source, str) or EXISTING not in source:
        raise Refusal("passive_provider_hook_not_installed")
    if source.count(EXISTING) != 1 or MARK in source or "_kitty_v6_ram" in source:
        raise Refusal("already_patched_or_ambiguous")
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, TypeError):
        raise Refusal("invalid_gateway_python") from None
    funcs = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)]
    providers = [n for n in funcs if n.name == "provider_events"]
    clients = [n for n in funcs if n.name == "client_events"]
    if len(providers) != 1 or len(clients) != 1:
        raise Refusal("gateway_function_scope_incompatible")
    provider = providers[0]
    loops = [n for n in _owner_nodes(provider)
             if isinstance(n, ast.AsyncFor) and isinstance(n.iter, ast.Name)
             and n.iter.id == "upstream"]
    if len(loops) != 1:
        raise Refusal("provider_loop_incompatible")
    loop = loops[0]
    # Hook must originate inside the authenticated provider loop, never the
    # S3 client loop. The existing provider observer was already AST checked.
    calls = [n for n in ast.walk(loop)
             if _call_named(n, "_kitty_v6_passive", "from_provider")]
    if len(calls) != 1 or len(calls[0].args) != 1 or not (
            isinstance(calls[0].args[0], ast.Name) and calls[0].args[0].id == "event"):
        raise Refusal("existing_provider_observer_incompatible")
    candidates = [n for n in ast.walk(loop) if isinstance(n, ast.If)
                  and any(x is calls[0] for x in ast.walk(n))]
    if not candidates:
        raise Refusal("observer_guard_missing")
    # Choose the narrowest enclosing if guard; require this to be the direct
    # provider event guard, not a broad conditional around the entire loop.
    guard = min(candidates, key=lambda n: n.end_lineno - n.lineno)
    if guard.lineno <= provider.lineno or guard.end_lineno >= loop.end_lineno:
        raise Refusal("observer_guard_scope_incompatible")
    # The exact provider->browser event forwarding must remain after the
    # observer, in the same handler; extra forwards elsewhere are irrelevant.
    forwards = [n for n in _owner_nodes(provider)
                if isinstance(n, ast.Await)
                and _call_named(n.value, "ws", "send_json")
                and len(n.value.args) == 1
                and isinstance(n.value.args[0], ast.Name)
                and n.value.args[0].id == "event"]
    if len(forwards) != 1 or forwards[0].lineno <= guard.end_lineno:
        raise Refusal("provider_forwarding_incompatible")
    lines = source.splitlines(keepends=True)
    marker_lines = [i for i, line in enumerate(lines)
                    if EXISTING in line and line.lstrip().startswith(EXISTING)]
    if len(marker_lines) != 1 or marker_lines[0] >= guard.lineno:
        raise Refusal("init_anchor_missing")
    m = marker_lines[0]
    if not (provider.lineno - 1 <= m < provider.end_lineno):
        raise Refusal("init_not_in_provider")
    if any("\t" in line[:len(line)-len(line.lstrip())]
           for line in (lines[m], lines[guard.lineno - 1])):
        raise Refusal("tabs_not_supported")
    init_indent = _indent(lines[m])
    guard_indent = _indent(lines[guard.lineno - 1])
    if not init_indent or not guard_indent or len(guard_indent) <= len(init_indent):
        raise Refusal("indentation_incompatible")
    init = (
        init_indent + MARK + "\n"
        + init_indent + "_kitty_v6_ram = None\n"
        + init_indent + "try:\n"
        + init_indent + "    from kitty_volatile_call_context_v6 import VolatileCallContext\n"
        + init_indent + "    _kitty_v6_ram = VolatileCallContext()\n"
        + init_indent + "except (ImportError, TypeError, RuntimeError):\n"
        + init_indent + "    _kitty_v6_ram = None\n"
    )
    body = (
        guard_indent + "if _kitty_v6_ram is not None and isinstance(event, dict):\n"
        + guard_indent + "    try:\n"
        + guard_indent + "        _kitty_v6_update = _kitty_v6_ram.on_provider_event(event)\n"
        + guard_indent + "        if _kitty_v6_update is not None:\n"
        + guard_indent + "            await upstream.send_json(_kitty_v6_update)\n"
        + guard_indent + "    except Exception:\n"
        + guard_indent + "        _kitty_v6_ram.close()\n"
        + guard_indent + "        _kitty_v6_ram = None\n"
    )
    # Bottom-up insertion keeps AST line indices valid.
    edits = [(guard.end_lineno, body), (m, init)]
    if edits[0][0] <= edits[1][0]:
        raise Refusal("edit_order_invalid")
    for at, code in edits:
        lines[at:at] = [code]
    candidate = "".join(lines)
    try:
        result = ast.parse(candidate)
        compile(candidate, "<kitty-ram-gateway>", "exec")
    except (SyntaxError, ValueError, TypeError):
        raise Refusal("candidate_syntax_invalid") from None
    if (candidate.count(MARK) != 1
            or candidate.count("await upstream.send_json(_kitty_v6_update)") != 1
            or len([n for n in ast.walk(result) if isinstance(n, ast.AsyncFunctionDef)
                    and n.name == "provider_events"]) != 1
            or source.count("await ws.send_json(event)") != candidate.count("await ws.send_json(event)")
            or source.count("_kitty_v6_passive.from_provider(event)") != candidate.count("_kitty_v6_passive.from_provider(event)")):
        raise Refusal("postcondition_failed")
    return candidate
