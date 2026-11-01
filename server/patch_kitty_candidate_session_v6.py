#!/usr/bin/env python3
"""Wire bounded X-vector candidate recognition to live session instructions.

The hint only says 'probable voice match'; it never changes speaker_id,
memory authorization, access controls, or audio handling. Refuse source drift.
"""
import argparse
import ast
import shutil
from pathlib import Path

MARKER = "# KITTY_CANDIDATE_SESSION_CALLBACK_V6"
ANCHOR = "                kitty_speaker_observer = KittySpeakerObserver(\n                    kitty_speaker_sink, enabled=True)"
READY = "            if event.get('type') != 'session.updated':"
READY_INSERT = """            _kitty_base_instructions = (
                event.get('session', {}).get('instructions', '')
                if isinstance(event.get('session'), dict) else ''
            )
"""
CALLBACK = """        # KITTY_CANDIDATE_SESSION_CALLBACK_V6
        _kitty_base_instructions = ((event.get('session') or {}).get('instructions') or '')
        _kitty_candidate_active = False
        _kitty_candidate_generation = 0

        async def kitty_candidate_hint(item_id, speaker_id):
            nonlocal _kitty_candidate_active, _kitty_candidate_generation
            if speaker_id != 'person:shana':
                return
            if _kitty_candidate_active:
                return
            _kitty_candidate_generation += 1
            generation = _kitty_candidate_generation
            if not _kitty_base_instructions:
                return
            note = (
                '\\nNon-authorizing voice observation: the last completed utterance '
                'was a probable voice match to Shana. You may acknowledge that '
                'the voice sounds like Shana if directly asked, in a natural way. '
                'This is NOT authentication. Never disclose personal memories '
                'or claim certain identity from this hint.\\n'
            )
            try:
                await upstream.send_json({
                    'type': 'session.update',
                    'session': {'instructions': _kitty_base_instructions + note},
                })
                _kitty_candidate_active = True
                async def expire():
                    await asyncio.sleep(20)
                    if generation == _kitty_candidate_generation:
                        await kitty_candidate_clear()
                asyncio.create_task(expire())
                print('[KITTY_CANDIDATE_SESSION] hint_sent=true memory_authorization=disabled', flush=True)
            except Exception as exc:
                print('[KITTY_CANDIDATE_SESSION] error=%s' % type(exc).__name__, flush=True)

        async def kitty_candidate_clear():
            nonlocal _kitty_candidate_active
            if not _kitty_candidate_active or not _kitty_base_instructions:
                return
            try:
                await upstream.send_json({
                    'type': 'session.update',
                    'session': {'instructions': _kitty_base_instructions},
                })
                _kitty_candidate_active = False
            except Exception:
                pass

"""
def patch(src):
    if MARKER in src:
        ast.parse(src)
        return src
    if src.count(ANCHOR) != 1 or src.count(READY) != 1:
        raise ValueError('Gateway anchors not unique; no changes made')
    src = src.replace('        async def kitty_speaker_sink(event):', CALLBACK + '        async def kitty_speaker_sink(event):', 1)
    src = src.replace(ANCHOR,
        "                kitty_speaker_observer = KittySpeakerObserver(\n"
        "                    kitty_speaker_sink, enabled=True,\n"
        "                    on_candidate=kitty_candidate_hint)\n"
        "                    # Candidate hint expires after 20 seconds", 1)
    ast.parse(src)
    return src

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('gateway', type=Path)
    p.add_argument('--apply', action='store_true')
    args = p.parse_args()
    before = args.gateway.read_text()
    after = patch(before)
    if args.apply and after != before:
        shutil.copy2(args.gateway, args.gateway.with_name(args.gateway.name+'.pre-candidate-session'))
        args.gateway.write_text(after)
    print('KITTY_CANDIDATE_SESSION_' + ('APPLIED' if args.apply else 'VALIDATED'))
