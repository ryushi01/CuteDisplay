#!/usr/bin/env python3
"""One-command, fail-closed deployment of Kitty V6 *private semantic* owner guard.

Use after fetching main:
    git show FETCH_HEAD:server/kitty_owner_guard_deploy_v6.py | python3 - --apply

Only the two private semantic HTTP handler branches in the RUNNING user memory
service are replaced. Missing pure-Python helper modules are copied next to
that service; installed helpers are never overwritten. No firmware, S3 SD,
Open WebUI/Docker gateway, speaker profiles, audio or AI/TTS files are changed.
Backups and automatic rollback protect the existing service. No secrets,
private source, service arguments or responses are printed.

Owner presence is NOT per-spoken-turn verification; this patch intentionally
denies private semantic requests without a valid independently issued grant.
"""
import argparse
import ast
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import types

SERVICE_NAME = "kitty-memory-v6.service"
REPO_PREFIX = "server/"
REQUIRED = ("kitty_semantic_authorization_v6.py",
            "kitty_memory_context_v6.py")
EXISTING = (("kitty_owner_session_v6.py", "verify_grant"),
            ("kitty_sd_semantic_index.py", "search"))
STATE_DIR = Path.home() / ".local" / "state" / "kitty-v6-owner-guard"


class DeploymentError(Exception):
    pass


