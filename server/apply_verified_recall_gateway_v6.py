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
            "kitty_semantic_reply(request_id, turn_id, speaker_id, query,\n                                             kitty_speaker_observer, epoch))",
        ),
    ]
    for before, after in edits:
        count = source.count(before)
        if count != 1:
            raise ValueError(f"Source mismatch, expected one match, found {count}: {before[:64]!r}")
        source = source.replace(before, after, 1)
    guard = "                    # Schedule CPU/HTTP recall separately: never pause the"
    if source.count(guard) != 1:
        raise ValueError("Semantic request handler differs from inspected gateway")
    source = source.replace(
        guard,
        "                    observer = kitty_speaker_observer\n"
        "                    if observer is None:\n"
        "                        continue\n"
        "                    epoch = observer.authorized_recall(turn_id, speaker_id, provenance)\n"
        "                    if epoch is None:\n"
        "                        continue\n"
        + guard, 1)
    callback_start = source.find("        async def kitty_speaker_sink(event):")
    callback_end = source.find("        kitty_speaker_observer = None", callback_start)
    if callback_start < 0 or callback_end < 0:
        raise ValueError("Speaker result callback not found")
    callback = source[callback_start:callback_end]
    log_end = "                ), flush=True)"
    if callback.count(log_end) != 1:
        raise ValueError("Speaker result callback structure differs")
    callback = callback.replace(log_end,
                                log_end + "\n                await ws.send_json(event)", 1)
    source = source[:callback_start] + callback + source[callback_end:]
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
