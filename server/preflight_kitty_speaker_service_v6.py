#!/usr/bin/env python3
"""Read-only Kitty V6 recognition deployment preflight.

Checks the active user service's interpreter, runtime module search path and
safe configuration presence. No tokens, audio, embeddings or private paths
are printed. Does not alter systemd units, Docker or the live gateway.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

UNIT="kitty-memory-v6.service"

def cmd(*args):
    p=subprocess.run(args, text=True, capture_output=True, check=False)
    if p.returncode:
        raise RuntimeError("Cannot inspect "+args[0]+" (exit "+str(p.returncode)+")")
    return p.stdout

def main():
    service=cmd("systemctl","--user","show",UNIT,
                "-p","ActiveState","-p","ExecStart","-p","Environment",
                "-p","EnvironmentFiles","-p","FragmentPath")
    fields=dict(line.split("=",1) for line in service.splitlines() if "=" in line)
    print("Memory service active:",fields.get("ActiveState")=="active")
    execstart=fields.get("ExecStart","")
    print("Service Python venv:",".venv-v6/bin/python" in execstart)
    env=fields.get("Environment","")
    print("CPU identification flag in unit environment:",
          "KITTY_SPEAKER_CPU_ENABLED=" in env)
    print("Profile path in unit environment:",
          "KITTY_VOICE_PROFILES_V6=" in env)
    print("Model path in unit environment:",
          "KITTY_SPEAKER_MODEL_DIR=" in env)
    print("Environment file configured:",
          bool(fields.get("EnvironmentFiles","")))
    # Refuse to interpret systemd's escaped ExecStart fields as shell input.
    print("Local CPU interpreter:",Path(".venv-v6/bin/python").is_file())
    print("Local profile exists:",
          (Path.home()/"kitty-v6/private/voice-profiles-v6.json").is_file())
    print("Local model exists:",
          (Path.home()/"kitty-v6/private/speaker-models/espnet-ecapa-v6/hyperparams.yaml").is_file())
    print("Running gateway and memory DB were not modified.")
    print("NOTE: environment files may contain additional settings; inspect privately.")
    print("NOTE: service Python must load torch/speechbrain before endpoint can run.")
if __name__=="__main__":
    main()
