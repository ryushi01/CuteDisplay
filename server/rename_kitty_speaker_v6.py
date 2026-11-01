#!/usr/bin/env python3
"""Rename an enrolled Kitty speaker ID without modifying voice embeddings.

Operates only on the private profile store supplied by KITTY_VOICE_PROFILES_V6.
Creates a permission-preserving backup. Refuses destination collisions.
Does not reassign historical semantic memories or enable the live gateway.
"""
import argparse
import json
import os
import shutil
import stat
from datetime import datetime
from pathlib import Path
from kitty_speaker_cpu_v6 import ID_PATTERN, _load, _save

def rename(old, new):
    if not ID_PATTERN.fullmatch(old) or not ID_PATTERN.fullmatch(new) or old == new:
        raise ValueError("invalid_or_identical_speaker_ids")
    source = os.environ.get("KITTY_VOICE_PROFILES_V6")
    if not source:
        raise RuntimeError("voice_profile_path_required")
    path = Path(source)
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise RuntimeError("unsafe_voice_profiles")
    profiles = _load()
    speakers = profiles["speakers"]
    if old not in speakers or new in speakers:
        raise ValueError("missing_old_or_destination_exists")
    backup = path.with_name(path.name + ".backup-before-rename-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    if backup.exists():
        raise FileExistsError(str(backup))
    shutil.copy2(path, backup)
    os.chmod(backup, stat.S_IRUSR | stat.S_IWUSR)
    before = json.dumps(speakers[old], sort_keys=True)
    speakers[new] = speakers.pop(old)
    _save(profiles)
    assert json.dumps(_load()["speakers"][new], sort_keys=True) == before
    print("Renamed:", old, "->", new)
    print("Embeddings: unchanged")
    print("Backup:", backup)
    print("Historical semantic memories: unchanged")
    print("Live speaker recognition: unchanged")

if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--from-id", required=True)
    p.add_argument("--to-id", required=True)
    a=p.parse_args()
    rename(a.from_id,a.to_id)
