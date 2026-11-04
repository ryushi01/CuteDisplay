#!/usr/bin/env python3
"""Read-only deployed Kitty V6 source/capability preflight for the Ubuntu VM.

Only prints fixed, non-sensitive statuses; NEVER prints process arguments,
environment, sources, transcripts, tokens, voice profiles, paths or health JSON.
This does not change systemd, Docker, Open WebUI, firmware or the SD archive.
Run as the user who owns kitty-memory-v6.service.
"""
import json
import os
from pathlib import Path
import subprocess
import urllib.request

GATEWAY_MARKERS = {
    "public_memory_refresh": "kitty.memory.refresh",
    "public_profile": "KITTY_INITIAL_PUBLIC_PROFILE_V6",
    "speaker_observer": "KittySpeakerObserver",
    "speaker_turn_result": "kitty.speaker.result",
    "semantic_request": "kitty.memory.semantic",
    "candidate_item": "KITTY_CANDIDATE_CONTEXT_ITEM_V6",
}
MEMORY_MARKERS = {
    "owner_grant_gate": "authorized_semantic_speaker(data,OWNER_PROOF)",
    "owner_challenge": '"/owner/challenge"',
    "private_semantic_endpoint": '"/semantic/context"',
    "shared_context_endpoint": '"/shared/context"',
}


def _run(argv, *, runner=subprocess.run, timeout=8):
    try:
        proc=runner(argv,capture_output=True,text=True,timeout=timeout,
                    check=False)
        if proc.returncode==0:
            return proc.stdout
    except (OSError,ValueError,subprocess.SubprocessError):
        pass
    return None


def user_unit_info(*, runner=subprocess.run):
    """Only read MainPID and ActiveState; never expose ExecStart or Environment."""
    result=_run(["systemctl","--user","show","kitty-memory-v6.service",
                 "-p","ActiveState","-p","MainPID"],runner=runner)
    if result is None:
        return "unknown",0
    pairs=dict(row.split("=",1) for row in result.splitlines() if "=" in row)
    state=pairs.get("ActiveState","unknown")
    if state not in ("active","inactive","failed","activating","deactivating"):
        state="unknown"
    pid=pairs.get("MainPID","0")
    return state,int(pid) if pid.isdecimal() else 0


def live_source_for_pid(pid, *, proc_root=Path("/proc")):
    """Identify only the named Python module, not arbitrary process/env files."""
    if not isinstance(pid,int) or pid<=0:
        return None
    base=proc_root/str(pid)
    try:
        parts=(base/"cmdline").read_bytes().split(b"\\0")
        names=[os.fsdecode(p) for p in parts if p]
        scripts=[p for p in names if p.endswith("/kitty_memory_service.py")
                 or p=="kitty_memory_service.py"]
        if len(scripts)!=1:
            return None
        script=Path(scripts[0])
        if not script.is_absolute():
            script=(Path(os.readlink(base/"cwd"))/script)
        script=script.resolve(strict=True)
        if script.is_file() and script.name=="kitty_memory_service.py":
            return script
    except (OSError,UnicodeError,ValueError):
        pass
    return None


def source_markers(source, markers):
    if not isinstance(source,str):
        return {key:"unknown" for key in markers}
    return {key:("present" if token in source else "absent")
            for key,token in markers.items()}


def gateway_markers(*, runner=subprocess.run):
    # Only fixed strings/booleans cross Docker stdout, not gateway source.
    code = (
        "import json; from pathlib import Path; "
        "p=Path('/app/backend/open_webui/routers/audio/realtime.py'); "
        "s=p.read_text(encoding='utf-8') if p.is_file() else None; "
        "marks="+repr(GATEWAY_MARKERS)+"; "
        "print(json.dumps({k:('unknown' if s is None else "
        "('present' if v in s else 'absent')) "
        "for k,v in marks.items()}))"
    )
    output=_run(["docker","exec","open-webui","python","-c",code],runner=runner)
    if output is None:
        return source_markers(None,GATEWAY_MARKERS)
    try:
        data=json.loads(output)
        if isinstance(data,dict) and set(data)==set(GATEWAY_MARKERS) and all(
                v in ("present","absent","unknown") for v in data.values()):
            return data
    except (ValueError,TypeError):
        pass
    return source_markers(None,GATEWAY_MARKERS)


def memory_health(*, opener=None):
    # No redirects or proxies; avoid forwarding credentials even if service
    # becomes misconfigured. The /health endpoint requires no bearer key.
    if opener is None:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                          _NoRedirect())
    try:
        response=opener.open("http://127.0.0.1:8766/health",timeout=2)
        with response as r:
            return "ok" if r.status==200 and json.loads(
                r.read(1024)).get("ok") is True else "not_ok"
    except (OSError,ValueError,TypeError,AttributeError):
        return "unavailable"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,request,fp,code,msg,headers,newurl):
        return None


def probe(*, runner=subprocess.run, proc_root=Path("/proc"),
          opener=None):
    state,pid=user_unit_info(runner=runner)
    path=live_source_for_pid(pid,proc_root=proc_root)
    try:
        source=path.read_text(encoding="utf-8") if path else None
    except (OSError,UnicodeError):
        source=None
    result={"memory_service_state":state,
            "memory_http_health":memory_health(opener=opener)}
    result.update({"memory_"+k:v for k,v in
                   source_markers(source,MEMORY_MARKERS).items()})
    result.update({"gateway_"+k:v for k,v in
                   gateway_markers(runner=runner).items()})
    # Cannot deduce grants, human identity or staging readiness from source text.
    result["trusted_speaker_turn_issuer"]="not_verified"
    result["safe_to_enable_private_auto_recall"]="no"
    return result


def main():
    print("KITTY_V6_READ_ONLY_PREFLIGHT")
    for k,v in probe().items():
        print(f"{k}={v}")
    print("No files, settings, credentials, containers or firmware changed.")


if __name__=="__main__":
    main()
