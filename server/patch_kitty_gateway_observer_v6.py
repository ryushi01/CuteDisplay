#!/usr/bin/env python3
"""Stage opt-in Kitty speaker event hooks in a reviewed realtime.py source.

Does not touch the running container. Both hooks are observational, guarded
against exceptions, and disabled unless KITTY_SPEAKER_GATEWAY_ENABLED=1.
Do not activate until the observer modules are mounted into Open WebUI.
"""
import argparse
import ast
from pathlib import Path

MARKER = "# Kitty V6 opt-in speaker observer hooks"
CLIENT_ANCHOR = "                event = JSONCodec.loads(raw)"
PROVIDER_FORWARD = "await ws.send_json(event)"
SETUP_ANCHOR = "        async def client_events():"

SETUP = """        # Kitty V6 optional observer; never required for existing voice.
        kitty_speaker_observer = None
        if os.environ.get('KITTY_SPEAKER_GATEWAY_ENABLED') == '1':
            try:
                from open_webui.kitty_realtime_gateway_observer_v6 import KittySpeakerObserver
                kitty_speaker_observer = KittySpeakerObserver(
                    ws.send_json, enabled=True)
            except Exception:
                kitty_speaker_observer = None  # preserve voice on feature errors
"""

CLIENT_HOOK = """                # Audio forwarding stays unchanged; observer failures are isolated.
                if kitty_speaker_observer is not None:
                    try:
                        kitty_speaker_observer.observe_client(event)
                    except Exception:
                        kitty_speaker_observer.close()
                        kitty_speaker_observer = None
"""

UPSTREAM_HOOK = """                    # Observer only; never change the upstream event.
                    if kitty_speaker_observer is not None:
                        try:
                            kitty_speaker_observer.observe_upstream(event)
                        except Exception:
                            kitty_speaker_observer.close()
                            kitty_speaker_observer = None
"""

def patch(source):
    if MARKER in source:
        compile(source, "realtime.py", "exec")
        return source
    tree = ast.parse(source)
    client = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "client_events"]
    provider = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "provider_events"]
    if len(client) != 1 or len(provider) != 1:
        raise ValueError("Missing unique event handlers")
    if source.count(CLIENT_ANCHOR) != 1 or source.count(SETUP_ANCHOR) != 1:
        raise ValueError("Unexpected client event layout")

    # Locate the actual outgoing event within provider_events, not a string
    # match elsewhere in the call or login handshake.
    lines = source.splitlines(keepends=True)
    p = provider[0]
    forwards = []
    for i in range(p.lineno - 1, p.end_lineno):
        if PROVIDER_FORWARD in lines[i]:
            forwards.append(i)
    if len(forwards) != 1:
        raise ValueError("Expected one provider event forwarding call")
    index = forwards[0]
    indentation = len(lines[index]) - len(lines[index].lstrip(" "))
    # Adapt the hook to the original forwarding statement's indentation.
    import textwrap
    forward_hook = textwrap.indent(textwrap.dedent(UPSTREAM_HOOK), " " * indentation)
    lines.insert(index, forward_hook)
    result = "".join(lines)
    # Nonlocal keyword is needed because an observer can be set to None on error.
    old = "            nonlocal kitty_memory_last_revision, kitty_memory_context_item, kitty_semantic_task"
    if result.count(old) != 1:
        raise ValueError("Expected current client nonlocal anchor")
    result = result.replace(old, old + ", kitty_speaker_observer", 1)
    # provider events also assigns observer on error, requiring nonlocal.
    prov_header = "        async def provider_events():"
    if result.count(prov_header) != 1:
        raise ValueError("Unexpected provider declaration")
    result = result.replace(prov_header, prov_header + "\n            nonlocal kitty_speaker_observer", 1)
    result = result.replace(CLIENT_ANCHOR, CLIENT_ANCHOR + "\n" + CLIENT_HOOK.rstrip("\n"), 1)
    result = result.replace(SETUP_ANCHOR, "        " + MARKER + "\n" + SETUP + SETUP_ANCHOR, 1)
    compile(result, "realtime.py", "exec")
    return result

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--file", required=True)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    path = Path(args.file)
    original = path.read_text()
    modified = patch(original)
    if args.apply and modified != original:
        from datetime import datetime
        import shutil
        backup = path.with_name(path.name + ".before-observer-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
        shutil.copy2(path, backup)
        path.write_text(modified)
        print("Backup:", backup)
    print("KITTY_OBSERVER_" + ("PATCHED" if args.apply else "CHECK_OK"))
if __name__ == "__main__":
    main()
