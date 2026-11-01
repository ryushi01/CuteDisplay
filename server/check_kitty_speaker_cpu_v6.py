#!/usr/bin/env python3
"""Offline, secret-free CPU speaker readiness report. No service mutation."""
import importlib.util
import os
from pathlib import Path

for module in ("torch", "torchaudio", "numpy", "speechbrain"):
    print(f"{module}: {'available' if importlib.util.find_spec(module) else 'missing'}")
model = os.environ.get("KITTY_SPEAKER_MODEL_DIR", "")
profile = os.environ.get("KITTY_VOICE_PROFILES_V6", "")
print("model_path:", "set" if model else "unset")
print("model_files:", "present" if model and Path(model).is_dir() and
      (Path(model)/"hyperparams.yaml").is_file() else "not_ready")
print("profiles_path:", "set" if profile else "unset")
print("profiles_file:", "present" if profile and Path(profile).is_file() else "not_ready")
print("recognition_enabled:", os.environ.get("KITTY_SPEAKER_CPU_ENABLED") == "1")
print("No service configuration has been changed.")
