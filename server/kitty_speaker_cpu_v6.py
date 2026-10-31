#!/usr/bin/env python3
"""Opt-in CPU speaker embedding enrollment and comparison. Never owner authentication.

Uses SpeechBrain ECAPA-TDNN on CPU; requires a locally cached model. No
automatic downloads in the live HTTP handler. Voice data stays on the host.
"""
import argparse
import base64
import io
import json
import os
import re
import stat
import tempfile
import threading
import wave
from pathlib import Path

MODEL_DIR = os.environ.get("KITTY_SPEAKER_MODEL_DIR", "")
PROFILE_PATH = os.environ.get("KITTY_VOICE_PROFILES_V6", "")
MODEL_LOCK = threading.Lock()
_MODEL = None
MAX_WAV_BYTES = 300000
MIN_SECONDS = 1.5
MAX_SECONDS = 8.0
THRESHOLD = 0.82
MARGIN = 0.10
ID_PATTERN = re.compile(r"^person:[A-Za-z0-9_-]{1,48}$")


def _encoder():
    global _MODEL
    with MODEL_LOCK:
        if _MODEL is None:
            if not MODEL_DIR or not Path(MODEL_DIR).is_dir():
                raise RuntimeError("speaker_model_not_configured")
            from speechbrain.inference.speaker import EncoderClassifier
            _MODEL = EncoderClassifier.from_hparams(
                source=MODEL_DIR, savedir=MODEL_DIR, run_opts={"device": "cpu"})
        return _MODEL


def _embedding(raw):
    if len(raw) > MAX_WAV_BYTES:
        raise ValueError("audio_too_large")
    with wave.open(io.BytesIO(raw), "rb") as wav:
        rate, channels, width = wav.getframerate(), wav.getnchannels(), wav.getsampwidth()
        frames = wav.getnframes()
        if (rate != 16000 or channels != 1 or width != 2 or
                not MIN_SECONDS <= frames / rate <= MAX_SECONDS):
            raise ValueError("requires_16khz_mono_pcm16_1.5_to_8_seconds")
        pcm = wav.readframes(frames)
    import numpy as np
    import torch
    samples = np.frombuffer(pcm, dtype="<i2").astype("float32") / 32768.
    if float(np.sqrt(np.mean(samples * samples))) < 0.008:
        raise ValueError("audio_too_quiet")
    with torch.inference_mode():
        vec = _encoder().encode_batch(torch.from_numpy(samples).unsqueeze(0))
        vec = vec.detach().cpu().numpy().reshape(-1).astype("float64")
    norm = float(np.linalg.norm(vec))
    if not norm > 1e-8:
        raise ValueError("invalid_embedding")
    return (vec / norm).tolist()


def _load():
    if not PROFILE_PATH:
        raise RuntimeError("voice_profiles_disabled")
    path = Path(PROFILE_PATH)
    if path.is_symlink():
        raise RuntimeError("symlink_profile_refused")
    if not path.exists():
        return {"version": 6, "speakers": {}}
    if path.stat().st_mode & 0o077:
        raise RuntimeError("voice_profile_permissions_must_be_0600")
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result.get("speakers"), dict):
        raise RuntimeError("invalid_profiles")
    return result


def _save(value):
    path = Path(PROFILE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".voice-", dir=path.parent)
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def enroll(speaker_id, wav_paths):
    if not ID_PATTERN.fullmatch(speaker_id):
        raise ValueError("invalid_person_id")
    if len(wav_paths) < 3:
        raise ValueError("at_least_three_explicit_samples_required")
    embeddings = [_embedding(Path(p).read_bytes()) for p in wav_paths[:8]]
    with MODEL_LOCK:
        profiles = _load()
        profiles["version"] = 6
        profiles["speakers"][speaker_id] = {
            "embeddings": embeddings, "consent": "local_explicit_enrollment",
            "role": "speaker_not_authenticated_owner"
        }
        _save(profiles)
    return {"enrolled": speaker_id, "samples": len(embeddings)}


def identify(wav_b64):
    if not isinstance(wav_b64, str) or len(wav_b64) > 410000:
        raise ValueError("invalid_audio_size")
    raw = base64.b64decode(wav_b64, validate=True)
    vector = _embedding(raw)
    import numpy as np
    with MODEL_LOCK:
        speakers = _load()["speakers"]
    scores = []
    for sid, profile in speakers.items():
        if not ID_PATTERN.fullmatch(sid) or not isinstance(profile, dict):
            continue
        samples = profile.get("embeddings", [])
        if len(samples) < 3:
            continue
        try:
            matches = [float(np.dot(vector, np.array(v, dtype="float64")))
                       for v in samples if len(v) == len(vector)]
        except (TypeError, ValueError):
            continue
        if len(matches) >= 3:
            scores.append((float(np.median(matches)), sid))
    scores.sort(reverse=True)
    best = scores[0] if scores else (0., "unknown")
    second = scores[1][0] if len(scores) > 1 else -1.
    # Conservative rejection, including ambiguity between enrolled people.
    accepted = best[0] >= THRESHOLD and best[0] - second >= MARGIN
    return {"speaker_id": best[1] if accepted else "unknown",
            "confidence": "probable" if accepted else "unknown",
            "score": round(best[0], 3) if accepted else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--enroll", help="person:ID; explicit opt-in only")
    ap.add_argument("--wav", action="append", default=[])
    ap.add_argument("--warm", action="store_true")
    args = ap.parse_args()
    if args.warm:
        _encoder()
        print("CPU speaker encoder ready")
    elif args.enroll:
        print(json.dumps(enroll(args.enroll, args.wav)))
    else:
        ap.error("provide --warm or --enroll with at least three --wav files")


if __name__ == "__main__":
    main()
