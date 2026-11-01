#!/usr/bin/env python3
"""Patch the already deployed Kitty realtime gateway in place, without touching audio paths."""
import argparse
import ast
import re
from pathlib import Path

def patch(source):
    edits = [
        (
            "async def kitty_semantic_reply(request_id, turn_id, speaker_id, query):",
            "async def kitty_semantic_reply(request_id, turn_id, speaker_id, query, observer, epoch):",
        ),
        (
            "            import os\n            try:\n                from open_webui.kitty_semantic_async_client_v6 import semantic_context",
            "            import os\n            if observer is None or observer.authorized_recall(\n                    turn_id, speaker_id, 'voice_probable') != epoch:\n                return\n            try:\n                from open_webui.kitty_semantic_async_client_v6 import semantic_context",
        ),
        (
            "            if isinstance(result, str) and result:\n                await ws.send_json({",
            "            scoped = observer.complete_recall(epoch, turn_id, speaker_id, result)\n            if scoped:\n                await ws.send_json({",
        ),
        ("'context': result[:1800],", "'context': scoped[:640],"),

        (
            "kitty_semantic_reply(request_id, turn_id, speaker_id, query))",
            "kitty_semantic_reply(request_id, turn_id, speaker_id, query,\n                                             observer, epoch))",
        ),
    ]
    for before, after in edits:
        count = source.count(before)
        if count != 1:
            raise ValueError(f"Source mismatch, expected one match, found {count}: {before[:64]!r}")
        source = source.replace(before, after, 1)
    # Replace the legacy fail-closed branch independently of its indentation.
    # A single observed, authorized turn is mandatory before recalling memory.
    branch = re.compile(
        r"(?m)^(?P<indent>[ \\t]*)if[ \\t]+not[ \\t]+kitty_server_verified_speaker_turn[ \\t]*:[ \\t]*\\n"
        r"(?P=indent)[ \\t]+continue[ \\t]*\\n"
    )
    def verified_branch(match):
        indent = match.group("indent")
        return (
            indent + "observer = kitty_speaker_observer\\n"
            + indent + "if observer is None:\\n"
            + indent + "    continue\\n"
            + indent + "epoch = observer.authorized_recall(turn_id, speaker_id, provenance)\\n"
            + indent + "if epoch is None:\\n"
            + indent + "    continue\\n"
        )
    source, replacements = branch.subn(verified_branch, source)
    if replacements != 1:
        raise ValueError(f"Expected one legacy memory guard, found {replacements}")
    # Older deployments differ in indentation/comment spelling on this flag.
    # The real enforcement is the exact observer authorization in the branch.
    source = re.sub(
        r"(?m)^[ \\t]*kitty_server_verified_speaker_turn[ \\t]*=[ \\t]*False[^\\n]*\\n",
        "", source,
    )
    if "kitty_server_verified_speaker_turn" in source:
        raise ValueError("Legacy memory flag remains; gateway not modified")
    ast.parse(source)
    return source

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("gateway", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    original = args.gateway.read_text()
    if ("observer.complete_recall(epoch, turn_id, speaker_id, result)" in original
            and "kitty_server_verified_speaker_turn" not in original):
        print("Already patched; no changes")
        return
    updated = patch(original)
    if args.apply:
        args.gateway.write_text(updated)
        print("Updated and syntax verified:", args.gateway)
    else:
        print("PASS: gateway can be patched safely; no changes made")

if __name__ == "__main__":
    main()
