#!/usr/bin/env python3
"""Allow authenticated CuteDisplay realtime clients to cancel an active response.
Strict source guard: never change an unknown bridge implementation.
"""
import argparse
import re
from pathlib import Path

ap=argparse.ArgumentParser()
ap.add_argument("--source-root",default="/app")
ap.add_argument("--check",action="store_true")
ap.add_argument("--apply",action="store_true")
args=ap.parse_args()
p=Path(args.source_root)/"backend/open_webui/routers/audio/realtime.py"
source=p.read_text()
marker="# CuteDisplay barge-in response cancellation v1"
if marker in source:
    print("BARGE_IN_PATCH_PRESENT")
    raise SystemExit(0)
start=source.find("async def client_events():")
if start<0: raise SystemExit("Unsupported Open WebUI bridge: no client_events")
end=source.find("async def ",start+10)
chunk=source[start:end if end>=0 else None]
lines=chunk.splitlines(keepends=True)
matches=[i for i,line in enumerate(lines) if "protocol.command(event)" in line]
if len(matches)!=1:
    raise SystemExit("Unsupported bridge command dispatch; refusing patch")
idx=matches[0]
line=lines[idx]
indent=line[:len(line)-len(line.lstrip())]
# Existing verified API-key WebSocket admission precedes client_events.
addition=(indent+marker+"\n"+
          indent+"if isinstance(event, dict) and event.get('type') == 'response.cancel' and set(event) == {'type'}:\n"+
          indent+"    if protocol.responses - protocol.finished_responses:\n"+
          indent+"        await upstream.send_json({'type': 'response.cancel'})\n"+
          indent+"    continue\n")
lines.insert(idx,addition)
new=source[:start]+''.join(lines)+source[end if end>=0 else len(source):]
compile(new,str(p),"exec")
if args.apply:
    p.write_text(new)
print("BARGE_IN_PATCH_VALID" + ("_APPLIED" if args.apply else ""))
