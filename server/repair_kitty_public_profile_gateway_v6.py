#!/usr/bin/env python3
"""Repair already-patched realtime.py without requiring a new Docker mount.

The existing realtime.py file is bind mounted into Open WebUI.
Only edits the public-profile insertion block. Backups and AST validation.
"""
import argparse
import ast
import shutil
from pathlib import Path

OLD_IMPORT = "                        from open_webui.kitty_public_profile_v6 import public_profile_instruction"
OLD_CALL = "                            addition = public_profile_instruction()"
NEW_IMPORT = """                        import json as _kitty_public_json
                        from pathlib import Path as _KittyPublicPath"""
NEW_CALL = """                            _kitty_public_path = _KittyPublicPath('/app/backend/data/kitty-public-profile.json')
                            try:
                                _kitty_public_cfg = _kitty_public_json.loads(
                                    _kitty_public_path.read_text(encoding='utf-8'))
                            except (OSError, ValueError):
                                _kitty_public_cfg = {}
                            _kitty_public_name = _kitty_public_cfg.get('name', '')
                            addition = ''
                            if (_kitty_public_cfg.get('enabled') is True
                                    and isinstance(_kitty_public_name, str)
                                    and 1 <= len(_kitty_public_name) <= 48
                                    and all(c.isalnum() or c in ' -_' for c in _kitty_public_name)):
                                addition = (
                                    '\\nKitty public background profile, not proof of identity: '
                                    'The companion primary user preferred name is ' + _kitty_public_name + '. '
                                    'Do not assume the current caller is this person. '
                                    'Do not reveal or retrieve private memories based on this profile.\\n')
"""
def repair(src):
    if OLD_IMPORT not in src or OLD_CALL not in src:
        if NEW_IMPORT in src and NEW_CALL in src:
            ast.parse(src)
            return src
        raise ValueError('Expected public-profile patch not found; no changes applied')
    if src.count(OLD_IMPORT) != 1 or src.count(OLD_CALL) != 1:
        raise ValueError('Ambiguous gateway patch')
    src = src.replace(OLD_IMPORT, NEW_IMPORT, 1).replace(OLD_CALL, NEW_CALL.rstrip('\n'), 1)
    # JSONCodec.dumps is not guaranteed to exist; use stdlib wire JSON.
    src = src.replace('                                raw = JSONCodec.dumps(event)',
                      '                                raw = _kitty_public_json.dumps(event)', 1)
    ast.parse(src)
    return src

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('gateway', type=Path)
    p.add_argument('--apply', action='store_true')
    args = p.parse_args()
    before = args.gateway.read_text(encoding='utf-8')
    after = repair(before)
    if args.apply and after != before:
        backup = args.gateway.with_name(args.gateway.name + '.before-public-profile-repair')
        shutil.copy2(args.gateway, backup)
        args.gateway.write_text(after, encoding='utf-8')
    print('PUBLIC_PROFILE_REPAIR_' + ('APPLIED' if args.apply else 'VALIDATED'))
