#!/usr/bin/env python3
"""Read-only compatibility plan for Kitty private semantic owner-guard update.

Works from `git show FETCH_HEAD:server/kitty_owner_guard_plan_v6.py | python3 -`
inside the existing Git checkout. It reads only the running memory-service
module, its sibling-module presence, and FETCH_HEAD's tracked source.
It does NOT write source, create .pyc files, alter systemd, restart services,
load private databases, or access snapshots, keys, audio or transcripts.

Output contains only predetermined status values; no code, paths, credentials
or user data. Do not treat "candidate_compiles=yes" as deployment approval.
"""
import ast
import os
from pathlib import Path
import subprocess

MODULES=(
    "kitty_semantic_authorization_v6.py",
    "kitty_owner_session_v6.py",
    "kitty_memory_context_v6.py",
    "kitty_sd_semantic_index.py",
)


def _route(node):
    if not isinstance(node,ast.If):
        return ""
    test=node.test
    if (not isinstance(test,ast.Compare) or len(test.ops)!=1
            or len(test.comparators)!=1
            or not isinstance(test.left,ast.Attribute)
            or not isinstance(test.left.value,ast.Name)
            or test.left.value.id!="self" or test.left.attr!="path"):
        return ""
    rhs=test.comparators[0]
    if isinstance(test.ops[0],ast.Eq) and isinstance(rhs,ast.Constant):
        return rhs.value if isinstance(rhs.value,str) else ""
    if isinstance(test.ops[0],ast.In) and isinstance(rhs,(ast.Tuple,ast.List)):
        names=[x.value for x in rhs.elts if isinstance(x,ast.Constant) and isinstance(x.value,str)]
        if len(names)==2 and set(names)=={"/semantic/context","/semantic"}:
            return "combined"
    return ""


def _sibling_pairs(tree):
    pairs=[]
    for parent in ast.walk(tree):
        for _,children in ast.iter_fields(parent):
            if isinstance(children,list):
                for i in range(len(children)-1):
                    if (_route(children[i])=="/semantic/context"
                            and _route(children[i+1])=="/semantic"):
                        pairs.append((children[i],children[i+1]))
    return pairs


def _topology(source):
    try:
        tree=ast.parse(source)
    except (SyntaxError,ValueError,TypeError):
        return None,"invalid"
    routes=[_route(node) for node in ast.walk(tree)]
    if (routes.count("combined")==1 and
            routes.count("/semantic/context")==1 and
            routes.count("/semantic")==0):
        return tree,"combined"
    if (routes.count("combined")==0 and
            routes.count("/semantic/context")==1 and
            routes.count("/semantic")==1 and
            len(_sibling_pairs(tree))==1):
        return tree,"split"
    return tree,"other"


def candidate(source_live,source_main):
    """Generate a compile-checked *in-memory* candidate, never write it."""
    lt,layout=_topology(source_live)
    mt,modern=_topology(source_main)
    if not lt or not mt or modern!="combined" or layout!="split":
        return "no"
    if "authorized_semantic_speaker" in source_live:
        return "no"
    old=_sibling_pairs(lt)[0]
    first,second=old
    original_lines=source_live.splitlines(keepends=True)
    old_text="".join(original_lines[first.lineno-1:second.end_lineno])
    # Refuse any unexpected older handler or partial installation.
    for expected in ("from kitty_memory_context_v6 import recall_context",
                     "from kitty_sd_semantic_index import search",
                     'data.get("speaker_id")', 'data.get("query"'):
        if expected not in old_text:
            return "no"
    modern_node=next(n for n in ast.walk(mt) if _route(n)=="combined")
    modern_lines=source_main.splitlines(keepends=True)
    replacement="".join(modern_lines[modern_node.lineno-1:modern_node.end_lineno])
    preview=("".join(original_lines[:first.lineno-1])+replacement+
             "".join(original_lines[second.end_lineno:]))
    try:
        compile(preview,"<kitty-owner-guard-candidate>","exec")
    except (SyntaxError,ValueError,TypeError):
        return "no"
    _,new_layout=_topology(preview)
    if new_layout!="combined":
        return "no"
    return "yes"


def _run(args):
    try:
        p=subprocess.run(args,text=True,capture_output=True,
                         check=False,timeout=8)
        return p.stdout if p.returncode==0 else None
    except (OSError,subprocess.SubprocessError):
        return None


def live_service_source():
    status=_run(["systemctl","--user","show","kitty-memory-v6.service",
                 "-p","ActiveState","-p","MainPID"])
    if status is None:
        return None
    pairs=dict(row.split("=",1) for row in status.splitlines() if "=" in row)
    if pairs.get("ActiveState")!="active" or not pairs.get("MainPID","").isdecimal():
        return None
    pid=int(pairs["MainPID"])
    if pid<=0:
        return None
    base=Path("/proc")/str(pid)
    try:
        parts=(base/"cmdline").read_bytes().split(bytes([0]))
        names=[os.fsdecode(p) for p in parts if p]
        scripts=[p for p in names if p.endswith("/kitty_memory_service.py")
                 or p=="kitty_memory_service.py"]
        if len(scripts)!=1:
            return None
        path=Path(scripts[0])
        if not path.is_absolute():
            path=Path(os.readlink(base/"cwd"))/path
        path=path.resolve(strict=True)
        if path.name!="kitty_memory_service.py" or not path.is_file():
            return None
        return path
    except (OSError,ValueError,UnicodeError):
        return None


def summarize(live,main,available_modules):
    result={}
    tree,layout=_topology(live)
    _,target=_topology(main)
    result["live_service_source"]="readable" if live is not None else "unknown"
    result["live_semantic_handlers"]=layout
    result["github_guard_handlers"]=target
    result["live_owner_guard_marker"]=(
        "present" if live and "authorized_semantic_speaker" in live
        else "absent" if live is not None else "unknown")
    result["candidate_compiles"]=candidate(live,main) if live and main else "no"
    for module in MODULES:
        key=module.replace(".py","")
        result["dependency_"+key]=("present" if module in available_modules else "missing")
    result["patch_applied"]="no"
    result["ready_for_live_restart"]="no"
    return result


def main():
    source_path=live_service_source()
    try:
        live=source_path.read_text(encoding="utf-8") if source_path else None
    except (OSError,UnicodeError):
        live=None
    upstream=_run(["git","show","FETCH_HEAD:server/kitty_memory_service.py"])
    available=set()
    if source_path is not None:
        for module in MODULES:
            try:
                if (source_path.parent/module).is_file():
                    available.add(module)
            except OSError:
                pass
    result=summarize(live,upstream,available)
    print("KITTY_V6_OWNER_GUARD_READ_ONLY_PLAN")
    for key,value in result.items():
        print(f"{key}={value}")
    print("No files, services, credentials or firmware changed.")


if __name__=="__main__":
    main()
