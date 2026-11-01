#!/usr/bin/env python3
"""Kitty X-vector preflight: independent genuine, impostor, and CPU timing metrics.

OFFLINE ONLY. Does not modify live profiles, threshold, or gateway.
Usage: --wav-dir ~/kitty-voice-new --model-dir .../xvector-voxceleb-v6
Optional --impostor-dir contains consented recordings by *other* speakers.
Never infer an identity from these scores. Threshold candidates require impostors.
"""
import argparse
import statistics
import time
import wave
from pathlib import Path

def pcm(path):
    import numpy as np
    with wave.open(str(path), "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (16000,1,2):
            raise ValueError("16kHz mono PCM16 WAV required: " + path.name)
        if not 1.5 <= w.getnframes()/16000 <= 8:
            raise ValueError("duration must be 1.5–8 seconds: " + path.name)
        a=np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype("float32")/32768.
    return a

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--wav-dir", type=Path, required=True)
    p.add_argument("--model-dir", type=Path, required=True)
    p.add_argument("--impostor-dir", type=Path)
    a=p.parse_args()
    if not (a.model_dir/"hyperparams.yaml").is_file():
        p.error("model must be cached on disk")
    files=[a.wav_dir/("voice-%02d.wav"%i) for i in range(1,7)]
    if not all(f.is_file() and not f.is_symlink() for f in files):
        p.error("requires six separate voice-01..voice-06.wav files")
    import numpy as np
    import torch
    from speechbrain.inference.speaker import EncoderClassifier
    started=time.perf_counter()
    model=EncoderClassifier.from_hparams(source=str(a.model_dir),savedir=str(a.model_dir),run_opts={"device":"cpu"})
    print("Model cold-load seconds: %.3f"%(time.perf_counter()-started))
    def extract(path):
        t=time.perf_counter()
        with torch.inference_mode():
            e=model.encode_batch(torch.from_numpy(pcm(path)).unsqueeze(0))
        e=e.detach().cpu().numpy().reshape(-1).astype("float64")
        n=np.linalg.norm(e)
        if not n>0: raise ValueError("zero embedding")
        return e/n,time.perf_counter()-t
    owner=[extract(f) for f in files]
    train=[x[0] for x in owner[:3]]
    def score(v):
        return float(statistics.median(float(np.dot(v,t)) for t in train))
    positives=[score(v) for v,_ in owner[3:]]
    print("Independent genuine scores:",[round(x,4) for x in positives])
    print("Owner embedding CPU seconds:",[round(t,3) for _,t in owner])
    print("Median CPU inference seconds:",round(statistics.median(t for _,t in owner),3))
    print("Worst genuine score:",round(min(positives),4))
    if a.impostor_dir:
        impostors=sorted(f for f in a.impostor_dir.glob("*.wav") if f.is_file() and not f.is_symlink())
        if not impostors: p.error("impostor directory has no WAV recordings")
        negative=[score(extract(f)[0]) for f in impostors]
        print("Impostor scores:",[round(x,4) for x in negative])
        print("Highest impostor score:",round(max(negative),4))
        print("Observed genuine/impostor score gap:",round(min(positives)-max(negative),4))
        print("Candidate separation:", "YES (small sample, not calibrated)" if min(positives)>max(negative) else "NO")
    else:
        print("NO IMPOSTOR DATA: do not activate private-memory authorization.")
    print("No voice profiles, thresholds, recordings or service settings changed.")
if __name__=="__main__": main()
