"""Optional, bounded X-vector shadow diagnostics. NO authentication output.

The worker logs a provisional match/unknown verdict and cosine similarity. It never sends IDs to Kitty,
updates a profile, stores audio, or permits memory access. At most one job is
pending/running; no additional tasks can queue in the live audio path.
"""
import io
import json
import os
import statistics
import threading
import time
import wave
from pathlib import Path

_GATE = threading.BoundedSemaphore(1)
_LOCK = threading.Lock()
_MODEL = None
_ANCHORS = None
# Provisional, calibrated from only one other speaker. Never an auth threshold.
SHADOW_THRESHOLD = 0.957
_WARM_STARTED = False

def _init():
    global _MODEL, _ANCHORS
    if _MODEL is not None:
        return
    model_dir=Path(os.environ["KITTY_XVECTOR_MODEL_DIR"])
    profile_path=Path(os.environ["KITTY_XVECTOR_SHADOW_PROFILE"])
    if not model_dir.is_dir() or profile_path.is_symlink():
        raise ValueError("invalid_shadow_configuration")
    if profile_path.stat().st_mode & 0o077:
        raise ValueError("shadow_profile_permissions")
    profile=json.loads(profile_path.read_text())
    if profile.get("mode")!="shadow_only" or profile.get("memory_authorization") is not False:
        raise ValueError("not_shadow_only")
    import numpy as np
    anchors=profile.get("anchor_embeddings",[])
    if len(anchors)<3: raise ValueError("missing_anchors")
    anchors=[np.asarray(v,dtype="float64") for v in anchors]
    from speechbrain.inference.speaker import EncoderClassifier
    model=EncoderClassifier.from_hparams(source=str(model_dir),savedir=str(model_dir),
                                        run_opts={"device":"cpu"})
    _ANCHORS=anchors
    _MODEL=model

def warm_async():
    """Preload the model independently of audio capture; nonblocking."""
    global _WARM_STARTED
    if os.environ.get("KITTY_XVECTOR_SHADOW_ENABLED") != "1":
        return False
    with _LOCK:
        if _WARM_STARTED:
            return True
        _WARM_STARTED = True
    def load():
        try:
            with _LOCK:
                started = time.monotonic()
                _init()
                print("[KITTY_XVECTOR_SHADOW] warm_ready_ms=%d" % round((time.monotonic()-started)*1000), flush=True)
        except Exception as exc:
            print("[KITTY_XVECTOR_SHADOW] warm_error=%s" % type(exc).__name__, flush=True)
    threading.Thread(target=load, daemon=True, name="kitty-xvector-warm").start()
    return True


def recognize_candidate(audio, *, threshold=None):
    """Opt-in experimental identity match. Caller controls any authorization.

    Higher threshold than the diagnostic shadow 0.957; this is NOT calibrated
    security-grade voice authentication. Safe failure returns unknown.
    """
    if threshold is None:
        try:
            threshold = float(os.environ.get("KITTY_XVECTOR_EXPERIMENTAL_THRESHOLD", "0.970"))
        except ValueError:
            threshold = 0.970
    # Reject unsafe or invalid configuration; never weaken automatically.
    if not 0.965 <= threshold <= 1.0:
        return {"speaker_id":"unknown","confidence":"unknown","score":None}
    if not _GATE.acquire(blocking=False):
        return {"speaker_id":"unknown","confidence":"unknown","score":None}
    try:
        with _LOCK:
            _init()
            with wave.open(io.BytesIO(audio), "rb") as wav:
                if (wav.getframerate(),wav.getnchannels(),wav.getsampwidth()) != (16000,1,2):
                    raise ValueError("bad_audio")
                import numpy as np
                import torch
                samples=np.frombuffer(wav.readframes(wav.getnframes()),dtype="<i2").astype("float32")/32768.
            if not 1.5 <= len(samples)/16000 <= 8:
                raise ValueError("bad_duration")
            started=time.monotonic()
            with torch.inference_mode():
                v=_MODEL.encode_batch(torch.from_numpy(samples).unsqueeze(0))
            v=v.detach().cpu().numpy().reshape(-1).astype("float64")
            v/=np.linalg.norm(v)
            score=statistics.median(float(np.dot(v,a)) for a in _ANCHORS)
            ms=round((time.monotonic()-started)*1000)
            accepted=score >= threshold
            print("[KITTY_XVECTOR_EXPERIMENTAL] match=%s score=%.4f threshold=%.3f inference_ms=%d" %
                  (accepted,score,threshold,ms),flush=True)
            return {"speaker_id":"person:shana" if accepted else "unknown",
                    "confidence":"probable" if accepted else "unknown",
                    "score":round(score,3) if accepted else None}
    except Exception as exc:
        print("[KITTY_XVECTOR_EXPERIMENTAL] error=%s"%type(exc).__name__,flush=True)
        return {"speaker_id":"unknown","confidence":"unknown","score":None}
    finally:
        _GATE.release()


def _run(audio):
    try:
        with _LOCK:
            _init()
            with wave.open(io.BytesIO(audio),"rb") as wav:
                if (wav.getframerate(),wav.getnchannels(),wav.getsampwidth())!=(16000,1,2):
                    return
                import numpy as np
                import torch
                samples=np.frombuffer(wav.readframes(wav.getnframes()),dtype="<i2").astype("float32")/32768.
            if not 1.5<=len(samples)/16000<=8: return
            started=time.monotonic()
            with torch.inference_mode():
                v=_MODEL.encode_batch(torch.from_numpy(samples).unsqueeze(0))
            v=v.detach().cpu().numpy().reshape(-1).astype("float64")
            v/=np.linalg.norm(v)
            score=statistics.median(float(np.dot(v,a)) for a in _ANCHORS)
            ms=round(1000*(time.monotonic()-started))
            verdict = "candidate_match" if score >= SHADOW_THRESHOLD else "unknown"
            print("[KITTY_XVECTOR_SHADOW] verdict=%s score=%.4f threshold=%.3f inference_ms=%d memory_authorization=disabled" % (verdict,score,SHADOW_THRESHOLD,ms),flush=True)
    except Exception as e:
        print("[KITTY_XVECTOR_SHADOW] error=%s"%type(e).__name__,flush=True)
    finally:
        _GATE.release()

def submit(audio):
    if os.environ.get("KITTY_XVECTOR_SHADOW_ENABLED")!="1":
        return False
    if not isinstance(audio,bytes) or len(audio)>300000 or not _GATE.acquire(blocking=False):
        return False
    try:
        threading.Thread(target=_run,args=(audio,),daemon=True,name="kitty-xvector-shadow").start()
        return True
    except Exception:
        _GATE.release()
        return False

# Optional warmup during service startup; harmless if already started.
warm_async()
