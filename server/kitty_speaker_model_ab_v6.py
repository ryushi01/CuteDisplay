#!/usr/bin/env python3
"""Offline A/B verification benchmark for two locally cached SpeechBrain encoders.

Never downloads models, writes a profile, or changes live thresholds. Requires
an explicitly provided second model directory. Separate enrollment and test
recordings; compares medians only; not a substitute for impostor calibration.
"""
import argparse
import itertools
import statistics
from pathlib import Path

def load_wav(path):
    import wave
    import numpy as np
    with wave.open(str(path), "rb") as wav:
        if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (16000, 1, 2):
            raise ValueError("expected 16k mono PCM16: " + path.name)
        audio = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype("float32")/32768.
    if not 1.5 <= len(audio)/16000 <= 8:
        raise ValueError("unexpected audio length: " + path.name)
    return audio

def run(label, model_dir, files):
    import numpy as np
    import torch
    from speechbrain.inference.speaker import EncoderClassifier
    model = EncoderClassifier.from_hparams(source=str(model_dir), savedir=str(model_dir),
                                           run_opts={"device": "cpu"})
    vectors = []
    with torch.inference_mode():
        for f in files:
            vec = model.encode_batch(torch.from_numpy(load_wav(f)).unsqueeze(0))
            vec = vec.detach().cpu().numpy().reshape(-1).astype("float64")
            vectors.append(vec/np.linalg.norm(vec))
    def sim(i,j):
        return float(np.dot(vectors[i],vectors[j]))
    # Chronological holdout: never select using the last three files.
    train = (0,1,2)
    test = (3,4,5)
    enrollment_pairs = [sim(i,j) for i,j in itertools.combinations(train,2)]
    scores = [statistics.median(sim(i,j) for j in train) for i in test]
    print("\n"+label)
    print("Enrollment pair similarities:", [round(v,3) for v in enrollment_pairs])
    print("Independent holdout medians:", [round(v,3) for v in scores])
    print("Worst holdout:", round(min(scores),3))
    return scores

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--wav-dir",type=Path,required=True)
    p.add_argument("--original-model-dir",type=Path,required=True)
    p.add_argument("--alternative-model-dir",type=Path,required=True)
    a=p.parse_args()
    paths=[a.wav_dir/("voice-%02d.wav"%i) for i in range(1,7)]
    for f in paths:
        if not f.is_file() or f.is_symlink():
            p.error("missing or symlink sample: "+str(f))
    for d in [a.original_model_dir,a.alternative_model_dir]:
        if not d.is_dir() or not (d/"hyperparams.yaml").is_file():
            p.error("locally cached SpeechBrain model required: "+str(d))
    run("Current model",a.original_model_dir,paths)
    run("Alternative model",a.alternative_model_dir,paths)
    print("\nRead-only A/B complete. No live settings, profiles or recordings modified.")
if __name__=="__main__":
    main()
