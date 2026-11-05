#!/usr/bin/env python3
"""Guarded Ubuntu rollout of Kitty's volatile per-call context.

Run with Kitty idle from the live-sync-build checkout after fetching the
feature branch and pinning FETCH_HEAD:

 git show FETCH_HEAD:server/kitty_gateway_call_ram_rollout_v6.py | python3 - --check
 git show FETCH_HEAD:server/kitty_gateway_call_ram_rollout_v6.py | python3 - --apply

The helper's *source code* is stored in the container, but no conversation
data are written to disk. One private 0600 copy of the original gateway
*source code* is retained only for rollback. No new memory store, SQLite
database, transcript file, logging, firmware or SD operation is introduced.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types

STORE = Path.home() / ".local/state/kitty-v6-call-ram"
ORIGINAL = STORE / "gateway-before-ram.py"
STATE = STORE / "state.json"
MODULE = "kitty_volatile_call_context_v6.py"
MODULE_DST = "/app/backend/" + MODULE


class Refusal(Exception):
    pass


def checked(argv, data=None, *, timeout=30):
    try:
        p = subprocess.run(argv, input=data, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, timeout=timeout,
                           check=False)
    except (OSError, subprocess.SubprocessError):
        raise Refusal("command_failed") from None
    if p.returncode:
        raise Refusal("command_failed")
    return p.stdout


def git_source(ref, name):
    if (not isinstance(name, str) or not name.endswith(".py")
            or "/" in name):
        raise Refusal("invalid_git_filename")
    raw = checked(["git", "show", ref + ":server/" + name], timeout=18)
    if not 1 <= len(raw) <= 110000:
        raise Refusal("invalid_pinned_source")
    try:
        compile(raw.decode("utf-8"), "<kitty-pinned-source>", "exec")
    except (UnicodeError, SyntaxError):
        raise Refusal("invalid_pinned_python") from None
    return raw


def components():
    sha = checked(["git", "rev-parse", "--verify", "FETCH_HEAD"]).decode("ascii").strip()
    if len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
        raise Refusal("fetch_head_not_pinned")
    guard = types.ModuleType("kitty_verified_bind_helpers")
    guard.__file__ = "<stdin>"
    exec(compile(git_source(sha, "kitty_gateway_bind_rollout_v6.py"),
                 "<approved-bind-helpers>", "exec"), guard.__dict__)
    patcher = types.ModuleType("kitty_guarded_ram_patcher")
    exec(compile(git_source(sha, "kitty_gateway_call_ram_patch_v6.py"),
                 "<approved-ram-patcher>", "exec"), patcher.__dict__)
    helper = git_source(sha, MODULE)
    return guard, patcher, helper


def source_metadata(g):
    if g.health() != "healthy":
        raise Refusal("open_webui_unhealthy")
    path = g.mounted_host_source()
    meta = g.verified_host_stat(path)
    original = g.source_in_container()
    if g.sha(original) != meta["sha"]:
        raise Refusal("host_container_source_conflict")
    if len(original) > 2_000_000:
        raise Refusal("gateway_source_too_large")
    return path, meta, original


def helper_inventory(g):
    # Only an allowlisted path and SHA are inspected; no helper or transcript
    # content can be printed to the operator.
    probe = (
        "import hashlib\nfrom pathlib import Path\n"
        f"p=Path({MODULE_DST!r})\n"
        "print('unsafe' if p.is_symlink() or (p.exists() and not p.is_file())"
        " else hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file()"
        " else 'absent')\n"
    )
    result = g.docker("exec", g.CONTAINER, "python3", "-c", probe,
                      timeout=15).decode("ascii").strip()
    if result != "absent" and (result == "unsafe"
                                 or len(result) != 64
                                 or any(c not in "0123456789abcdef" for c in result)):
        raise Refusal("helper_file_unsafe")
    return result


def preflight(g, patcher, helper, *, allow_installed=False):
    path, meta, original = source_metadata(g)
    if STATE.exists() and not allow_installed:
        raise Refusal("previous_ram_rollout_exists")
    try:
        candidate = patcher.patch(original.decode("utf-8")).encode("utf-8")
    except (UnicodeError, ValueError, SyntaxError, TypeError):
        raise Refusal("live_gateway_ast_incompatible") from None
    if candidate == original or g.sha(candidate) == g.sha(original):
        raise Refusal("unchanged_candidate")
    inventory = helper_inventory(g)
    if inventory not in ("absent", g.sha(helper)):
        raise Refusal("ram_module_version_conflict")
    g.preflight_host_writable(path, meta)
    return path, meta, original, candidate, inventory


def safe_store():
    if STORE.is_symlink() or ORIGINAL.is_symlink() or STATE.is_symlink():
        raise Refusal("state_symlink")
    STORE.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(STORE, 0o700)


def copy_helper(g, helper):
    with tempfile.TemporaryDirectory(prefix="ram-module-", dir=STORE) as folder:
        src = Path(folder) / MODULE
        with src.open("xb") as fp:
            os.chmod(src, 0o600)
            fp.write(helper)
        g.docker("cp", str(src), g.CONTAINER + ":" + MODULE_DST, timeout=35)
    if helper_inventory(g) != g.sha(helper):
        raise Refusal("container_helper_sha_mismatch")
    g.docker("exec", "-w", "/app/backend", g.CONTAINER, "python3", "-c",
             "from kitty_volatile_call_context_v6 import VolatileCallContext\n"
             "assert VolatileCallContext().buffered_turns == 0\n",
             timeout=18)


def remove_created_helper(g, expected):
    if helper_inventory(g) != expected:
        return
    program = (
        "import hashlib\nfrom pathlib import Path\n"
        f"p=Path({MODULE_DST!r})\n"
        f"assert p.is_file() and not p.is_symlink() and "
        f"hashlib.sha256(p.read_bytes()).hexdigest()=={expected!r}\n"
        "p.unlink()\n"
    )
    g.docker("exec", "--user", "0", g.CONTAINER, "python3", "-c",
             program, timeout=15)


def install():
    g, patcher, helper = components()
    path, meta, original, candidate, inventory = preflight(g, patcher, helper)
    safe_store()
    # Only the original gateway *code*, never memory data, is retained.
    if ORIGINAL.exists() or STATE.exists():
        raise Refusal("previous_ram_rollout_exists")
    g.file_copy_private(ORIGINAL, original)
    g.atomic_private(STATE, json.dumps({
        "status":"prepared", "source":path, "meta":meta,
        "before":g.sha(original), "after":g.sha(candidate),
        "module":g.sha(helper), "module_created":inventory=="absent"
    }, sort_keys=True).encode())
    created = False
    stopped = False
    try:
        if inventory == "absent":
            copy_helper(g, helper)
            created = True
        # Recheck live bind and full bytes before taking the call backend down.
        if g.mounted_host_source() != path or g.source_in_container() != original:
            raise Refusal("gateway_changed_during_preflight")
        print("preflight=passed", flush=True)
        g.docker("stop", g.CONTAINER, timeout=75)
        stopped = True
        if g.state() != "exited":
            raise Refusal("container_not_stopped")
        g.root_write(path, candidate, g.sha(original), meta)
        g.docker("start", g.CONTAINER, timeout=75)
        stopped = False
        if not g.wait_healthy():
            raise Refusal("gateway_health_failed_after_restart")
        if (g.sha(g.source_in_container()) != g.sha(candidate)
                or g.verified_host_stat(path)["sha"] != g.sha(candidate)):
            raise Refusal("gateway_content_verification_failed")
        g.atomic_private(STATE, json.dumps({
            "status":"installed", "source":path, "meta":meta,
            "before":g.sha(original), "after":g.sha(candidate),
            "module":g.sha(helper), "module_created":created
        }, sort_keys=True).encode())
        print("gateway_health=healthy", flush=True)
        print("live_call_ram_context=installed", flush=True)
        print("call_memory_storage=volatile_ram_only", flush=True)
        print("durable_memory_authority=S3_microSD", flush=True)
        print("speaker_private_recall=unchanged_disabled", flush=True)
        print("audio_firmware_sd=unchanged", flush=True)
    except Exception:
        print("install_error=rollback_attempted", flush=True)
        # A partial in-place write, unexpected module error or a bad startup
        # must not overwrite any unrelated source change.
        try:
            if g.state() != "exited":
                g.docker("stop", g.CONTAINER, timeout=75)
            g.recover_partial_write(path, original, candidate, meta)
            g.docker("start", g.CONTAINER, timeout=75)
            if not g.wait_healthy():
                raise Refusal("rollback_container_unhealthy")
            if created:
                remove_created_helper(g, g.sha(helper))
            g.atomic_private(STATE, json.dumps({
                "status":"rolled_back", "source":path,
                "before":g.sha(original), "module_created":created
            }, sort_keys=True).encode())
            print("rollback=completed", flush=True)
        except Exception:
            try:
                if g.state() == "exited":
                    g.docker("start", g.CONTAINER, timeout=75)
            except Exception:
                pass
            print("rollback=requires_manual_review", flush=True)
        raise Refusal("ram_rollout_failed") from None


def inspect():
    g, patcher, helper = components()
    preflight(g, patcher, helper)
    print("KITTY_V6_RAM_CONTEXT_PREFLIGHT", flush=True)
    print("gateway=healthy", flush=True)
    print("gateway_hook=compatible", flush=True)
    print("source_bind=readonly_verified", flush=True)
    print("private_memory=not_enabled", flush=True)
    print("changes=none", flush=True)


def rollback():
    g, _, _ = components()
    if not STATE.is_file() or STATE.is_symlink() or not ORIGINAL.is_file():
        raise Refusal("no_valid_installation")
    try:
        record = json.loads(STATE.read_text())
    except (OSError, ValueError):
        raise Refusal("invalid_installed_state") from None
    if record.get("status") != "installed":
        raise Refusal("not_installed")
    path, meta = record["source"], record["meta"]
    if g.mounted_host_source() != path:
        raise Refusal("mount_source_changed")
    original = ORIGINAL.read_bytes()
    if g.sha(original) != record["before"]:
        raise Refusal("original_source_hash_changed")
    current = g.source_in_container()
    if g.sha(current) != record["after"]:
        raise Refusal("current_gateway_changed")
    if g.verified_host_stat(path)["sha"] != record["after"]:
        raise Refusal("host_gateway_changed")
    g.docker("stop", g.CONTAINER, timeout=75)
    try:
        g.root_write(path, original, record["after"], meta)
    finally:
        g.docker("start", g.CONTAINER, timeout=75)
    if not g.wait_healthy():
        raise Refusal("rollback_health_failed")
    if record.get("module_created") is True:
        remove_created_helper(g, record["module"])
    record["status"] = "rolled_back"
    g.atomic_private(STATE, json.dumps(record, sort_keys=True).encode())
    print("rollback=completed", flush=True)
    print("gateway_health=healthy", flush=True)


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    try:
        if args.check:
            inspect()
        elif args.apply:
            install()
        else:
            rollback()
    except Refusal as exc:
        print("status=" + str(exc), flush=True)
        raise SystemExit(1) from None
    except Exception:
        print("status=unexpected_local_error", flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
