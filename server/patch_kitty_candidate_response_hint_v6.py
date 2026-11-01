#!/usr/bin/env python3
"""Optional probable-speaker hint only on existing response.create commands.

Never creates another provider event, modifies audio, or authorizes recall.
Strict matching and AST validation. Must be deployed alongside matching
kitty_realtime_gateway_observer_v6.py in the Open WebUI container.
"""
import argparse
import ast
import shutil
from pathlib import Path

MARKER = "# KITTY_XVECTOR_CONVERSATION_HINT_V6"
ANCHOR = "                command = protocol.command(event)"
HOOK = """
                # KITTY_XVECTOR_CONVERSATION_HINT_V6
                if kitty_speaker_observer is not None:
                    try:
                        _kh = kitty_speaker_observer.candidate_hint
                        if (_kh is not None and _kh[1] == 'person:shana'\n                                and __import__('time').monotonic() < kitty_speaker_observer.candidate_expires):
                            # Only annotate a response the client was already
                            # authorized to create. Never emit a new response.
                            _kit_items = command if isinstance(command, list) else [command]
                            for _kit_item in _kit_items:
                                if (isinstance(_kit_item, dict)
                                        and _kit_item.get('type') == 'response.create'
                                        and isinstance(_kit_item.get('response'), dict)):
                                    _kit_response = _kit_item['response']
                                    _kit_old = _kit_response.get('instructions', '')
                                    if isinstance(_kit_old, str):
                                        _kit_note = (
                                            'Speaker recognition hint for this utterance only: '
                                            'the voice is a probable match to Shana, not verified identity. '
                                            'You may say it sounds like Shana if directly asked, but do not '
                                            'claim certainty, mention biometric scores, or reveal personal '
                                            'memories based on this hint. Keep your tone natural.')
                                        _kit_response['instructions'] = (_kit_old + '\\n' + _kit_note)[:1800]\n                                        print('[KITTY_CANDIDATE_RESPONSE] hint_attached=true memory_authorization=disabled', flush=True)
                    except Exception:
                        pass  # Optional hint must never interrupt voice
"""

def patch(src):
    if MARKER in src:
        ast.parse(src)
        return src
    if src.count(ANCHOR) != 1:
        raise ValueError('Expected single protocol.command event; unchanged')
    result = src.replace(ANCHOR, ANCHOR + HOOK, 1)
    ast.parse(result)
    return result

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('gateway', type=Path)
    p.add_argument('--apply', action='store_true')
    args = p.parse_args()
    old = args.gateway.read_text(encoding='utf-8')
    new = patch(old)
    if args.apply and new != old:
        shutil.copy2(args.gateway, args.gateway.with_name(args.gateway.name + '.before-candidate-hint'))
        args.gateway.write_text(new, encoding='utf-8')
    print('KITTY_CANDIDATE_HINT_' + ('APPLIED' if args.apply else 'VALIDATED'))
