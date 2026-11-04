#!/usr/bin/env python3
"""Read-only diagnosis of a failed atomic replace of Open WebUI realtime.py.

Reads Docker mount metadata and fixed-path container filesystem status only.
Never reads or prints file content, host mount source paths, configuration,
transcripts, credentials, environment variables, log lines, or private hashes.

Run on Ubuntu HOST:
  git show FETCH_HEAD:server/kitty_gateway_atomic_mount_probe_v6.py | python3 -
"""
import json
import os
import subprocess

CONTAINER="open-webui"
TARGET="/app/backend/open_webui/routers/audio/realtime.py"


def _run(argv):
    try:
        p=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                         timeout=14,check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode!=0 or len(p.stdout)>30000:
        return None
    return p.stdout


def classify_mounts(mounts, target=TARGET):
    """Only fixed status labels; no host Source or Docker volume names."""
    if not isinstance(mounts,list):
        return {"mount_layout":"unverified","mount_write_mode":"unknown"}
    matched=[]
    for m in mounts:
        if not isinstance(m,dict):
            continue
        dest=m.get("Destination")
        if not isinstance(dest,str) or not dest.startswith("/"):
            continue
        if dest==target or target.startswith(dest.rstrip("/")+"/"):
            matched.append(m)
    if not matched:
        return {"mount_layout":"container_layer",
                "mount_write_mode":"unknown"}
    match=max(matched,key=lambda m:len(m.get("Destination","")))
    direct=match.get("Destination")==target
    kind=match.get("Type")
    if kind not in ("bind","volume","tmpfs"):
        kind="other"
    result={
        "mount_layout":("file_" if direct else "parent_")+kind,
        "mount_write_mode":("rw" if match.get("RW") is True
                            else "ro" if match.get("RW") is False
                            else "unknown")
    }
    return result


def classify_container_state(state):
    if not isinstance(state,dict):
        return {
            "target_is_mountpoint":"unknown",
            "target_is_regular_file":"unknown",
            "parent_writable_for_root":"unknown",
            "filesystem_readonly":"unknown",
            "known_staging_candidate":"unknown",
            "inspect_uid":"unknown",
        }
    result={}
    for source,key in (
        ("is_mountpoint","target_is_mountpoint"),
        ("is_regular_file","target_is_regular_file"),
        ("parent_root_writable","parent_writable_for_root"),
        ("readonly_fs","filesystem_readonly"),
        ("staging_exists","known_staging_candidate")):
        val=state.get(source)
        result[key]="yes" if val is True else "no" if val is False else "unknown"
    uid=state.get("effective_uid")
    result["inspect_uid"]="root" if uid==0 and type(uid) is int else "other"
    return result


def inspect_container():
    # Exact fixed path only. No source content or private directory listings.
    snippet=r'''import json,os,stat
from pathlib import Path
p=Path("/app/backend/open_webui/routers/audio/realtime.py")
tmp=p.with_name(".kitty-v6-provider-passive-candidate.py")
data={
 "effective_uid":os.geteuid(),
 "is_mountpoint":os.path.ismount(str(p)),
 "is_regular_file":p.is_file() and not p.is_symlink(),
 "parent_root_writable":os.access(str(p.parent),os.W_OK),
 "readonly_fs":bool(os.statvfs(str(p.parent)).f_flag & os.ST_RDONLY),
 "staging_exists":tmp.exists() or tmp.is_symlink(),
}
print(json.dumps(data))
'''
    data=_run(["sudo","docker","exec","--user","0",
               CONTAINER,"python3","-c",snippet])
    if data is None:
        return classify_container_state(None)
    try:
        obj=json.loads(data)
    except (UnicodeError,ValueError,TypeError):
        obj=None
    return classify_container_state(obj)


def inspect_mounts():
    data=_run(["sudo","docker","inspect","-f","{{json .Mounts}}",CONTAINER])
    if data is None:
        return classify_mounts(None)
    try:
        mounts=json.loads(data)
    except (UnicodeError,ValueError,TypeError):
        mounts=None
    return classify_mounts(mounts)


def diagnosis(mount, state):
    if (mount["mount_layout"]=="file_bind"
            or state["target_is_mountpoint"]=="yes"):
        return "single_file_mount_possible"
    if mount["mount_write_mode"]=="ro" or state["filesystem_readonly"]=="yes":
        return "read_only_mount_possible"
    if state["parent_writable_for_root"]=="no":
        return "directory_permission_possible"
    if state["target_is_regular_file"]=="no":
        return "target_file_invalid"
    if state["known_staging_candidate"]=="yes":
        return "stale_staging_file_needs_validation"
    if (mount["mount_layout"]=="container_layer"
            and state["target_is_mountpoint"]=="no"):
        return "replace_failure_requires_errno"
    return "mount_details_inconclusive"


def main():
    mount=inspect_mounts()
    state=inspect_container()
    print("KITTY_V6_GATEWAY_ATOMIC_REPLACE_READ_ONLY")
    for key in ("mount_layout","mount_write_mode"):
        print(key+"="+mount[key])
    for key in ("target_is_mountpoint","target_is_regular_file",
                "parent_writable_for_root","filesystem_readonly",
                "known_staging_candidate","inspect_uid"):
        print(key+"="+state[key])
    print("diagnosis="+diagnosis(mount,state))
    print("No Docker, gateway, memory, firmware or SD files changed.")


if __name__=="__main__":
    main()
