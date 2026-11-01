#!/usr/bin/env python3
"""Kitty V6 X-vector shadow profile builder: never activates identity or memory.

Builds a separate protected 0600 profile from voice-01..03 enrollment utterances.
voice-04..06 remain untouched independent holdouts. No profile gets modified
unless --output is an absent regular path; never accepts a production V6 path.
"""
import argparse
import json
import os
import statistics
import tempfile
import time
import wave
from pathlib import Path

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--wav-dir",type=Path,required=True)
    p.add_argument("--model-dir",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--min-genuine",type=float,default=0.965)
    a=p.parse_args()
    if not (a.model_dir/"hyperparams.yaml").is_file():
        p.error("model not cached")
    if not 0.965 <= a.min_genuine <= 1:
        p.error("shadow acceptance floor must be >= 0.965")
    if a.output.is_symlink() or a.output.exists():
        p.error("refusing to replace existing profile")
    if a.output.name != "kitty-xvector-shadow-v6.json":
        p.error("output must be named kitty-xvector-shadow-v6.json")
    files=[a.wav_dir / ("voice-%02d.wav"%i) for i in range(1,7)]
    import numpy as np
    import torch
    from speechbrain.inference.speaker import EncoderClassifier
    model=EncoderClassifier.from_hparams(source=str(a.model_dir), savedir=str(a.model_dir),run_opts={"device":"cpu"})
    vectors=[]
    for f in files:
        if not f.is_file() or f.is_symlink(): p.error("missing regular recording "+str(f))
        with wave.open(str(f)) as w:
            if (w.getframerate(),w.getnchannels(),w.getsampwidth())!=(16000,1,2):
                p.error("bad WAV "+str(f))
            samples=np.frombuffer(w.readframes(w.getnframes()),dtype="<i2").astype("float32")/32768.
        with torch.inference_mode():
            e=model.encode_batch(torch.from_numpy(samples).unsqueeze(0))
        vec=e.detach().cpu().numpy().reshape(-1).astype("float64")
        vec/=np.linalg.norm(vec)
        vectors.append(vec)
    anchors=vectors[:3]
    scores=[statistics.median(float(np.dot(v,a)) for a in anchors) for v in vectors[3:]]
    if min(scores)<a.min_genuine:
        p.error("independent samples failed conservative shadow floor")
    obj={"version":6,"model":"speechbrain/spkrec-xvect-voxceleb","speaker_id":"person:shana",
         "mode":"shadow_only","memory_authorization":False,
         "anchor_embeddings":[v.tolist() for v in anchors],
         "adaptive_embeddings":[],"enrollment_holdout_scores":[round(s,5) for s in scores],
         "min_genuine_floor":a.min_genuine}
    a.output.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd=os.open(str(a.output),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,"w") as out:
            json.dump(obj,out,separators=(",",":"))
    except BaseException:
        a.output.unlink(missing_ok=True)
        raise
    print("Created shadow-only profile:",a.output)
    print("Independent genuine holdout medians:",[round(v,4) for v in scores])
    print("Live speaker profile, gateway, memory access and thresholds UNCHANGED.")
if __name__=="__main__":main()
