#!/usr/bin/env python3
"""One-shot guarded Ubuntu V6 voice safety bundle, with exact rollback.

Run only from your existing private checkout after git fetch origin main:
 git show FETCH_HEAD:server/kitty_v6_voice_stage_deploy.py | python3 - --apply

This is a narrow safety deployment, NOT hands-free owner identification.
It preserves the live custom memory service, private owner-grant guard,
Open WebUI and S3/C5 firmware. It patches only the exact old X-vector
experimental identity branch inside the CPU worker, if the canonical
old branch exists; copies only ABSENT opt-in modules from FETCH_HEAD.
All changed files are backed up and will roll back if health or private
semantic 403 validation fails. Nothing overwrites profile/SD/secret files.
No source, tokens, paths, credentials or voice data are logged.
"""
import argparse
import ast
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import types

STATE=Path.home()/".local/state/kitty-v6-voice-stage"
STATE_FILE=STATE/"transaction.json"
SPEAKER_NAME="kitty_speaker_cpu_v6.py"
HELPERS=(
  "kitty_voice_adaptation_policy_v6.py",
  "kitty_voice_adaptive_scoring_v6.py",
  "kitty_voice_familiarity_hints_v6.py",
  "kitty_voice_learning_v6.py",
  "kitty_owner_voice_postcall_v6.py",
  "kitty_owner_voice_profile_store_v6.py",
  "kitty_owner_voice_review_issuer_v6.py",
  "kitty_owner_voice_review_workflow_v6.py",
  "kitty_owner_voice_learning_factory_v6.py",
  "kitty_xvector_adaptive_store_v6.py",
  "kitty_attested_live_call_v6.py",
  "kitty_gateway_turn_adapter_v6.py",
  "kitty_turn_context_v6.py",
  "kitty_live_rolling_context_v6.py",
)
# Exact older branch only; refuse customized or ambiguous live handlers.
OLD_BRANCH='''    # Explicit experimental opt-in. This returns an identity used downstream for
    # speaker-scoped recall; enable only with acceptance of voice spoofing risk.
    if os.environ.get("KITTY_XVECTOR_EXPERIMENTAL_IDENTITY") == "1":
        try:
            from kitty_xvector_shadow_worker_v6 import recognize_candidate
            return recognize_candidate(raw)
        except (ImportError, OSError, RuntimeError, ValueError):
            return {"speaker_id":"unknown","confidence":"unknown","score":None}
'''
STATE_VERSION=1


class StageError(Exception): pass


def digest(blob): return hashlib.sha256(blob).hexdigest()


def run(argv, *, timeout=15):
    try:
        p=subprocess.run(argv,capture_output=True,check=False,text=True,timeout=timeout)
    except (OSError,subprocess.SubprocessError):
        raise StageError("command_failed") from None
    if p.returncode:
        raise StageError("command_failed")
    return p.stdout


def upstream(name):
    if not name.endswith(".py") or "/" in name:
        raise StageError("unsupported_module")
    source=run(["git","show","FETCH_HEAD:server/"+name],timeout=10)
    if not source or len(source)>110000:
        raise StageError("missing_fetched_source")
    compile(source,"<fetched-v6-module>","exec")
    return source


def load_primitives():
    source=upstream("kitty_owner_guard_deploy_v6.py")
    lib=types.ModuleType("kitty_live_guard_utilities")
    exec(compile(source,"<guard-utilities>","exec"),lib.__dict__)
    return lib


def resolve_active_memory_service():
    src=upstream("kitty_owner_guard_plan_v6.py")
    mod=types.ModuleType("kitty_source_locator")
    exec(compile(src,"<source-locator>","exec"),mod.__dict__)
    return mod.live_service_source()


