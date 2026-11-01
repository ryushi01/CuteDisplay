#!/usr/bin/env python3
"""Reversible safety change: disable the rejected live session.update callback.

Preserve public profile, speaker observer, X-vector, and explicit response hint.
Strict count checks. Print-only default; --apply creates rollback copy.
"""
import argparse
import ast
import shutil
from pathlib import Path

OLD = "on_candidate=kitty_candidate_hint)"
NEW = "on_candidate=None)"
def patch(source):
    if source.count(OLD) == 1:
        result = source.replace(OLD, NEW, 1)
    elif source.count(NEW) == 1 and OLD not in source:
        result = source
    else:
        raise ValueError("Unexpected candidate callback layout; unchanged")
    ast.parse(result)
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("gateway", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    old = args.gateway.read_text(encoding="utf-8")
    updated = patch(old)
    if args.apply and updated != old:
        backup = args.gateway.with_name(args.gateway.name + ".pre-live-candidate-disable")
        shutil.copy2(args.gateway, backup)
        args.gateway.write_text(updated, encoding="utf-8")
    print("KITTY_LIVE_CANDIDATE_DISABLED" if args.apply else "KITTY_LIVE_CANDIDATE_PATCH_VALID")

if __name__ == "__main__":
    main()
