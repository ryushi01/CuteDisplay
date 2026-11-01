#!/usr/bin/env python3
"""Version-guarded, opt-in Open WebUI V6 semantic context on session setup.

This patch augments the already-patched Kitty SD memory context. It runs one
bounded semantic lookup at session startup; per-turn voice retrieval is still
future work. It NEVER enables itself for ordinary Open WebUI browser clients.
"""
import argparse
from pathlib import Path

MARKER="# CuteDisplay semantic V6 opt-in context v1"
ANCHOR="kitty_sd_memory = auth.get('kitty_sd_memory', '')"
VALIDATION="            kitty_sd_memory = ''"

def patch(source):
    if MARKER in source:
        compile(source,"realtime.py","exec")
        return source
    if source.count(ANCHOR)!=1 or source.count(VALIDATION)!=1:
        raise ValueError("Incompatible Kitty realtime source: missing SD auth validation")
    insertion="""            kitty_sd_memory = ''
        # CuteDisplay semantic V6 opt-in context v1
        # A device token proves device access, not the identity of a speaker.
        if auth.get('kitty_semantic_v6') is True and kitty_expressions:
            query = auth.get('kitty_semantic_query', '')
            if isinstance(query, str) and 1 <= len(query.encode('utf-8')) <= 300:
                from kitty_semantic_bridge_v6 import bounded_semantic_context
                kitty_sd_memory, kitty_semantic_source = await bounded_semantic_context(
                    query, kitty_sd_memory, timeout=0.18)
                kitty_sd_memory = kitty_sd_memory.encode('utf-8')[:1800].decode('utf-8','ignore')
"""
    result=source.replace(VALIDATION,insertion,1)
    compile(result,"realtime.py","exec")
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source-root",default="/app")
    a=p.add_mutually_exclusive_group(required=True)
    a.add_argument("--check",action="store_true")
    a.add_argument("--apply",action="store_true")
    args=p.parse_args()
    path=Path(args.source_root)/"backend/open_webui/routers/audio/realtime.py"
    old=path.read_text()
    new=patch(old)
    if args.apply and new!=old:
        path.write_text(new)
    print("KITTY_SEMANTIC_V6_"+("APPLIED" if args.apply else "VALID"))
if __name__=="__main__":main()
