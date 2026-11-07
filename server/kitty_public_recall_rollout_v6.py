#!/usr/bin/env python3
"""Guarded Ubuntu rollout of approved-only Kitty V6 cross-call recall.

Run with Kitty idle from the live-sync-build git checkout:
    git fetch -q origin main
    git show FETCH_HEAD:server/kitty_public_recall_rollout_v6.py | python3 - --check
    git show FETCH_HEAD:server/kitty_public_recall_rollout_v6.py | python3 - --apply

Changes TWO existing Ubuntu memory service Python sources plus TWO container
helper sources; it does not change the private realtime.py route, iPhone,
ESP32 firmware, C5 Bluetooth, SD card or historical owner classification.

--check reads allowlisted bytes and flags only.
--apply requires byte-for-byte known baseline and a healthy service/container,
backs up exact originals (0600), restarts service/container once, and restores
both on any failure. --rollback restores the exact original files only if
all deployed sources still match this transaction; never overwrite a custom
change. No user memories, auth tokens or transcripts are copied or logged.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time

BASE_HOST = "ea14ea1b585fb4af356d2c7971238086f5ab4a9c"
BASE_CONTAINER = "754cb8a0cceea51d90eb80b6cd58da4536a4ff80"
HOST_ROOT = Path.home() / "kitty-v6/CuteDisplay/server"
HOST_FILES = ("kitty_memory_service.py", "kitty_shareable_memory_v6.py")
CONTAINER_BASE = "/app/backend/"
CONTAINER_FILES = ("kitty_response_bound_call_context_v6.py",
                   "kitty_approved_live_query_v6.py")
ROUTE = "/app/backend/open_webui/routers/audio/realtime.py"
SERVICE = "kitty-memory-v6.service"
CONTAINER = "open-webui"
STORE = Path.home() / ".local/state/kitty-v6-approved-crosscall"
MANIFEST = STORE / "state.json"


class Refusal(RuntimeError):
    pass


def checksum(data):
    return hashlib.sha256(data).hexdigest()


def command(args, *, timeout=75):
    try:
        p = subprocess.run(args, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        raise Refusal("command_unavailable") from None
    if p.returncode:
        raise Refusal("command_failed")
    return p.stdout


def git_file(ref, name):
    if (not isinstance(ref, str) or len(ref) != 40 or
            any(x not in "0123456789abcdef" for x in ref)
            or not name.endswith(".py") or "/" in name):
        raise Refusal("invalid_pinned_source")
    data = command(["git", "show", ref + ":server/" + name], timeout=20)
    if not 1 <= len(data) <= 100000:
        raise Refusal("missing_pinned_source")
    try:
        compile(data, "<pinned-kitty-module>", "exec")
    except SyntaxError:
        raise Refusal("invalid_pinned_python") from None
    return data


def pinned_sha():
    value = command(["git", "rev-parse", "--verify", "FETCH_HEAD"],
                    timeout=12).decode().strip()
    if len(value) != 40 or any(c not in "0123456789abcdef" for c in value):
        raise Refusal("git_fetch_head_invalid")
    return value


def docker(*args, timeout=75):
    return command(["sudo", "docker", *args], timeout=timeout)


def container_bytes(name, *, optional=False):
    if name not in CONTAINER_FILES:
        raise Refusal("container_module_not_allowlisted")
    path = CONTAINER_BASE + name
    program = (
        "import pathlib,stat,sys\n"
        f"p=pathlib.Path({path!r})\n"
        "if not p.exists() and not p.is_symlink():\n"
        " sys.exit(2)\n"
        "info=p.lstat()\n"
        "if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:\n"
        " sys.exit(3)\n"
        "sys.stdout.buffer.write(p.read_bytes())\n")
    try:
        return docker("exec", CONTAINER, "python3", "-c", program, timeout=20)
    except Refusal:
        if not optional:
            raise
        # Distinguish missing helper from unreadable/conflicting file using
        # a separate metadata-only check (never print its content).
        check = (
            "from pathlib import Path\n"
            f"p=Path({path!r})\n"
            "print('absent' if not p.exists() and not p.is_symlink() "
            "else 'present')\n")
        if docker("exec", CONTAINER, "python3", "-c", check,
                  timeout=15).strip() == b"absent":
            return None
        raise Refusal("container_file_conflict")


def gateway_ok():
    program = (
        "from pathlib import Path\n"
        f"s=Path({ROUTE!r}).read_text(encoding='utf-8')\n"
        "ok=all(x in s for x in ("
        "'KITTY_V6_RESPONSE_BOUND_CALL_CONTEXT_V6',"
        "'KITTY_SHARED_CONTEXT_PERSIST_RESPONSE_V6'))\n"
        "ok=ok and 'KITTY_V6_CALL_RAM_ONLY_HOOK' not in s\n"
        "print('yes' if ok else 'no')\n")
    return docker("exec", CONTAINER, "python3", "-c", program,
                  timeout=15).strip() == b"yes"


def public_endpoint_ok():
    # Exact configured URL and bearer are never printed.
    program = (
        "import os\n"
        "from urllib.parse import urlsplit\n"
        "import posixpath\n"
        "u=os.environ.get('KITTY_SEMANTIC_SERVICE_URL','')\n"
        "t=os.environ.get('KITTY_MEMORY_TOKEN','')\n"
        "try:\n"
        " p=urlsplit(u)\n"
        " ok=((p.scheme=='http' and p.hostname=='127.0.0.1' "
        "and p.port is not None and 0<p.port<=65535 and "
        "p.path in ('','/') and not p.username and not p.password "
        "and not p.query and not p.fragment) or\n"
        " (p.scheme=='unix' and not p.netloc and not p.query and "
        "not p.fragment and p.path.startswith('/run/kitty-semantic/') "
        "and p.path==posixpath.normpath(p.path) "
        "and not any(c in p.path for c in ('%','\\\\','\\x00'))))\n"
        "except ValueError:\n"
        " ok=False\n"
        "print('yes' if ok and bool(t) else 'no')\n"
    )
    return docker("exec", CONTAINER, "python3", "-c", program,
                  timeout=15).strip() == b"yes"


def container_health():
    return docker("inspect", "-f", "{{.State.Health.Status}}", CONTAINER,
                  timeout=15).decode().strip()


def wait_health():
    for _ in range(35):
        if container_health() == "healthy":
            return True
        time.sleep(2)
    return False


def service_active():
    return command(["systemctl", "--user", "is-active", SERVICE],
                   timeout=15).strip() == b"active"


def service_source_verified():
    pid = command(["systemctl", "--user", "show", SERVICE, "-p",
                   "MainPID", "--value"], timeout=15).decode().strip()
    if not pid.isdecimal() or int(pid) <= 1:
        return False
    try:
        args = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False
    return b"kitty_memory_service.py" in args


def host_bytes(name):
    if name not in HOST_FILES:
        raise Refusal("host_module_not_allowlisted")
    path = HOST_ROOT / name
    if path.is_symlink() or not path.is_file():
        raise Refusal("host_module_missing_or_symlink")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
        raise Refusal("host_module_owner_or_link_conflict")
    return path.read_bytes(), stat.S_IMODE(info.st_mode)


def safe_store():
    if STORE.is_symlink() or MANIFEST.is_symlink() or MANIFEST.exists():
        raise Refusal("previous_transaction_present")
    STORE.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(STORE, 0o700)
    if any(STORE.iterdir()):
        raise Refusal("previous_transaction_present")


def atomic_file(path, data, mode):
    if path.is_symlink():
        raise Refusal("target_is_symlink")
    fd, temp = tempfile.mkstemp(prefix=".kitty-public-", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def backup(name, data):
    target = STORE / name
    if target.exists() or target.is_symlink():
        raise Refusal("backup_conflict")
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def safe_state(payload):
    atomic_file(MANIFEST, json.dumps(payload, sort_keys=True).encode(), 0o600)


def deploy_container(name, content):
    if name not in CONTAINER_FILES:
        raise Refusal("container_module_not_allowlisted")
    with tempfile.TemporaryDirectory(prefix=".kitty-module-", dir=STORE) as d:
        local = Path(d) / name
        local.write_bytes(content)
        local.chmod(0o600)
        docker("cp", str(local), CONTAINER + ":" + CONTAINER_BASE + name,
               timeout=35)
    if container_bytes(name) != content:
        raise Refusal("container_copy_verification_failed")


def remove_container(name, expected):
    if name not in CONTAINER_FILES or container_bytes(name) != expected:
        raise Refusal("new_helper_changed")
    p = CONTAINER_BASE + name
    program = (f"from pathlib import Path\np=Path({p!r})\n"
               "assert p.is_file() and not p.is_symlink()\np.unlink()\n")
    docker("exec", "--user", "0", CONTAINER, "python3", "-c", program,
           timeout=15)


def preflight():
    ref = pinned_sha()
    if MANIFEST.exists() or MANIFEST.is_symlink():
        raise Refusal("previous_transaction_present")
    if not service_active() or not service_source_verified():
        raise Refusal("memory_service_not_verified")
    if container_health() != "healthy" or not gateway_ok():
        raise Refusal("working_gateway_not_verified")
    if not public_endpoint_ok():
        raise Refusal("local_memory_endpoint_not_verified")
    old_host, new_host, modes = {}, {}, {}
    for name in HOST_FILES:
        current, mode = host_bytes(name)
        old = git_file(BASE_HOST, name)
        new = git_file(ref, name)
        if current != old:
            raise Refusal("custom_host_module_refused")
        if old == new:
            raise Refusal("host_module_update_missing")
        old_host[name], new_host[name], modes[name] = current, new, mode
    previous = container_bytes(CONTAINER_FILES[0])
    if previous != git_file(BASE_CONTAINER, CONTAINER_FILES[0]):
        raise Refusal("custom_container_helper_refused")
    if container_bytes(CONTAINER_FILES[1], optional=True) is not None:
        raise Refusal("optional_query_helper_conflict")
    new_container = {name: git_file(ref, name) for name in CONTAINER_FILES}
    if new_container[CONTAINER_FILES[0]] == previous:
        raise Refusal("container_update_missing")
    return ref, old_host, new_host, modes, previous, new_container


def apply():
    ref, old_host, new_host, modes, previous, new_container = preflight()
    safe_store()
    for name, data in old_host.items():
        backup(name + ".before", data)
    backup(CONTAINER_FILES[0] + ".before", previous)
    state = {
        "status": "prepared", "ref": ref,
        "host_old": {name: checksum(data) for name, data in old_host.items()},
        "host_new": {name: checksum(data) for name, data in new_host.items()},
        "host_modes": modes,
        "container_old": checksum(previous),
        "container_new": {name: checksum(data)
                          for name, data in new_container.items()},
    }
    safe_state(state)
    changed = False
    try:
        # Revalidate all source bytes after backing up and before first write.
        for name, data in old_host.items():
            if host_bytes(name)[0] != data:
                raise Refusal("host_changed_during_preflight")
        if container_bytes(CONTAINER_FILES[0]) != previous:
            raise Refusal("container_changed_during_preflight")
        for name in HOST_FILES:
            changed = True
            atomic_file(HOST_ROOT / name, new_host[name], modes[name])
        command(["systemctl", "--user", "restart", SERVICE])
        if not service_active() or not service_source_verified():
            raise Refusal("memory_service_restart_failed")
        for name in CONTAINER_FILES:
            changed = True
            deploy_container(name, new_container[name])
        docker("restart", CONTAINER, timeout=90)
        if not wait_health() or not gateway_ok():
            raise Refusal("webui_health_failed")
        if not public_endpoint_ok():
            raise Refusal("public_endpoint_missing_after_restart")
        for name in HOST_FILES:
            if host_bytes(name)[0] != new_host[name]:
                raise Refusal("host_hash_mismatch")
        for name in CONTAINER_FILES:
            if container_bytes(name) != new_container[name]:
                raise Refusal("container_hash_mismatch")
        state["status"] = "installed"
        safe_state(state)
        print("memory_service=active")
        print("open_webui=healthy")
        print("approved_public_query=installed")
        print("voice_gateway_route=unchanged")
        print("owner_private_recall=disabled")
        print("sd_firmware_iphone=unchanged")
    except Exception:
        print("deployment_error=rollback_attempted", flush=True)
        try:
            if changed:
                restore_files(state, expected="partial")
                command(["systemctl", "--user", "restart", SERVICE])
                docker("restart", CONTAINER, timeout=90)
            if not service_active() or not wait_health():
                raise Refusal("rollback_health_failed")
            state["status"] = "rolled_back"
            safe_state(state)
            print("rollback=completed", flush=True)
        except Exception:
            print("rollback=requires_manual_review", flush=True)
        raise Refusal("public_recall_deployment_failed") from None


def restore_files(state, *, expected="installed"):
    for name in HOST_FILES:
        old = (STORE / (name + ".before")).read_bytes()
        if checksum(old) != state["host_old"][name]:
            raise Refusal("host_backup_corrupt")
        current, mode = host_bytes(name)
        target = state["host_new"][name]
        if expected == "installed" and checksum(current) != target:
            raise Refusal("host_modified_since_install")
        if expected == "partial" and checksum(current) not in (
                state["host_old"][name], target):
            raise Refusal("host_conflict_during_recovery")
        atomic_file(HOST_ROOT / name, old, state["host_modes"][name])
    old = (STORE / (CONTAINER_FILES[0] + ".before")).read_bytes()
    if checksum(old) != state["container_old"]:
        raise Refusal("container_backup_corrupt")
    current = container_bytes(CONTAINER_FILES[0])
    if expected == "installed" and checksum(current) != state["container_new"][CONTAINER_FILES[0]]:
        raise Refusal("container_modified_since_install")
    if expected == "partial" and checksum(current) not in (
            state["container_old"], state["container_new"][CONTAINER_FILES[0]]):
        raise Refusal("container_conflict_during_recovery")
    if current != old:
        deploy_container(CONTAINER_FILES[0], old)
    optional = container_bytes(CONTAINER_FILES[1], optional=True)
    if optional is not None:
        if checksum(optional) != state["container_new"][CONTAINER_FILES[1]]:
            raise Refusal("new_helper_changed")
        remove_container(CONTAINER_FILES[1], optional)


def rollback():
    if MANIFEST.is_symlink() or not MANIFEST.is_file():
        raise Refusal("no_installed_transaction")
    try:
        state = json.loads(MANIFEST.read_text())
    except (OSError, ValueError):
        raise Refusal("transaction_state_corrupt") from None
    if state.get("status") != "installed":
        raise Refusal("not_installed")
    if container_health() != "healthy" or not service_active():
        raise Refusal("services_not_healthy")
    restore_files(state, expected="installed")
    command(["systemctl", "--user", "restart", SERVICE])
    docker("restart", CONTAINER, timeout=90)
    if not service_active() or not wait_health() or not gateway_ok():
        raise Refusal("rollback_health_failed")
    state["status"] = "rolled_back"
    safe_state(state)
    print("rollback=completed")
    print("memory_service=active")
    print("open_webui=healthy")


def main():
    p = argparse.ArgumentParser()
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--rollback", action="store_true")
    args = p.parse_args()
    try:
        if args.check:
            preflight()
            print("public_recall_preflight=ready")
            print("gateway_bind=unchanged")
            print("owner_private_recall=disabled")
            print("changes=none")
        elif args.apply:
            apply()
        else:
            rollback()
    except Refusal as exc:
        print("status=" + str(exc))
        raise SystemExit(1) from None
    except Exception:
        print("status=unexpected_local_error")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