def speaker_patch(live, fetched):
    """Return (new source, status). Never patch entire live speaker module."""
    if not isinstance(live,str) or not isinstance(fetched,str):
        raise StageError("speaker_source_incompatible")
    if live.count("KITTY_XVECTOR_EXPERIMENTAL_IDENTITY") != 1:
        raise StageError("speaker_source_incompatible")
    tree=ast.parse(fetched)
    identify=next((n for n in tree.body
                   if isinstance(n,ast.FunctionDef) and n.name=="identify"),None)
    if identify is None:
        raise StageError("speaker_source_incompatible")
    guarded=[n for n in ast.walk(identify)
             if isinstance(n,ast.If) and
             "KITTY_XVECTOR_EXPERIMENTAL_IDENTITY" in
             ast.get_source_segment(fetched,n.test)]
    if len(guarded)!=1:
        raise StageError("speaker_source_incompatible")
    replacement=ast.get_source_segment(fetched,guarded[0])
    if not replacement or '"candidate_only":True' not in replacement:
        raise StageError("speaker_source_incompatible")
    if OLD_BRANCH in live:
        patched=live.replace(OLD_BRANCH,
            "    # Experimental X-vector match remains a candidate, never identity.\n"
            + "".join("    "+line+"\n" for line in replacement.splitlines()))
        # Ensure neither a malformed indentation nor duplicated if logic.
        compile(patched,"<live-voice-candidate-patch>","exec")
        if patched.count("KITTY_XVECTOR_EXPERIMENTAL_IDENTITY") != 1:
            raise StageError("speaker_source_incompatible")
        return patched,"patched"
    # A token elsewhere in this file is NOT proof this branch was fixed.
    # Require this exact AST (modulo whitespace) for already-safe detection.
    try:
        actual=ast.parse(live)
        actual_identify=next(n for n in actual.body
                             if isinstance(n,ast.FunctionDef)
                             and n.name=="identify")
        actual_branches=[n for n in ast.walk(actual_identify)
                         if isinstance(n,ast.If) and
                         "KITTY_XVECTOR_EXPERIMENTAL_IDENTITY" in
                         ast.get_source_segment(live,n.test)]
        if (len(actual_branches)==1
                and ast.dump(actual_branches[0],include_attributes=False)
                ==ast.dump(guarded[0],include_attributes=False)):
            return live,"already_safe"
    except (SyntaxError,StopIteration,ValueError,TypeError):
        pass
    raise StageError("speaker_source_incompatible")


def check_target(path):
    if path.is_symlink() or not path.is_file():
        raise StageError("live_source_not_regular")
    if not os.access(path,os.W_OK):
        raise StageError("live_source_not_writable")


def atomic_write(path,data,mode=0o644):
    if path.is_symlink():
        raise StageError("symlink_refused")
    fd,temp=tempfile.mkstemp(prefix=".kitty-voice-transaction-",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(data);f.flush();os.fsync(f.fileno())
        os.chmod(temp,mode)
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)


def state_save(data):
    STATE.mkdir(mode=0o700,parents=True,exist_ok=True)
    os.chmod(STATE,0o700)
    atomic_write(STATE_FILE,json.dumps(data,sort_keys=True).encode(),0o600)


def restore(data, *, strict):
    target=Path(data["speaker_path"])
    backup=Path(data["backup"])
    if not backup.is_file() or target.is_symlink() or not target.is_file():
        raise StageError("backup_unavailable")
    live=target.read_bytes()
    if strict and digest(live)!=data["new_sha"]:
        raise StageError("rollback_conflict")
    old=backup.read_bytes()
    if digest(old)!=data["old_sha"]:
        raise StageError("backup_corrupt")
    atomic_write(target,old,int(data["source_mode"]))
    for name in data["created"]:
        p=target.parent/name
        if (p.is_file() and not p.is_symlink() and
                digest(p.read_bytes())==data["module_shas"][name]):
            p.unlink()
    data["status"]="rolled_back"
    state_save(data)


