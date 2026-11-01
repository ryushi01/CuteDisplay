#!/usr/bin/env bash
# Install isolated CPU speaker inference dependencies for Kitty V6.
# Does NOT enable speaker identification, fetch the model, or restart services.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
PY="$PWD/.venv-v6/bin/python"
if [[ ! -x "$PY" ]]; then echo "ERROR: Existing .venv-v6 Python is missing"; exit 2; fi
"$PY" -m pip --version >/dev/null || { echo "ERROR: pip missing from .venv-v6"; exit 2; }
"$PY" -m pip install --index-url https://download.pytorch.org/whl/cpu torch torchaudio
"$PY" -m pip install speechbrain
PYTHONDONTWRITEBYTECODE=1 "$PY" - <<'PY'
import torch, numpy, speechbrain
from speechbrain.inference.speaker import EncoderClassifier
print("Speaker dependencies installed")
print("torch:", torch.__version__)
print("CUDA available:", torch.cuda.is_available())
print("SpeechBrain import: OK")
print("NumPy:", numpy.__version__)
PY
echo "Kitty speaker recognition is still DISABLED: model, profile and service configuration required."
