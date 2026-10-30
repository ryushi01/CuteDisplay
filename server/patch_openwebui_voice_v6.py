#!/usr/bin/env python3
"""Guarded optional voice-ID bridge for pinned Open WebUI realtime gateway.

Source integration is intentionally exact-anchor: fail closed if upstream
layout changes. No code is patched unless --apply is explicitly chosen.
"""
import argparse
from pathlib import Path

MARKER="# Kitty V6 bounded voice recognition bridge v1"
AUTH="kitty_sd_memory = auth.get('kitty_sd_memory', '')"
EVENTS="        async def client_events():\n            while True:"
COMMAND="                command = protocol.command(event)"
# The installed gateway currently relays provider events to S3; this anchor
# MUST be verified against the pinned image before applying the patch.
FORWARD="await ws.send_json(event)"

def patch(source):
    if MARKER in source:
        compile(source,"realtime.py","exec")
        return source
    for label,anchor in (("auth",AUTH),("client",EVENTS),
                         ("command",COMMAND),("provider_forward",FORWARD)):
        if source.count(anchor)!=1:
            raise ValueError(f"incompatible realtime gateway: {label}: {source.count(anchor)}")
    source=source.replace(AUTH,AUTH+"\n        "+MARKER+"""
        kitty_voice_v6_enabled = (auth.get('kitty_voice_v6') is True
                                   and auth.get('kitty_expressions') is True)
        kitty_voice_v6 = None
        if kitty_voice_v6_enabled:
            from kitty_realtime_voice_v6 import UtteranceCollector
            kitty_voice_v6 = UtteranceCollector()
""",1)
    source=source.replace(COMMAND,"""                if kitty_voice_v6 is not None and isinstance(event,dict):
                    if event.get('type')=='input_audio_buffer.append':
                        kitty_voice_v6.add(event.get('audio'))
                command = protocol.command(event)""",1)
    # Capture indentation from the *real installed* upstream relay line.
    import re
    matches=list(re.finditer(r"(?m)^(?P<indent>[ ]+)await ws\\.send_json\\(event\\)[ ]*$",source))
    if len(matches)!=1:
        raise ValueError("incompatible event forward indentation")
    match=matches[0]
    indent=match.group("indent")
    child=indent+"    "
    body=[
        "if kitty_voice_v6 is not None and isinstance(event,dict):",
        "    kind = event.get('type')",
        "    if kind=='input_audio_buffer.speech_started':",
        "        kitty_voice_v6.speech_started()",
        "    elif kind=='input_audio_buffer.speech_stopped':",
        "        kitty_voice_v6.speech_stopped()",
        "    elif kind=='conversation.item.input_audio_transcription.completed':",
        "        from kitty_realtime_voice_v6 import recognize_turn",
        "        if isinstance(event.get('item_id'),str):",
        "            import asyncio",
        "            asyncio.create_task(recognize_turn(",
        "                kitty_voice_v6,event['item_id'],ws.send_json,",
        "                transcript=event.get('transcript','')))",
        "await ws.send_json(event)",
    ]
    replacement="\\n".join((indent + line if i==0 else indent+line) for i,line in enumerate(body))
    source=source[:match.start()]+replacement+source[match.end():]
    compile(source,"realtime.py","exec")
    return source

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--source-root",default="/app")
    action=ap.add_mutually_exclusive_group(required=True)
    action.add_argument("--check",action="store_true")
    action.add_argument("--apply",action="store_true")
    args=ap.parse_args()
    path=Path(args.source_root)/"backend/open_webui/routers/audio/realtime.py"
    before=path.read_text()
    after=patch(before)
    if args.apply and after!=before:
        path.write_text(after)
    print("KITTY_VOICE_V6_"+("APPLIED" if args.apply else "VALID"))

if __name__=="__main__":main()
