#!/usr/bin/env python3
"""Guarded, one-command Ubuntu Open WebUI passive-hook rollout (host-side).

Run when Kitty is not in a call:
  git fetch origin main
  git show FETCH_HEAD:server/kitty_gateway_passive_rollout_v6.py |
      python3 - --apply

Calls sudo docker only. Makes a private host backup, validates the exact
provider-event JSON-decode AST, preserves all existing WS forwarding, copies
only absent matching source helpers, restarts ONLY open-webui, checks Docker
health, and attempts exact rollback on failure. It does NOT modify the memory
service, SD, C5/S3, Mac AI/TTS, secrets, audio protocol, owner private recall
or automatic voice learning. Unknown gateway layouts are rejected before
modification. No source, transcripts or keys printed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import types

CONTAINER="open-webui"
RUNTIME=Path("/app/backend")
LIVE=Path("/app/backend/open_webui/routers/audio/realtime.py")
TMP=LIVE.with_name(".kitty-v6-provider-passive-candidate.py")
STORE=Path.home()/".local/state/kitty-v6-gateway-passive"
MANIFEST=STORE/"transaction.json"
HELPERS=(
    "kitty_passive_turn_bridge_v6.py",
    "kitty_gateway_turn_adapter_v6.py",
    "kitty_attested_live_call_v6.py",
    "kitty_live_rolling_context_v6.py",
    "kitty_turn_context_v6.py",
    "kitty_semantic_async_client_v6.py",
    "kitty_owner_session_v6.py",
    "kitty_voice_familiarity_hints_v6.py",
)


class DeployRefusal(Exception):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def command(argv, *, data=None, timeout=50):
    try:
        result=subprocess.run(argv,input=data,stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE,timeout=timeout,
                              check=False)
    except (OSError,subprocess.TimeoutExpired):
        raise DeployRefusal("system_command_failed") from None
    if result.returncode:
        raise DeployRefusal("system_command_failed")
    return result.stdout


def git_source(sha_ref, name):
    if (not name.endswith(".py")
            or "/" in name or ".." in name):
        raise DeployRefusal("source_name_invalid")
    raw=command(["git","show",sha_ref+":server/"+name],timeout=12)
    if not 1<=len(raw)<=110000:
        raise DeployRefusal("git_source_missing")
    try:
        compile(raw.decode("utf-8"),"<git-voice-module>","exec")
    except (SyntaxError,UnicodeError):
        raise DeployRefusal("git_source_invalid") from None
    return raw


def docker(*args, timeout=55):
    return command(["sudo","docker",*args],timeout=timeout)


def docker_exec(pycode, *, timeout=25):
    return docker("exec","-w",str(RUNTIME),CONTAINER,
                  "python3","-c",pycode,timeout=timeout)


def get_container_health():
    try:
        return docker("inspect","-f","{{.State.Health.Status}}",
                      CONTAINER,timeout=12).decode("ascii").strip()
    except (UnicodeError,DeployRefusal):
        return "unknown"


def wait_healthy():
    for _ in range(25):
        if get_container_health()=="healthy":
            return True
        time.sleep(2)
    return False


def ensure_store():
    if STORE.is_symlink():
        raise DeployRefusal("state_directory_conflict")
    STORE.mkdir(parents=True,exist_ok=True,mode=0o700)
    if not STORE.is_dir() or STORE.is_symlink():
        raise DeployRefusal("state_directory_conflict")
    os.chmod(STORE,0o700)


def save_manifest(data):
    ensure_store()
    fd,name=tempfile.mkstemp(prefix=".kitty-v6-stage-state-",dir=STORE)
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(json.dumps(data,sort_keys=True).encode())
            f.flush()
            os.fsync(f.fileno())
        os.chmod(name,0o600)
        os.replace(name,MANIFEST)
    finally:
        if os.path.exists(name):os.unlink(name)


def helper_status(names):
    # Return fixed destination hashes only; never read or echo private data.
    check="import json,hashlib,stat\nfrom pathlib import Path\n"
    check+="names="+repr(tuple(names))+"\n"
    check+="root=Path('/app/backend')\n"
    check+="out={}\n"
    check+="for name in names:\n"
    check+=" p=root/name\n"
    check+=" if p.is_symlink():out[name]='symlink'\n"
    check+=" elif p.is_file():out[name]=hashlib.sha256(p.read_bytes()).hexdigest()\n"
    check+=" elif p.exists():out[name]='nonfile'\n"
    check+=" else:out[name]=None\n"
    check+="print(json.dumps(out))\n"
    try:
        values=json.loads(docker_exec(check,timeout=15).decode("utf-8"))
    except (UnicodeError,ValueError):
        raise DeployRefusal("container_module_check_failed") from None
    if set(values)!=set(names):
        raise DeployRefusal("container_module_check_failed")
    return values


def target_status():
    # Only fixed checksum and metadata; never emit private gateway source.
    code="from pathlib import Path\nimport hashlib\n"
    code+=f"p=Path({str(LIVE)!r})\n"
    code+="assert p.is_file() and not p.is_symlink()\n"
    code+="print(hashlib.sha256(p.read_bytes()).hexdigest())\n"
    try:
        return docker_exec(code,timeout=12).decode("ascii").strip()
    except (UnicodeError,DeployRefusal):
        raise DeployRefusal("gateway_source_changed") from None


def move_candidate(expect_before, expect_after):
    # Atomic replacement only; a bind-mounted single file is rejected rather
    # than modified in place. The source is already backed up on the host.
    code="from pathlib import Path\nimport os,stat,hashlib\n"
    code+=f"original=Path({str(LIVE)!r})\n"
    code+=f"candidate=Path({str(TMP)!r})\n"
    code+=f"assert original.is_file() and not original.is_symlink()\n"
    code+=f"assert candidate.is_file() and not candidate.is_symlink()\n"
    code+=f"assert hashlib.sha256(original.read_bytes()).hexdigest()=={expect_before!r}\n"
    code+=f"assert hashlib.sha256(candidate.read_bytes()).hexdigest()=={expect_after!r}\n"
    code+="os.chmod(candidate,stat.S_IMODE(original.stat().st_mode))\n"
    code+="os.replace(candidate,original)\n"
    docker_exec(code,timeout=18)


def remove_created(state):
    items=tuple(state.get("created",()))
    if not items:return
    expected=state.get("helper_hashes",{})
    # No deletion of an intervening third-party update.
    probe=helper_status(items)
    for name in items:
        if probe.get(name)==expected.get(name):
            code="from pathlib import Path\n"
            code+=f"p=Path({str(RUNTIME/name)!r})\n"
            code+="assert p.is_file() and not p.is_symlink()\n"
            code+="p.unlink()\n"
            docker_exec(code,timeout=12)


def restore(state, *, strict):
    old=Path(state["backup"])
    if not old.is_file() or sha(old.read_bytes())!=state["before"]:
        raise DeployRefusal("backup_corrupt")
    current=target_status()
    if strict and current!=state["after"]:
        raise DeployRefusal("rollback_conflict")
    if current==state["after"]:
        docker("cp",str(old),f"{CONTAINER}:{TMP}",timeout=30)
        move_candidate(state["after"],state["before"])
    elif current!=state["before"]:
        raise DeployRefusal("rollback_conflict")
    remove_created(state)
    state["status"]="rolled_back"
    save_manifest(state)


def restart():
    docker("restart",CONTAINER,timeout=70)
    if not wait_healthy():
        raise DeployRefusal("gateway_health_failed")


def apply():
    if get_container_health()!="healthy":
        raise DeployRefusal("gateway_not_healthy")
    ensure_store()
    if MANIFEST.exists():
        try:
            prior=json.loads(MANIFEST.read_text(encoding="utf-8"))
        except (OSError,ValueError):
            raise DeployRefusal("previous_transaction_unreadable") from None
        if prior.get("status")!="rolled_back":
            raise DeployRefusal("previous_transaction_exists")

    ref=command(["git","rev-parse","--verify","FETCH_HEAD"],
                timeout=10).decode("ascii").strip()
    if len(ref)!=40 or any(x not in "0123456789abcdef" for x in ref):
        raise DeployRefusal("git_ref_invalid")
    helper_bytes={name:git_source(ref,name) for name in HELPERS}
    patcher=git_source(ref,"kitty_gateway_decode_hook_patch_v6.py")
    module=types.ModuleType("kitty_v6_offline_source_patcher")
    exec(compile(patcher,"<trusted-kitty-patcher>","exec"),module.__dict__)

    probe=helper_status(HELPERS)
    created=[]
    for name,raw in helper_bytes.items():
        dest_hash=probe[name]
        if dest_hash is None:
            created.append(name)
        elif dest_hash!=sha(raw):
            raise DeployRefusal("existing_helper_conflict")
    if target_status()=="unknown":
        raise DeployRefusal("gateway_source_unreadable")
    leaf="backup-"+str(time.time_ns())
    folder=STORE/leaf
    folder.mkdir(mode=0o700)
    backup=folder/"realtime.py"
    docker("cp",f"{CONTAINER}:{LIVE}",str(backup),timeout=35)
    os.chmod(backup,0o600)
    original=backup.read_bytes()
    try:
        source=original.decode("utf-8")
        revised=module.patch(source)
    except (UnicodeError,ValueError,SyntaxError,TypeError):
        raise DeployRefusal("live_provider_layout_incompatible") from None
    # A fixed temporary file from a prior interrupted operation must not be
    # overwritten or followed as a symlink. Only a fresh target is admissible.
    check="from pathlib import Path\\n"
    check+=f"p=Path({str(TMP)!r})\\n"
    check+="assert not p.exists() and not p.is_symlink()\\n"
    docker_exec(check,timeout=12)
    expected_before=sha(original)
    if target_status()!=expected_before:
        raise DeployRefusal("gateway_source_changed")
    candidate=revised.encode("utf-8")
    state={
        "status":"prepared","git_sha":ref,
        "before":expected_before,"after":sha(candidate),
        "backup":str(backup.resolve()),"created":created,
        "helper_hashes":{n:sha(helper_bytes[n]) for n in created},
    }
    save_manifest(state)
    print("source_backup=created",flush=True)
    did_change=False
    try:
        for name in created:
            local=folder/name
            local.write_bytes(helper_bytes[name])
            os.chmod(local,0o644)
            docker("cp",str(local),f"{CONTAINER}:{RUNTIME/name}",timeout=25)
        # Pre-import everything while the old gateway continues running.
        docker_exec("from kitty_passive_turn_bridge_v6 import KittyPassiveTurnBridge\n"
                    "assert KittyPassiveTurnBridge().session_id\n",timeout=20)
        local=folder/"realtime-candidate.py"
        local.write_bytes(candidate)
        os.chmod(local,0o600)
        docker("cp",str(local),f"{CONTAINER}:{TMP}",timeout=35)
        move_candidate(expected_before,sha(candidate))
        did_change=True
        restart()
        state["status"]="installed"
        save_manifest(state)
        print("gateway_hook=installed",flush=True)
        print("gateway_health=healthy",flush=True)
        print("provider_forwarding=unchanged",flush=True)
        print("private_recall=disabled",flush=True)
        print("automatic_voice_learning=disabled",flush=True)
        print("firmware_and_SD=unchanged",flush=True)
    except (DeployRefusal,OSError,ValueError,RuntimeError):
        try:
            if did_change or target_status()==state["after"]:
                restore(state,strict=False)
                restart()
                print("rollback=completed",flush=True)
            else:
                remove_created(state)
                state["status"]="rolled_back"
                save_manifest(state)
                print("rollback=no_gateway_change",flush=True)
        except (DeployRefusal,OSError,ValueError):
            print("rollback=manual_recovery_required",flush=True)
        raise DeployRefusal("deployment_failed") from None


def rollback():
    if not MANIFEST.is_file():
        raise DeployRefusal("backup_missing")
    try:
        state=json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError,ValueError):
        raise DeployRefusal("backup_unreadable") from None
    if state.get("status")!="installed":
        raise DeployRefusal("no_active_deployment")
    restore(state,strict=True)
    restart()
    print("rollback=completed",flush=True)
    print("gateway_health=healthy",flush=True)


def main():
    p=argparse.ArgumentParser()
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument("--apply",action="store_true")
    group.add_argument("--rollback",action="store_true")
    args=p.parse_args()
    print("KITTY_V6_PROVIDER_PASSIVE_ROLLOUT",flush=True)
    try:
        if args.apply:apply()
        else:rollback()
    except DeployRefusal as exc:
        print("rollout_error="+str(exc),flush=True)
        raise SystemExit(1) from None


if __name__=="__main__":
    main()
