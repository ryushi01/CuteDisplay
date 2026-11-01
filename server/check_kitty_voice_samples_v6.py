#!/usr/bin/env python3
"""Check local enrollment WAV recording levels without sharing or playing audio."""
import argparse
import wave
from pathlib import Path

def main():
    p=argparse.ArgumentParser()
    p.add_argument("files", nargs="+", type=Path)
    a=p.parse_args()
    for path in a.files:
        try:
            with wave.open(str(path), "rb") as w:
                rate, channels, width = w.getframerate(),w.getnchannels(),w.getsampwidth()
                frames = w.getnframes()
                pcm=w.readframes(frames)
            # Python 3.12 supports audioop; compute exact RMS via stdlib.
            import math
            from array import array
            if width != 2 or channels != 1:
                raise ValueError("requires mono PCM16")
            values=array("h")
            values.frombytes(pcm)
            if __import__("sys").byteorder != "little":
                values.byteswap()
            rms=math.sqrt(sum(int(x)*int(x) for x in values)/max(1,len(values)))/32768
            peak=max((abs(x) for x in values),default=0)/32768
            duration=frames/rate
            status=("PASS" if rate==16000 and 1.5<=duration<=8 and rms>=0.008 else "LOW/INVALID")
            print(f"{path.name}: {duration:.2f}s RMS={rms:.4f} peak={peak:.4f} {status}")
        except (OSError,ValueError,EOFError,ZeroDivisionError,wave.Error) as e:
            print(f"{path.name}: ERROR {e}")
if __name__=="__main__":
    main()
