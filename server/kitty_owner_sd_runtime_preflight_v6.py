#!/usr/bin/env python3
"""Read-only on-host Kitty owner SD receipt readiness diagnostic.

Examines only four explicit deployed Python module files and one fixed
systemd --user service state. Does not import executable services, touch
SQLite or SD snapshots, call the model, read environment variables or
print code, paths, hashes, transcripts or credentials.

On Ubuntu:
  git show FETCH_HEAD:server/kitty_owner_sd_runtime_preflight_v6.py |
    python3 - --server-dir "$HOME/kitty-v6/CuteDisplay/server"

This verifies source files ON DISK. It cannot prove which Python modules the
already running process has in RAM; a restart is not requested or authorized.
"""
import argparse
import ast
from pathlib import Path
import subprocess

TARGETS = (
    "kitty_sd_snapshot_v6.py",
    "kitty_memory_service.py",
    "kitty_owner_sd_receipts_v6.py",
    "kitty_semantic_attribution_v6.py",
    "kitty_sd_semantic_index.py",
)
RECEIPT = "owner_turn_receipts_v6.tsv"
MAX_SOURCE_BYTES = 600_000


def _source(root, filename):
    path = root / filename
    try:
        if (root.is_symlink() or path.is_symlink()
                or not path.is_file()
                or not 0 < path.stat().st_size <= MAX_SOURCE_BYTES):
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _parse(source):
    if source is None:
        return None
    try:
        return ast.parse(source)
    except (SyntaxError, ValueError, TypeError, RecursionError):
        return None


def _functions(tree):
    return {n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _names(tree):
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}


def _strings(tree):
    return {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def _call_uses(tree, name):
    return any(
        isinstance(node, ast.Call)
        and ((isinstance(node.func, ast.Name)
              and node.func.id == name)
             or (isinstance(node.func, ast.Attribute)
                 and node.func.attr == name))
        for node in ast.walk(tree))


def _assign_literal(tree, name):
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == name
                        for t in node.targets)):
            try:
                return ast.literal_eval(node.value)
            except (ValueError, TypeError, SyntaxError, MemoryError):
                return None
    return None


def analyze(server_dir):
    """Closed-label structural report. No files are written or executed."""
    root = Path(server_dir).expanduser()
    source = {name: _source(root, name) for name in TARGETS}
    parsed = {name: _parse(source[name]) for name in TARGETS}
    labels = {
        "deployed_source_files": "present" if all(
            source[name] is not None for name in TARGETS) else "incomplete",
        "deployed_python_syntax": "valid" if all(
            tree is not None for tree in parsed.values()) else "not_verified",
        "snapshot_owner_tenth_file": "not_verified",
        "memory_snapshot_endpoint": "not_verified",
        "signed_owner_receipt_verifier": "not_verified",
        "semantic_owner_attribution": "not_verified",
        "semantic_index_receipt_binding": "not_verified",
        "running_process_module_revision": "not_verified",
        "owner_receipt_signing_keys": "not_checked",
        "owner_sd_receipt_written": "not_verified",
        "live_owner_private_recall": "no",
        "deployment_ready": "no",
    }
    sn = parsed["kitty_sd_snapshot_v6.py"]
    if sn is not None:
        fs = _assign_literal(sn, "FILES")
        classes = {n.name: n for n in sn.body if isinstance(n, ast.ClassDef)}
        receiver = classes.get("SnapshotReceiver")
        methods = (_functions(receiver) if receiver is not None else set())
        if (isinstance(fs, (set, frozenset)) and len(fs) == 10
                and RECEIPT in fs and "conversations.tsv" in fs
                and "finalize" in methods and "chunk" in methods
                and "OWNER_RECEIPT_MAX_FILE" in _names(sn)
                and "snapshot id reused with different content" in _strings(sn)
                and "owner receipt snapshot too large" in _strings(sn)):
            labels["snapshot_owner_tenth_file"] = "supported_on_disk"
    ms = parsed["kitty_memory_service.py"]
    if ms is not None and (
            "SnapshotReceiver" in _names(ms)
            and "queue_semantic_refresh" in _names(ms)
            and _call_uses(ms, "chunk") and _call_uses(ms, "finalize")
            and "/snapshot/finalize" in _strings(ms)):
        labels["memory_snapshot_endpoint"] = "present_on_disk"
    owner = parsed["kitty_owner_sd_receipts_v6.py"]
    if owner is not None and (
            _assign_literal(owner, "VERSION") == "owner-v1"
            and {"read_verified_owner_receipts",
                 "issue_provisional_owner_receipt",
                 "_archive_question", "_mac"} <= _functions(owner)
            and "conversations.tsv" in _strings(owner)
            and RECEIPT in _strings(owner)
            and _call_uses(owner, "compare_digest")):
        labels["signed_owner_receipt_verifier"] = "present_on_disk"
    attr = parsed["kitty_semantic_attribution_v6.py"]
    if attr is not None and (
            "iter_archive_with_speakers" in _functions(attr)
            and _call_uses(attr, "read_verified_owner_receipts")
            and "session_verified" in _strings(attr)
            and "person:owner" in _strings(attr)):
        labels["semantic_owner_attribution"] = "present_on_disk"
    idx = parsed["kitty_sd_semantic_index.py"]
    if idx is not None and (
            "build" in _functions(idx)
            and _call_uses(idx, "iter_archive_with_speakers")
            and _call_uses(idx, "configured_receipt_secret")
            and "owner_receipt_key_id" in _strings(idx)):
        labels["semantic_index_receipt_binding"] = "present_on_disk"
    return labels


def service_status():
    """Only ask for fixed unit status; never print systemctl config/env."""
    try:
        p = subprocess.run(
            ["systemctl", "--user", "is-active", "kitty-memory-v6.service"],
            capture_output=True, timeout=3, check=False, text=True)
    except (OSError, subprocess.SubprocessError):
        return "not_verified"
    return "active" if p.returncode == 0 and p.stdout.strip() == "active" else (
        "inactive_or_unavailable")


def main(argv=None):
    ap = argparse.ArgumentParser(description="read-only owner SD readiness")
    ap.add_argument("--server-dir", required=True)
    opts = ap.parse_args(argv)
    status = analyze(opts.server_dir)
    print("KITTY_V6_OWNER_SD_RUNTIME_READ_ONLY")
    for k, v in status.items():
        print(k + "=" + v)
    print("kitty_memory_user_service=" + service_status())
    print("No gateway, service, archive, snapshot, firmware, key or setting changed.")


if __name__ == "__main__":
    main()
