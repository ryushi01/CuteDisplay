#!/usr/bin/env python3
"""Make candidate voice hints non-disruptive in the realtime gateway.

The observer keeps its candidate matching and per-response hint. Do not send
session.update asynchronously on a candidate result: this can race realtime
response creation. Never change owner authorization or audio forwarding.
"""
import argparse
from pathlib import Path

START="        async def kitty_candidate_hint(item_id, speaker_id):"
END="        async def kitty_speaker_sink(event):"
REPLACEMENT="""        # KITTY_CANDIDATE_STABLE_V6
        # Keep callback active, but do not mutate the realtime upstream session.
        # The observer retains a TTL-bounded candidate_hint, which is read by
        # the existing response.create hint injection further below.
        async def kitty_candidate_hint(item_id, speaker_id):
            if speaker_id == 'person:shana':
                print('[KITTY_CANDIDATE_STABLE] candidate_seen=true authorization=disabled', flush=True)

        async def kitty_candidate_clear():
            # No session override to clear. The observer handles TTL and
            # clears candidate state when it expires.
            return

"""
def patch(src):
    if "KITTY_CANDIDATE_STABLE_V6" in src:
        return src
    if src.count(START)!=1 or src.count(END)!=1:
        raise ValueError("Unknown gateway candidate structure; no modifications")
    a=src.index(START)
    b=src.index(END,a)
    if not (a<b and "on_candidate=kitty_candidate_hint" in src):
        raise ValueError("Candidate callbacks not enabled; no modifications")
    out=src[:a]+REPLACEMENT+src[b:]
    compile(out,"realtime.py","exec")
    return out

def main():
    p=argparse.ArgumentParser()
    p.add_argument("route",type=Path)
    route=p.parse_args().route
    old=route.read_text(encoding="utf-8")
    new=patch(old)
    if new==old:
        print("Candidate hint already stabilized")
        return
    bak=route.with_name(route.name+".before-candidate-stability-v6.bak")
    if bak.exists():
        raise SystemExit("Backup exists; no modifications")
    bak.write_text(old,encoding="utf-8")
    route.write_text(new,encoding="utf-8")
    print("Candidate hints now use per-response context; live session updates disabled")

if __name__=="__main__":
    main()
