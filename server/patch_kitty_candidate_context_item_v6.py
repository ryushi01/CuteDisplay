#!/usr/bin/env python3
"""Replace rejected live session.update candidate callback with context item.

Uses gateway's existing conversation.item.create pattern. Candidate context
is only conversational, not memory authorization. No response.create generated.
Requires existing KITTY_CANDIDATE_SESSION_CALLBACK_V6 source.
"""
import argparse
import ast
import shutil
from pathlib import Path

MARKER = "# KITTY_CANDIDATE_CONTEXT_ITEM_V6"
START = "        async def kitty_candidate_hint(item_id, speaker_id):"
END = "        async def kitty_speaker_sink(event):"

REPLACEMENT = '''        # KITTY_CANDIDATE_CONTEXT_ITEM_V6
        _kitty_candidate_item_id = None

        async def kitty_candidate_hint(item_id, speaker_id):
            nonlocal _kitty_candidate_item_id
            if speaker_id != 'person:shana' or _kitty_candidate_item_id is not None:
                return
            # Only non-sensitive, non-authorizing information enters the model.
            # There is no new response request; automatic voice timing stays
            # controlled by the existing provider and S3.
            try:
                candidate_item = 'kitty_candidate_hint_v6'
                await upstream.send_json({
                    'type': 'conversation.item.create',
                    'item': {
                        'id': candidate_item,
                        'type': 'message',
                        'role': 'system',
                        'content': [{
                            'type': 'input_text',
                            'text': (
                                'Temporary voice recognition observation, not authentication: '
                                'The immediately preceding speaker voice is a probable match '
                                'to Shana, Kitty primary user. If explicitly asked, you can '
                                'naturally say it sounds like Shana, but not that identity '
                                'is verified. Do not disclose private memories on this basis. '
                                'This observation can be wrong.'
                            ),
                        }],
                    },
                })
                _kitty_candidate_item_id = candidate_item
                print('[KITTY_CANDIDATE_CONTEXT_ITEM] sent=true authorization=disabled', flush=True)
            except Exception as exc:
                print('[KITTY_CANDIDATE_CONTEXT_ITEM] error=%s' % type(exc).__name__, flush=True)

        async def kitty_candidate_clear():
            nonlocal _kitty_candidate_item_id
            if _kitty_candidate_item_id is None:
                return
            previous = _kitty_candidate_item_id
            _kitty_candidate_item_id = None
            try:
                await upstream.send_json({
                    'type': 'conversation.item.delete',
                    'item_id': previous,
                })
            except Exception:
                pass

'''

def patch(src):
    if MARKER in src:
        ast.parse(src)
        return src
    if src.count(START) != 1 or src.count(END) != 1:
        raise ValueError('Gateway callback layout mismatch; unchanged')
    start = src.index(START)
    end = src.index(END, start)
    if "KITTY_CANDIDATE_SESSION_CALLBACK_V6" not in src:
        raise ValueError('Expected candidate callback missing')
    out = src[:start] + REPLACEMENT + src[end:]
    if out.count('on_candidate=None)') == 1:
        out = out.replace('on_candidate=None)', 'on_candidate=kitty_candidate_hint)', 1)
    elif out.count('on_candidate=kitty_candidate_hint)') != 1:
        raise ValueError('Observer initialization not found')
    # The context item must be retracted when a new utterance starts.
    out = out.replace(
        'on_candidate=kitty_candidate_hint)',
        'on_candidate=kitty_candidate_hint,\n'
        '                    on_candidate_clear=kitty_candidate_clear)', 1)
    ast.parse(out)
    return out

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('gateway', type=Path)
    p.add_argument('--apply', action='store_true')
    a = p.parse_args()
    old = a.gateway.read_text()
    new = patch(old)
    if a.apply and new != old:
        shutil.copy2(a.gateway, a.gateway.with_name(a.gateway.name + '.pre-candidate-context-item'))
        a.gateway.write_text(new)
    print('KITTY_CONTEXT_ITEM_' + ('APPLIED' if a.apply else 'VALIDATED'))
