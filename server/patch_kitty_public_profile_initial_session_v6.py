#!/usr/bin/env python3
"""Attach the optional non-sensitive Kitty profile to the server-generated
initial OpenAI realtime session.update. No speaker authorization changes.

Strict source anchors, AST check, idempotent, backup before write.
"""
import argparse
import ast
import shutil
import re
from pathlib import Path

MARKER = "# KITTY_INITIAL_PUBLIC_PROFILE_V6"
ANCHOR = "            await upstream.send_json(\n                {\n                    'type': 'session.update',"
EXPRESSION = "                                (config.get('audio.realtime.prompt_template') or DEFAULT_REALTIME_CALL_PROMPT_TEMPLATE)"
INSERT = """
            # KITTY_INITIAL_PUBLIC_PROFILE_V6
            _kitty_initial_profile = ''
            try:
                import json as _kitty_pjson
                from pathlib import Path as _KittyPPath
                _kitty_pcfg = _kitty_pjson.loads(
                    _KittyPPath('/app/backend/data/kitty-public-profile.json')
                    .read_text(encoding='utf-8'))
                if isinstance(_kitty_pcfg, dict) and _kitty_pcfg.get('enabled') is True:
                    _kitty_pname = _kitty_pcfg.get('name')
                    if (isinstance(_kitty_pname, str)
                            and 1 <= len(_kitty_pname) <= 48
                            and all(c.isalnum() or c in ' -_' for c in _kitty_pname)):
                        _kitty_initial_profile = (
                            '\\nKitty non-sensitive public profile: '
                            'The primary user preferred name is ' + _kitty_pname + '. '
                            'This is general background only, NOT proof of current speaker identity. '
                            'If asked who the primary user is, answer using this configured name. '
                            'Do not assume the current caller is that person, '
                            'and never reveal private memories based on this profile.\\n')
            except (OSError, ValueError, TypeError):
                pass
"""

def patch(src):
    if MARKER in src:
        ast.parse(src)
        return src
    # Locate a unique upstream initial session update followed by its initial
    # prompt template. Ignore differences in indentation and whitespace.
    update = re.search(
        r"(?m)^(?P<indent>[ ]*)await upstream[.]send_json[(]\s*"
        r"\{\s*['\\"]type['\\"]\s*:\s*['\\"]session[.]update['\\"]",
        src,
    )
    expression = re.search(
        r"(?m)^(?P<indent>[ ]*)[(]config[.]get[(]"
        r"['\\"]audio[.]realtime[.]prompt_template['\\"]"
        r"[)]\s+or\s+DEFAULT_REALTIME_CALL_PROMPT_TEMPLATE[)]",
        src,
    )
    if (not update or not expression or
            len(re.findall(r"['\\"]type['\\"]\s*:\s*['\\"]session[.]update['\\"]", src)) != 1 or
            len(re.findall(r"DEFAULT_REALTIME_CALL_PROMPT_TEMPLATE[)]", src)) != 1 or
            update.start() >= expression.start() or
            expression.start() - update.start() > 2500):
        raise ValueError("Initial session update not uniquely located; unchanged")
    indent = update.group("indent")
    block = "".join(indent + line + "\n" if line else "\n"
                    for line in INSERT.strip("\n").splitlines())
    src = src[:update.start()] + block + src[update.start():]
    # Match fresh expression after insertion; insert immediately after it.
    expression = re.search(
        r"(?m)^(?P<indent>[ ]*)[(]config[.]get[(]"
        r"['\\"]audio[.]realtime[.]prompt_template['\\"]"
        r"[)]\s+or\s+DEFAULT_REALTIME_CALL_PROMPT_TEMPLATE[)]", src)
    pos = expression.end()
    src = src[:pos] + "\n" + expression.group("indent") + "+ _kitty_initial_profile" + src[pos:]
    ast.parse(src)
    return src

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('gateway', type=Path)
    p.add_argument('--apply', action='store_true')
    args = p.parse_args()
    old = args.gateway.read_text(encoding='utf-8')
    new = patch(old)
    if args.apply and new != old:
        shutil.copy2(args.gateway, args.gateway.with_name(args.gateway.name+'.before-initial-public-profile'))
        args.gateway.write_text(new, encoding='utf-8')
    print('INITIAL_PUBLIC_PROFILE_' + ('APPLIED' if args.apply else 'VALIDATED'))