def command(args, timeout=20):
    try:
        p = subprocess.run(args, capture_output=True, text=True,
                           check=False, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise DeploymentError("command_failed") from None
    if p.returncode != 0:
        raise DeploymentError("command_failed")
    return p.stdout


def git_source(path):
    value = command(["git", "show", "FETCH_HEAD:" + REPO_PREFIX + path],
                    timeout=10)
    if not value or len(value) > 100000:
        raise DeploymentError("github_file_unavailable")
    compile(value, "<trusted-github-source>", "exec")
    return value


def load_plan():
    # The checkout may be detached and older than FETCH_HEAD, so import from
    # exactly the fetched commit rather than the local worktree.
    source = git_source("kitty_owner_guard_plan_v6.py")
    module = types.ModuleType("kitty_guard_plan_from_fetch_head")
    exec(compile(source, "<owner-guard-plan>", "exec"), module.__dict__)
    return module


def build_candidate(old, target, plan):
    """Replace only the exact adjacent AST branches. Refuse modified layouts."""
    if plan.candidate(old, target) != "yes":
        raise DeploymentError("source_incompatible")
    oldtree, oldlayout = plan._topology(old)
    newtree, newlayout = plan._topology(target)
    if oldlayout != "split" or newlayout != "combined":
        raise DeploymentError("source_incompatible")
    first, second = plan._sibling_pairs(oldtree)[0]
    modern = next(n for n in ast.walk(newtree)
                  if plan._route(n) == "combined")
    original = old.splitlines(keepends=True)
    incoming = target.splitlines(keepends=True)
    result = ("".join(original[:first.lineno-1])
              + "".join(incoming[modern.lineno-1:modern.end_lineno])
              + "".join(original[second.end_lineno:]))
    compile(result, "<owner-guard-candidate>", "exec")
    if plan._topology(result)[1] != "combined":
        raise DeploymentError("candidate_invalid")
    if result.count("authorized_semantic_speaker(data,OWNER_PROOF)") != 1:
        raise DeploymentError("candidate_invalid")
    return result


def sha(value):
    return hashlib.sha256(value).hexdigest()


def as_source_bytes(text):
    return text.encode("utf-8")


def atomic_write(path, data, mode=0o644):
    if path.is_symlink():
        raise DeploymentError("symlink_refused")
    fd, temp = tempfile.mkstemp(prefix=".kitty_owner_guard_tmp_", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def service_state():
    raw = command(["systemctl", "--user", "show", SERVICE_NAME,
                   "-p", "MainPID", "-p", "ActiveState"], timeout=8)
    data = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
    pid = data.get("MainPID", "0")
    return data.get("ActiveState") == "active", int(pid) if pid.isdecimal() else 0


def healthy():
    try:
        conn = http.client.HTTPConnection("127.0.0.1", 8766, timeout=2)
        try:
            conn.request("GET", "/health")
            response = conn.getresponse()
            body = response.read(512)
            return response.status == 200 and json.loads(body).get("ok") is True
        finally:
            conn.close()
    except (OSError, ValueError, TypeError, http.client.HTTPException):
        return False


def wait_healthy(attempts=12):
    for _ in range(attempts):
        try:
            active, pid = service_state()
            if active and pid > 0 and healthy():
                return pid
        except DeploymentError:
            pass
        time.sleep(0.5)
    return 0


def process_token(pid):
    """Read the server's own token without logging, storing or shell exposure."""
    if not pid:
        return None
    try:
        values = (Path("/proc") / str(pid) / "environ").read_bytes().split(bytes([0]))
        found = [v.partition(b"=")[2] for v in values
                 if v.startswith(b"KITTY_MEMORY_TOKEN=")]
        if len(found) != 1 or not 1 <= len(found[0]) <= 8192:
            return None
        return found[0].decode("utf-8")
    except (OSError, UnicodeError, ValueError):
        return None


def private_routes_deny_unverified(token):
    """Real localhost HTTP 403 check, with no semantic DB read and no secrets output."""
    if not isinstance(token, str) or not token:
        return False
    body = json.dumps({"speaker_id": "person:owner",
                       "session_id": "deployment-unverified-session",
                       "owner_grant": "NOT-A-GRANT",
                       "query": "authorization-check"}).encode("utf-8")
    for route in ("/semantic", "/semantic/context"):
        try:
            conn = http.client.HTTPConnection("127.0.0.1", 8766, timeout=2)
            try:
                conn.request("POST", route, body=body, headers={
                    "Authorization": "Bearer " + token,
                    "Content-Type": "application/json"})
                response = conn.getresponse()
                response.read(512)
                if response.status != 403:
                    return False
            finally:
                conn.close()
        except (OSError, ValueError, http.client.HTTPException):
            return False
    return True


def valid_function(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
               and node.name == name for node in tree.body)


def offline_security_smoke(candidate_source, service_directory):
    """Validate both route handlers with a synthetic bearer; no server activity."""
    sys.path.insert(0, str(service_directory))
    try:
        import importlib
        for module in ("kitty_semantic_authorization_v6",
                       "kitty_owner_session_v6"):
            sys.modules.pop(module, None)
        importlib.invalidate_caches()
        auth = importlib.import_module("kitty_semantic_authorization_v6")
        session = importlib.import_module("kitty_owner_session_v6")
        key = bytes([73]) * 32
        sid = "trusted-deployment-session-100"
        grant = session.issue_grant(key, True, sid, ttl=30)
        owner = types.SimpleNamespace(secret=key)
        if auth.authorized_semantic_speaker(
                {"speaker_id": "person:owner", "session_id": sid,
                 "owner_grant": grant}, owner) != "person:owner":
            raise DeploymentError("offline_auth_failed")
        if auth.authorized_semantic_speaker(
                {"speaker_id": "person:guest", "session_id": sid,
                 "owner_grant": grant}, owner) is not None:
            raise DeploymentError("offline_auth_failed")
        module = types.ModuleType("kitty_memory_service_offline_check")
        exec(compile(candidate_source, "<memory-service-offline>", "exec"),
             module.__dict__)
        module.TOKEN = "_KITTY_LOCAL_SMOKE_ONLY_"
        module.OWNER_PROOF = owner
        for endpoint in ("/semantic", "/semantic/context"):
            for payload in (
                {"speaker_id": "person:owner", "query": "private",
                 "session_id": sid, "owner_grant": "invalid"},
                {"speaker_id": "person:guest", "query": "private",
                 "session_id": sid, "owner_grant": grant},
                {"speaker_id": "person:owner", "query": "private"},
            ):
                request = object.__new__(module.Handler)
                request.path = endpoint
                request.headers = {"Authorization": "Bearer " + module.TOKEN,
                                   "Content-Length": str(len(json.dumps(payload).encode()))}
                request.rfile = io.BytesIO(json.dumps(payload).encode())
                request._reply = lambda status, data: status
                if request.do_POST() != 403:
                    raise DeploymentError("offline_route_failed")
        return True
    except (OSError, ValueError, SyntaxError, ImportError, TypeError,
            AttributeError) as exc:
        raise DeploymentError("offline_auth_failed") from None
    finally:
        sys.path.pop(0)
        for mod in ("kitty_semantic_authorization_v6", "kitty_owner_session_v6"):
            sys.modules.pop(mod, None)


def state_file():
    return STATE_DIR / "last-deployment.json"


def create_backup(service_path, old_bytes, created, new_bytes, modules):
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(STATE_DIR, 0o700)
    if state_file().exists():
        previous = json.loads(state_file().read_text())
        if previous.get("status") == "installed":
            raise DeploymentError("existing_deployment_backup")
    leaf = "backup-" + str(time.time_ns())
    folder = STATE_DIR / leaf
    folder.mkdir(mode=0o700)
    original = folder / "kitty_memory_service.py"
    atomic_write(original, old_bytes, 0o600)
    data = {"service_path": str(service_path.resolve()),
            "backup": str(original.resolve()),
            "before_sha": sha(old_bytes),
            "after_sha": sha(new_bytes),
            "created": created,
            "module_sha": {name: sha(as_source_bytes(modules[name])) for name in created},
            "status": "prepared"}
    write_state(data)
    return data


def write_state(data):
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_write(state_file(), json.dumps(data, sort_keys=True).encode(), 0o600)


def restore_original(data, *, strict=True):
    """Restore only our exact candidate and helpers, not later user changes."""
    target = Path(data["service_path"])
    saved = Path(data["backup"])
    if not saved.is_file() or target.is_symlink():
        raise DeploymentError("rollback_backup_unavailable")
    if strict and (not target.is_file()
                   or sha(target.read_bytes()) != data["after_sha"]):
        raise DeploymentError("rollback_conflicting_changes")
    original = saved.read_bytes()
    if sha(original) != data["before_sha"]:
        raise DeploymentError("rollback_backup_corrupt")
    mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else 0o644
    atomic_write(target, original, mode)
    for module in data["created"]:
        path = target.parent / module
        if path.is_file() and not path.is_symlink():
            if sha(path.read_bytes()) == data["module_sha"][module]:
                path.unlink()
    data["status"] = "rolled_back"
    write_state(data)


def restart():
    command(["systemctl", "--user", "restart", SERVICE_NAME], timeout=25)


def rollback():
    if not state_file().exists():
        raise DeploymentError("rollback_backup_unavailable")
    data = json.loads(state_file().read_text())
    if data.get("status") != "installed":
        raise DeploymentError("no_active_deployment")
    restore_original(data, strict=True)
    restart()
    if not wait_healthy():
        raise DeploymentError("rollback_service_unhealthy")
    print("rollback=completed")
    print("memory_health=ok")


def apply():
    plan = load_plan()
    service_path = plan.live_service_source()
    if not service_path or service_path.is_symlink():
        raise DeploymentError("live_service_not_identified")
    active, pid = service_state()
    if not active or pid <= 0 or not healthy():
        raise DeploymentError("predeploy_service_not_healthy")
    token = process_token(pid)
    if token is None:
        raise DeploymentError("service_token_unreadable")
    original_bytes = service_path.read_bytes()
    original = original_bytes.decode("utf-8")
    upstream = git_source("kitty_memory_service.py")
    candidate_source = build_candidate(original, upstream, plan)
    original_mode = stat.S_IMODE(service_path.stat().st_mode)
    modules = {}
    created = []
    for name, function in EXISTING:
        path = service_path.parent / name
        if (not path.is_file() or path.is_symlink()
                or not valid_function(path, function)):
            raise DeploymentError("existing_dependency_incompatible")
    for name in REQUIRED:
        desired = git_source(name)
        path = service_path.parent / name
        if path.exists() or path.is_symlink():
            if not path.is_file() or path.read_text(encoding="utf-8") != desired:
                raise DeploymentError("existing_dependency_different")
        else:
            created.append(name)
        modules[name] = desired

    # Never overwrite an in-flight previous backup transaction.
    data = create_backup(service_path, original_bytes, created,
                         as_source_bytes(candidate_source), modules)
    changed = False
    print("backup=created")
    try:
        for name in created:
            atomic_write(service_path.parent / name,
                         as_source_bytes(modules[name]), 0o644)
        atomic_write(service_path, as_source_bytes(candidate_source),
                     original_mode)
        changed = True
        offline_security_smoke(candidate_source, service_path.parent)
        print("offline_private_guard=passed")
        restart()
        new_pid = wait_healthy()
        if not new_pid:
            raise DeploymentError("service_unhealthy_after_restart")
        after_token = process_token(new_pid)
        if not private_routes_deny_unverified(after_token):
            raise DeploymentError("private_403_failed")
        data["status"] = "installed"
        write_state(data)
        print("deployment=completed")
        print("memory_health=ok")
        print("private_semantic_403=verified")
        print("shared_audio_gateway=unchanged")
    except Exception:
        # Even if an error occurs before the primary file replacement, restore
        # the original and remove only exact helper bytes created by this run.
        try:
            if changed or service_path.read_bytes() != original_bytes:
                restore_original(data, strict=False)
            else:
                for name in created:
                    path = service_path.parent / name
                    if path.is_file() and sha(path.read_bytes()) == sha(
                            as_source_bytes(modules[name])):
                        path.unlink()
                data["status"] = "rolled_back"
                write_state(data)
            restart()
            recovered = bool(wait_healthy())
            print("rollback=" + ("completed" if recovered else "service_check_failed"))
        except Exception:
            print("rollback=manual_recovery_required")
        raise DeploymentError("deployment_failed_rolled_back") from None


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--apply", action="store_true")
    group.add_argument("--rollback", action="store_true")
    options = parser.parse_args()
    print("KITTY_V6_PRIVATE_OWNER_GUARD_DEPLOY")
    try:
        if options.apply:
            apply()
        else:
            rollback()
    except (DeploymentError, OSError, ValueError, UnicodeError, SyntaxError,
            PermissionError, KeyError, json.JSONDecodeError) as exc:
        # Do not print exceptions which could expose a path or source.
        label = str(exc) if isinstance(exc, DeploymentError) else "unexpected_error"
        if label not in {
            "source_incompatible", "candidate_invalid", "github_file_unavailable",
            "command_failed", "live_service_not_identified",
            "predeploy_service_not_healthy", "service_token_unreadable",
            "existing_dependency_incompatible", "existing_dependency_different",
            "existing_deployment_backup", "rollback_backup_unavailable",
            "rollback_conflicting_changes", "rollback_backup_corrupt",
            "no_active_deployment", "rollback_service_unhealthy",
            "deployment_failed_rolled_back", "unexpected_error"}:
            label = "unexpected_error"
        print("deployment_error=" + label)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
