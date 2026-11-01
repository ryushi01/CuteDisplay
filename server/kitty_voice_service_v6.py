#!/usr/bin/env python3
"""Optional standalone CPU voice-ID HTTP service for Ubuntu.

Keep separate from Open WebUI and from the existing memory-service body cap.
Default localhost only. Requires pre-enrolled, consented speaker profiles
stored as JSON vectors; no automatic enrollment and no raw audio saved.
"""
import argparse
import json
import os
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

MAX_WAV=16_000*2*12+4096
TOKEN=os.environ.get("KITTY_VOICE_TOKEN","")
PROFILES=os.environ.get("KITTY_VOICE_PROFILES_V6","")
_INFERENCE_SLOT=threading.BoundedSemaphore(value=1)

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path!="/identify":
            self.send_error(404);return
        if not TOKEN or self.headers.get("Authorization")!="Bearer "+TOKEN:
            self.send_error(401);return
        length=self.headers.get("Content-Length","")
        if not length.isdecimal() or not 0<int(length)<=MAX_WAV:
            self.send_error(413);return
        if not PROFILES or not os.path.isfile(PROFILES):
            self.send_error(503);return
        if not _INFERENCE_SLOT.acquire(blocking=False):
            self.send_error(503,"voice service busy");return
        try:
            from kitty_voice_id_v6 import pcm16_from_wav,embedding,identify
            samples=pcm16_from_wav(self.rfile.read(int(length)))
            # Prefer the canonical microSD export format; accept legacy
            # private JSON vector dictionaries for staged compatibility.
            with open(PROFILES,encoding="utf-8") as f:
                profile_data=json.load(f)
            if isinstance(profile_data,dict) and profile_data.get("version")==1:
                from kitty_voice_profiles_sd_v6 import validate_profiles
                profiles=validate_profiles(profile_data)
            else:
                profiles=profile_data
            if not isinstance(profiles,dict) or len(profiles)>32:
                raise ValueError("invalid profiles")
            match=identify(embedding(samples),profiles)
            payload=json.dumps({"speaker_id":match.speaker_id,
                               "confidence":match.confidence,
                               "score":match.score}).encode()
            self.send_response(200)
            self.send_header("Content-Type","application/json")
            self.send_header("Cache-Control","no-store")
            self.send_header("Content-Length",str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (ValueError,RuntimeError,OSError,KeyError,TypeError):
            self.send_error(422)
        finally:
            _INFERENCE_SLOT.release()
    def log_message(self,*args):
        pass

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--host",default="127.0.0.1")
    ap.add_argument("--port",type=int,default=8772)
    args=ap.parse_args()
    if not TOKEN or not PROFILES:
        raise SystemExit("Set KITTY_VOICE_TOKEN and KITTY_VOICE_PROFILES_V6")
    ThreadingHTTPServer((args.host,args.port),Handler).serve_forever()
if __name__=="__main__":
    main()
