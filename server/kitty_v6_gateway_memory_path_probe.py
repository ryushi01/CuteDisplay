#!/usr/bin/env python3
"""Read-only, no-source-leak audit of Kitty's installed realtime memory path.

Run through the live Open WebUI container on stdin. Report only allowlisted
structural flags: never print source, environment, prompts, headers,
transcripts, API keys, URLs, speaker IDs or memory content.

This diagnoses why an SD-saved event can fail to reach a realtime reply,
without sending any upstream events or making the earlier rejected RAM patch.
"""
import ast
from pathlib import Path

SOURCE = Path("/app/backend/open_webui/routers/audio/realtime.py")
MARKERS = {
    "public_profile": "KITTY_INITIAL_PUBLIC_PROFILE_V6",
    "approved_shared_context": "KITTY_APPROVED_SHARED_INITIAL_CONTEXT_V6",
    "approved_shared_on_session_updates": "KITTY_SHARED_CONTEXT_PERSIST_SESSION_V6",
    "approved_shared_on_responses": "KITTY_SHARED_CONTEXT_PERSIST_RESPONSE_V6",
    "sd_public_refresh_route": "kitty.memory.refresh",
    "semantic_private_request_route": "kitty.memory.semantic",
    "speaker_observer": "KittySpeakerObserver",
    "passive_provider_hook": "KITTY_V6_PROVIDER_DECODE_PASSIVE_HOOK",
    "unsafe_experimental_ram_hook": "KITTY_V6_CALL_RAM_ONLY_HOOK",
    "trusted_live_turn_issuer": "AttestedLiveCall",
    "legacy_probable_recall": "authorized_recall(",
}


def _own_nodes(func):
    pending = list(reversed(func.body))
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        yield node
        pending.extend(reversed(list(ast.iter_child_nodes(node))))


def _label(n):
    return "none" if n == 0 else "one" if n == 1 else "multiple"


def _event_lit(nodes, value):
    return any(isinstance(n, ast.Constant) and n.value == value for n in nodes)


def _upstream_sends(nodes):
    return sum(
        isinstance(n, ast.Await)
        and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Attribute)
        and n.value.func.attr in ("send", "send_json", "send_text")
        and isinstance(n.value.func.value, ast.Name)
        and n.value.func.value.id == "upstream"
        for n in nodes
    )


def probe(source):
    result = {"source": "readable" if isinstance(source, str) else "unavailable"}
    if source is None:
        return {"source": "unavailable", "syntax": "unknown",
                **{k: "unknown" for k in MARKERS}}
    try:
        tree = ast.parse(source)
    except (SyntaxError, TypeError, ValueError):
        return {"source": "readable", "syntax": "invalid",
                **{k: "unknown" for k in MARKERS}}
    result["syntax"] = "valid"
    functions = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)]
    clients = [n for n in functions if n.name == "client_events"]
    providers = [n for n in functions if n.name == "provider_events"]
    result["client_handler"] = _label(len(clients))
    result["provider_handler"] = _label(len(providers))
    if len(clients) == 1:
        nodes = list(_own_nodes(clients[0]))
        result["client_upstream_sends"] = _label(_upstream_sends(nodes))
        result["client_session_update_branch"] = ("present"
            if _event_lit(nodes, "session.update") else "absent")
        result["client_response_create_branch"] = ("present"
            if _event_lit(nodes, "response.create") else "absent")
    else:
        result["client_upstream_sends"] = "not_verified"
        result["client_session_update_branch"] = "not_verified"
        result["client_response_create_branch"] = "not_verified"
    if len(providers) == 1:
        nodes = list(_own_nodes(providers[0]))
        result["upstream_final_transcription"] = ("present"
            if _event_lit(nodes, "conversation.item.input_audio_transcription.completed")
            else "absent")
    else:
        result["upstream_final_transcription"] = "not_verified"
    result.update({k: ("present" if marker in source else "absent")
                   for k, marker in MARKERS.items()})
    # Structural proof cannot substitute for testing the provider with an
    # authenticated non-private session; no live changes are justified here.
    result["safe_to_enable_private_history"] = "no"
    result["safe_to_reapply_failed_ram_hook"] = "no"
    return result


def main():
    try:
        source = SOURCE.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        source = None
    print("KITTY_V6_GATEWAY_MEMORY_PATH_READ_ONLY")
    for key, value in probe(source).items():
        print(f"{key}={value}")
    print("changes=none")


if __name__ == "__main__":
    main()