def apply():
    service=resolve_active_memory_service()
    if service is None or not service.is_file():
        raise StageError("memory_service_not_resolved")
    # The earlier owner-grant security deployment must still be installed.
    source=service.read_text(encoding="utf-8")
    if "authorized_semantic_speaker(data,OWNER_PROOF)" not in source:
        raise StageError("owner_guard_not_installed")
    lib=load_primitives()
    if not lib.healthy():
        raise StageError("memory_service_unhealthy")
    if STATE_FILE.exists():
        raise StageError("prior_transaction_exists")
    target=service.parent/SPEAKER_NAME
    check_target(target)
    before=target.read_bytes()
    after,status=speaker_patch(before.decode("utf-8"),upstream(SPEAKER_NAME))
    after_bytes=after.encode()
    modules={}
    created=[]
    for name in HELPERS:
        desired=upstream(name).encode()
        dest=service.parent/name
        if dest.is_symlink():
            raise StageError("helper_path_conflict")
        if dest.exists():
            if not dest.is_file() or dest.read_bytes()!=desired:
                raise StageError("helper_version_conflict")
        else:
            if not os.access(dest.parent,os.W_OK):
                raise StageError("helper_directory_not_writable")
            created.append(name)
        modules[name]=desired
    # No need to restart if this was already deployed identically.
    STATE.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(STATE,0o700)
    backup_dir=STATE/("backup-"+str(time.time_ns()))
    backup_dir.mkdir(mode=0o700)
    backup=backup_dir/SPEAKER_NAME
    atomic_write(backup,before,0o600)
    trans={
        "version":STATE_VERSION,"status":"prepared",
        "speaker_path":str(target.resolve()),"backup":str(backup.resolve()),
        "old_sha":digest(before),"new_sha":digest(after_bytes),
        "created":created,"module_shas":{n:digest(modules[n]) for n in created},
        "source_mode":stat.S_IMODE(target.stat().st_mode),
    }
    state_save(trans)
    print("backup=created",flush=True)
    replaced=False
    try:
        for name in created:
            atomic_write(target.parent/name,modules[name],0o644)
        if after_bytes!=before:
            atomic_write(target,after_bytes,trans["source_mode"])
            replaced=True
        print("candidate_identity_guard="+status,flush=True)
        print("optional_helpers_staged="+str(len(HELPERS)),flush=True)
        # The user memory service restart is the only process change.
        lib.restart()
        pid=lib.wait_healthy()
        if not pid:
            raise StageError("health_validation_failed")
        token=lib.process_token(pid)
        if not lib.private_routes_deny_unverified(token):
            raise StageError("private_403_validation_failed")
        trans["status"]="installed"
        state_save(trans)
        print("memory_service=healthy",flush=True)
        print("private_403=verified",flush=True)
        print("candidate_only_safety=staged",flush=True)
        print("live_owner_auto_learning=off",flush=True)
        print("open_webui_audio=untouched",flush=True)
        print("esp32_firmware=untouched",flush=True)
    except Exception:
        try:
            restore(trans,strict=False)
            lib.restart()
            recovered=bool(lib.wait_healthy())
            print("rollback="+("completed" if recovered else "health_not_confirmed"))
        except Exception:
            print("rollback=manual_recovery_required")
        raise StageError("deployment_rolled_back") from None


def rollback():
    if not STATE_FILE.exists():
        raise StageError("backup_unavailable")
    data=json.loads(STATE_FILE.read_text())
    if data.get("status")!="installed":
        raise StageError("no_active_installation")
    lib=load_primitives()
    restore(data,strict=True)
    lib.restart()
    if not lib.wait_healthy():
        raise StageError("rollback_health_failed")
    print("rollback=completed")


def main():
    p=argparse.ArgumentParser()
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument("--apply",action="store_true")
    group.add_argument("--rollback",action="store_true")
    args=p.parse_args()
    print("KITTY_V6_VOICE_SAFETY_STAGE")
    try:
        if args.apply:apply()
        else:rollback()
    except Exception as err:
        label=str(err) if isinstance(err,StageError) else "unexpected_error"
        print("stage_error="+label)
        raise SystemExit(1) from None


if __name__=="__main__":
    main()
