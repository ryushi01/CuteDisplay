#!/usr/bin/env python3
"""Stage the SpeechBrain ECAPA model in Kitty's private directory.

Does not touch running services, enable recognition, enroll speakers,
or copy anything into the public repository.
"""
import os
from pathlib import Path
from huggingface_hub import snapshot_download

revision = "a9f171aee6b706ea72b35dfe6d9dbd07947c2555"
target = Path.home() / "kitty-v6/private/speaker-models/espnet-ecapa-v6"
target.mkdir(parents=True, exist_ok=True)
target.chmod(0o700)
snapshot_download(
    repo_id="speechbrain/spkrec-ecapa-voxceleb",
    revision=revision,
    local_dir=str(target),
    allow_patterns=["hyperparams.yaml", "*.ckpt", "label_encoder.txt"],
)
required = ["hyperparams.yaml", "embedding_model.ckpt",
            "mean_var_norm_emb.ckpt", "classifier.ckpt",
            "label_encoder.txt"]
missing = [name for name in required if not (target / name).is_file()]
if missing:
    raise SystemExit("Model incomplete: " + ", ".join(missing))
yaml = target / "hyperparams.yaml"
src = yaml.read_text()
old = "pretrained_path: speechbrain/spkrec-ecapa-voxceleb"
if old not in src and f"pretrained_path: {target}" not in src:
    raise SystemExit("Unexpected hyperparams pretrained_path; refusing rewrite")
if old in src:
    yaml.write_text(src.replace(old, f"pretrained_path: {target}", 1))
print("Model directory prepared:", target)
print("To warm the model without changing services:")
print(f" KITTY_SPEAKER_MODEL_DIR={target} PYTHONPATH=server .venv-v6/bin/python server/kitty_speaker_cpu_v6.py --warm")
print("Recognition remains DISABLED until explicitly configured.")
