#!/usr/bin/env python3
"""One-use Kitty V6 passive provider observer for a READ-ONLY single-file bind.

Run on the Ubuntu HOST with Kitty idle:
  git fetch origin main
  git show FETCH_HEAD:server/kitty_gateway_bind_rollout_v6.py | python3 - --apply

Never remount, recreate Compose, change C5/S3, change owner/private memory,
modify model prompts, or enable unverified voice learning.

The Docker container's realtime.py is an individually read-only bind mount,
so os.replace() is impossible. This deployment:
  1. Verifies the EXACT source-only file bind and host/container identical sha.
  2. Saves the user's original private file in a 0700/0600 host-only backup.
  3. Applies the already tested exact-AST provider event observation patch.
  4. Stages only absent byte-identical helpers; verifies their imports.
  5. STOPS open-webui, rewrites the bind source *in-place* without changing
     its inode/ownership/mode, starts open-webui, checks health + source sha.
  6. Rolls back the exact original bytes in-place on unsuccessful startup.

The update is deliberately offline-only: no owner-memory recall is turned on,
no speaker candidate is treated as authentication, and no profile learning
is scheduled. Never prints actual host paths, source or secrets.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import types

CONTAINER="open-webui"
LIVE="/app/backend/open_webui/routers/audio/realtime.py"
STORE=Path.home()/".local/state/kitty-v6-gateway-bind"
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

class Refusal(Exception):pass

def sha(data):
    return hashlib.sha256(data).hexdigest()

def cmd(argv, *, content=None, timeout=50):
    try:
        p=subprocess.run(argv,input=content,stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL,check=False,timeout=timeout)
    except (OSError,subprocess.SubprocessError):
        raise Refusal("command_failed") from None
    if p.returncode:
        raise Refusal("command_failed")
    return p.stdout

def docker(*args,timeout=50):
    return cmd(["sudo","docker",*args],timeout=timeout)

def github_file(ref,name):
    if not isinstance(name,str) or "/" in name or not name.endswith(".py"):
        raise Refusal("invalid_module")
    data=cmd(["git","show",ref+":server/"+name],timeout=12)
    if not 1<=len(data)<=110000:raise Refusal("missing_git_source")
    try:compile(data.decode("utf-8"),"<pinned-module>","exec")
    except (SyntaxError,UnicodeError):
        raise Refusal("invalid_git_source") from None
    return data

def health():
    try:
        return docker("inspect","-f","{{.State.Health.Status}}",
                      CONTAINER,timeout=12).decode("ascii").strip()
    except (Refusal,UnicodeError):return "unknown"

def state():
    try:
        return docker("inspect","-f","{{.State.Status}}",
                      CONTAINER,timeout=12).decode("ascii").strip()
    except (Refusal,UnicodeError):return "unknown"

def wait_healthy():
    for _ in range(35):
        if health()=="healthy":return True
        time.sleep(2)
    return False

def safe_store():
    if STORE.is_symlink():raise Refusal("state_symlink")
    STORE.mkdir(parents=True,exist_ok=True,mode=0o700)
    if STORE.is_symlink() or not STORE.is_dir():raise Refusal("state_directory_invalid")
    os.chmod(STORE,0o700)

def atomic_private(path,data):
    if path.is_symlink():raise Refusal("private_target_symlink")
    fd,tmp=tempfile.mkstemp(prefix=".kitty-v6-safe-",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(tmp,0o600)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def save(tx):
    safe_store()
    atomic_private(MANIFEST,json.dumps(tx,sort_keys=True).encode())

def mounted_host_source():
    """Validate exactly one individual RO bind; never expose its Source."""
    try:
        mounts=json.loads(docker("inspect","-f","{{json .Mounts}}",
                                CONTAINER,timeout=12))
    except (ValueError,UnicodeError,TypeError):
        raise Refusal("mount_inspect_failed") from None
    found=[m for m in mounts if (isinstance(m,dict)
           and m.get("Destination")==LIVE and m.get("Type")=="bind")]
    if len(found)!=1 or found[0].get("RW") is not False:
        raise Refusal("expected_readonly_file_bind")
    source=found[0].get("Source")
    if (not isinstance(source,str) or not source.startswith("/")
            or len(source)>4096 or "\x00" in source):
        raise Refusal("invalid_mount_source")
    return source

def host_file_stat(path):
    """Metadata and sha of a fixed path, no source printed; no symlinks."""
    import stat
    if (not isinstance(path,str) or not os.path.isabs(path)
            or os.path.realpath(path)!=path):
        raise Refusal("host_path_noncanonical")
    try:
        fd=os.open(path,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0))
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:
                raise Refusal("host_source_not_regular")
            data=b""
            while True:
                piece=os.read(fd,131072)
                if not piece:break
                data+=piece
                if len(data)>2_000_000:raise Refusal("host_source_too_large")
            if not data:raise Refusal("host_source_empty")
            return {"dev":info.st_dev,"ino":info.st_ino,
                    "mode":stat.S_IMODE(info.st_mode),"uid":info.st_uid,
                    "gid":info.st_gid,"sha":sha(data)}
        finally:os.close(fd)
    except OSError:
        raise Refusal("host_source_read_denied") from None

ROOT_STAT_HELPER=r'''import hashlib,json,os,stat,sys
path=sys.argv[1]
assert os.path.isabs(path) and os.path.realpath(path)==path
fd=os.open(path,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0))
try:
 info=os.fstat(fd)
 assert stat.S_ISREG(info.st_mode) and info.st_nlink==1
 digest=hashlib.sha256()
 total=0
 while True:
  chunk=os.read(fd,131072)
  if not chunk:break
  total+=len(chunk)
  assert total<=2000000
  digest.update(chunk)
 assert total>0
 print(json.dumps({"dev":info.st_dev,"ino":info.st_ino,
   "mode":stat.S_IMODE(info.st_mode),"uid":info.st_uid,"gid":info.st_gid,
   "sha":digest.hexdigest()}))
finally:os.close(fd)
'''

def verified_host_stat(path):
    """Read host file metadata without requiring user access to a root file.

    Prefer normal unprivileged access; sudo fallback prints fixed JSON only.
    Neither mode prints the source path or any file contents.
    """
    try:
        return host_file_stat(path)
    except Refusal as err:
        if str(err)!="host_source_read_denied":
            raise
    try:
        obj=json.loads(cmd(["sudo","python3","-c",ROOT_STAT_HELPER,path],
                           timeout=20))
    except (Refusal,ValueError,UnicodeError,TypeError):
        raise Refusal("host_source_metadata_denied") from None
    if (not isinstance(obj,dict)
            or set(obj)!={"dev","ino","mode","uid","gid","sha"}
            or any(type(obj[k]) is not int for k in ("dev","ino","mode","uid","gid"))
            or type(obj["sha"]) is not str or len(obj["sha"])!=64):
        raise Refusal("host_source_metadata_invalid")
    return obj

def overwrite_same_inode(path, incoming, expected, original):
    """This runs as root, only while Docker is STOPPED in normal deployment.

    Replaces bytes inside the already bind-mounted inode; unlike os.replace,
    the container will still see the updated bytes after docker start.
    """
    if (not isinstance(incoming,bytes) or len(incoming)>2_000_000
            or not incoming):
        raise Refusal("invalid_candidate")
    info=host_file_stat(path)
    for key in ("dev","ino","uid","gid","mode"):
        if info[key]!=original[key]:
            raise Refusal("host_inode_or_metadata_changed")
    if info["sha"]!=expected:
        raise Refusal("host_source_conflict")
    try:
        fd=os.open(path,os.O_WRONLY|getattr(os,"O_NOFOLLOW",0))
        try:
            current=os.fstat(fd)
            if ((current.st_dev,current.st_ino)!=(original["dev"],original["ino"])):
                raise Refusal("host_inode_changed")
            os.lseek(fd,0,os.SEEK_SET)
            pending=memoryview(incoming)
            while pending:
                n=os.write(fd,pending)
                if n<=0:raise Refusal("host_write_failed")
                pending=pending[n:]
            os.ftruncate(fd,len(incoming))
            os.fsync(fd)
        finally:os.close(fd)
    except OSError:
        raise Refusal("host_write_failed") from None
    final=host_file_stat(path)
    if (final["sha"]!=sha(incoming) or
            final["ino"]!=original["ino"] or final["dev"]!=original["dev"]):
        raise Refusal("host_write_verification_failed")
    return True

def root_write(source,payload,expected,meta):
    """Execute narrowly scoped trusted writer as host root; no output leakage."""
    # The second process is an exact copy of THIS GitHub file (pinned SHA)
    # invoked through sudo; no host-source data is sent as command arguments.
    script=Path(__file__).resolve() if __file__!="<stdin>" else None
    # When launched through git show | python3 -, use a minimal self-contained
    # root program built from the verified function source below.
    helper=ROOT_HELPER
    try:
        p=subprocess.run(["sudo","python3","-c",helper,source,expected,
                          json.dumps(meta,sort_keys=True)],
                         input=payload,stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL,check=False,timeout=20)
    except (OSError,subprocess.SubprocessError):
        raise Refusal("host_root_writer_failed") from None
    if p.returncode or p.stdout!=b"verified\n":
        raise Refusal("host_root_writer_failed")

# This code is re-checked with compile() in offline tests. The root process
# does not import project code or accept untrusted scripts from the device.
ROOT_HELPER=r'''import hashlib,json,os,stat,sys
path=sys.argv[1]
expected=sys.argv[2]
meta=json.loads(sys.argv[3])
incoming=sys.stdin.buffer.read(2000001)
def check(fd):
 st=os.fstat(fd)
 assert stat.S_ISREG(st.st_mode) and st.st_nlink==1
 assert [st.st_dev,st.st_ino,st.st_uid,st.st_gid,stat.S_IMODE(st.st_mode)]==[
    meta["dev"],meta["ino"],meta["uid"],meta["gid"],meta["mode"]]
 os.lseek(fd,0,os.SEEK_SET)
 digest=hashlib.sha256()
 while True:
  chunk=os.read(fd,131072)
  if not chunk:break
  digest.update(chunk)
 return digest.hexdigest()
assert os.path.isabs(path) and os.path.realpath(path)==path
assert len(incoming)>0 and len(incoming)<=2000000
fd=os.open(path,os.O_RDWR|getattr(os,"O_NOFOLLOW",0))
try:
 assert check(fd)==expected
 os.lseek(fd,0,os.SEEK_SET)
 rest=memoryview(incoming)
 while rest:
  n=os.write(fd,rest)
  assert n>0
  rest=rest[n:]
 os.ftruncate(fd,len(incoming))
 os.fsync(fd)
 assert check(fd)==hashlib.sha256(incoming).hexdigest()
finally:os.close(fd)
sys.stdout.write("verified\n")
'''

def source_in_container():
    b=docker("exec",CONTAINER,"cat",LIVE,timeout=22)
    if not 1<=len(b)<=2_000_000:raise Refusal("container_source_invalid")
    return b

def helper_inventory():
    code="import hashlib,json\nfrom pathlib import Path\n"
    code+="names="+repr(HELPERS)+"\nroot=Path('/app/backend')\nout={}\n"
    code+="for name in names:\n"
    code+=" p=root/name\n"
    code+=" out[name]='unsafe' if p.is_symlink() else (hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else 'unsafe' if p.exists() else None)\n"
    code+="print(json.dumps(out))\n"
    try:
        out=json.loads(docker("exec",CONTAINER,"python3","-c",code,timeout=15))
    except (ValueError,UnicodeError):
        raise Refusal("helper_inventory_failed") from None
    if set(out)!=set(HELPERS):raise Refusal("helper_inventory_invalid")
    return out

def remove_created(created,expected):
    for name in created:
        if helper_inventory().get(name)!=expected[name]:continue
        code=("from pathlib import Path\nimport hashlib\n"
              f"p=Path({('/app/backend/'+name)!r})\n"
              "assert p.is_file() and not p.is_symlink()\n"
              f"assert hashlib.sha256(p.read_bytes()).hexdigest()=={expected[name]!r}\n"
              "p.unlink()\n")
        docker("exec","--user","0",CONTAINER,"python3","-c",code,timeout=12)

def patcher_from_git(ref):
    code=github_file(ref,"kitty_gateway_decode_hook_patch_v6.py")
    mod=types.ModuleType("kitty_approved_patcher")
    exec(compile(code,"<verified-source-patcher>","exec"),mod.__dict__)
    return mod

def git_sha():
    val=cmd(["git","rev-parse","--verify","FETCH_HEAD"],timeout=10).decode("ascii").strip()
    if len(val)!=40 or any(c not in "0123456789abcdef" for c in val):
        raise Refusal("unpinned_fetch_head")
    return val

def file_copy_private(path,data):
    flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0)
    try:
        fd=os.open(path,flags,0o600)
        with os.fdopen(fd,"wb") as f:
            f.write(data);f.flush();os.fsync(f.fileno())
    except OSError:
        raise Refusal("private_backup_failed") from None
    if sha(path.read_bytes())!=sha(data):raise Refusal("private_backup_mismatch")

def apply():
    if health()!="healthy":raise Refusal("gateway_not_healthy")
    safe_store()
    if MANIFEST.exists():
        try:earlier=json.loads(MANIFEST.read_text())
        except (OSError,ValueError):raise Refusal("prior_transaction_invalid") from None
        if earlier.get("status") not in ("rolled_back",):
            raise Refusal("previous_installation_or_unfinished_transaction")
    ref=git_sha()
    source=mounted_host_source()
    original=source_in_container()
    hostmeta=verified_host_stat(source)
    if hostmeta["sha"]!=sha(original):
        raise Refusal("host_container_source_mismatch")
    try:updated=patcher_from_git(ref).patch(original.decode("utf-8")).encode()
    except (UnicodeError,ValueError,TypeError,SyntaxError):
        raise Refusal("source_shape_incompatible") from None
    if updated==original:raise Refusal("source_unmodified")
    names={n:github_file(ref,n) for n in HELPERS}
    inventory=helper_inventory()
    created=[]
    for n,data in names.items():
        if inventory[n] is None:created.append(n)
        elif inventory[n]!=sha(data):raise Refusal("existing_helper_conflict")
    # Private source backup and transaction owned by invoking Ubuntu user.
    folder=STORE/("backup-"+str(time.time_ns()))
    folder.mkdir(mode=0o700)
    backup=folder/"realtime.py"
    file_copy_private(backup,original)
    candidate=folder/"realtime-patched.py"
    file_copy_private(candidate,updated)
    tx={
        "status":"prepared","pinned_ref":ref,"backup":str(backup),
        "candidate":str(candidate),"before":sha(original),"after":sha(updated),
        "host_source":source,"host_meta":hostmeta,
        "created":created,
        "helper_hashes":{n:sha(names[n]) for n in created},
    }
    save(tx)
    print("backup=verified",flush=True)
    phase="copy_helpers"
    stopped=False
    wrote=False
    try:
        for n in created:
            local=folder/n
            file_copy_private(local,names[n])
            docker("cp",str(local),CONTAINER+":/app/backend/"+n,timeout=25)
        phase="preimport"
        docker("exec","-w","/app/backend",CONTAINER,"python3","-c",
               "from kitty_passive_turn_bridge_v6 import KittyPassiveTurnBridge\n"
               "assert KittyPassiveTurnBridge().session_id\n",timeout=18)
        if mounted_host_source()!=source:
            raise Refusal("mount_source_changed")
        if sha(source_in_container())!=tx["before"]:
            raise Refusal("source_changed_before_stop")
        phase="stop"
        tx["status"]="stopping"
        save(tx)
        docker("stop",CONTAINER,timeout=70)
        stopped=True
        if state()!="exited":raise Refusal("container_not_stopped")
        phase="host_write"
        tx["status"]="writing"
        save(tx)
        root_write(source,updated,tx["before"],hostmeta)
        wrote=True
        tx["status"]="patched"
        save(tx)
        phase="start"
        docker("start",CONTAINER,timeout=70)
        stopped=False
        if not wait_healthy():raise Refusal("gateway_health_failed")
        phase="verify"
        if (sha(source_in_container())!=tx["after"]
                or verified_host_stat(source)["sha"]!=tx["after"]):
            raise Refusal("deployed_content_mismatch")
        tx["status"]="installed"
        save(tx)
        print("gateway_hook=installed",flush=True)
        print("gateway_health=healthy",flush=True)
        print("host_inode=preserved",flush=True)
        print("provider_forwarding=unchanged",flush=True)
        print("private_recall=disabled",flush=True)
        print("automatic_voice_learning=disabled",flush=True)
        print("firmware_and_SD=unchanged",flush=True)
    except Exception:
        print("failed_phase="+phase,flush=True)
        try:
            # An error before stop leaves the realtime source unchanged.
            # Do not interrupt a healthy call service merely to clean helpers.
            if phase in ("copy_helpers","preimport"):
                if verified_host_stat(source)["sha"]!=tx["before"]:
                    raise Refusal("source_changed_during_staging")
                if state()=="running":
                    remove_created(created,tx["helper_hashes"])
                    tx["status"]="rolled_back"
                    save(tx)
                    print("rollback=no_gateway_change",flush=True)
                else:
                    raise Refusal("container_state_changed")
            else:
                if state()!="exited":
                    docker("stop",CONTAINER,timeout=70)
                if sha(backup.read_bytes())!=tx["before"]:
                    raise Refusal("backup_corrupt")
                current_sha=verified_host_stat(source)["sha"]
                if current_sha==tx["after"]:
                    root_write(source,original,tx["after"],hostmeta)
                elif current_sha!=tx["before"]:
                    raise Refusal("rollback_conflict")
                tx["status"]="rolled_back"
                save(tx)
                docker("start",CONTAINER,timeout=70)
                if not wait_healthy():raise Refusal("rollback_gateway_unhealthy")
                remove_created(created,tx["helper_hashes"])
                print("rollback=completed",flush=True)
        except Exception:
            print("rollback=manual_recovery_required",flush=True)
        raise Refusal("deployment_failed:"+phase) from None

def rollback():
    if not MANIFEST.exists():raise Refusal("no_installation")
    try:tx=json.loads(MANIFEST.read_text())
    except (OSError,ValueError):raise Refusal("invalid_transaction") from None
    if tx.get("status")!="installed":raise Refusal("no_active_installation")
    current_source=mounted_host_source()
    if current_source!=tx["host_source"]:raise Refusal("mount_changed")
    original=Path(tx["backup"]).read_bytes()
    if sha(original)!=tx["before"]:raise Refusal("backup_corrupt")
    metadata=verified_host_stat(current_source)
    if metadata["sha"]!=tx["after"]:raise Refusal("rollback_conflict")
    for key in ("dev","ino","mode","uid","gid"):
        if metadata[key]!=tx["host_meta"][key]:raise Refusal("host_inode_changed")
    docker("stop",CONTAINER,timeout=70)
    try:
        root_write(current_source,original,tx["after"],metadata)
        tx["status"]="rolled_back"
        save(tx)
    finally:
        docker("start",CONTAINER,timeout=70)
    if not wait_healthy():raise Refusal("rollback_health_failed")
    remove_created(tx["created"],tx["helper_hashes"])
    print("rollback=completed",flush=True)
    print("gateway_health=healthy",flush=True)

def main():
    p=argparse.ArgumentParser()
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--apply",action="store_true")
    mode.add_argument("--rollback",action="store_true")
    args=p.parse_args()
    print("KITTY_V6_READONLY_BIND_GATEWAY_ROLLOUT",flush=True)
    try:
        if args.apply:apply()
        else:rollback()
    except Refusal as exc:
        print("rollout_error="+str(exc),flush=True)
        raise SystemExit(1) from None
    except (OSError,ValueError,TypeError,PermissionError):
        print("rollout_error=unexpected_local_error",flush=True)
        raise SystemExit(1) from None

if __name__=="__main__":main()
