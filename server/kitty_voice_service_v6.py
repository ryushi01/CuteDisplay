#!/usr/bin/env python3
"""Optional standalone CPU voice-ID HTTP service for Ubuntu.

Keep separate from Open WebUI and from the existing memory-service body cap.
Default localhost only. Requires pre-enrolled, consented speaker profiles
stored as JSON vectors; no automatic enrollment and no raw audio saved.
"""
import argparse
import json
import os
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

MAX_WAV=16_000*2*12+4096
TOKEN=os.environ.get("KITTY_VOICE_TOKEN","")
PROFILES=os.environ.get("KITTY_VOICE_PROFILES_V6","")

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
        try:
            from kitty_voice_id_v6 import pcm16_from_wav,embedding,identify
            samples=pcm16_from_wav(self.rfile.read(int(length)))
            with open(PROFILES,encoding="utf-8") as f:
                profiles=json.load(f)
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
