#!/usr/bin/env python3
"""Kitty V6 read-only shape probe for *running* private Open WebUI realtime.py.

Run in the existing open-webui container with Python; source is never printed,
copied or modified. Do not pass environment variables, process argv, secrets,
tokens, private transcripts or gateway source back to ChatGPT.
"""
import ast
import hashlib
from pathlib import Path

SOURCE = Path("/app/backend/open_webui/routers/audio/realtime.py")

MARKERS = {
    "public_memory_refresh": "kitty.memory.refresh",
    "public_profile": "KITTY_INITIAL_PUBLIC_PROFILE_V6",
    "speaker_observer": "KittySpeakerObserver",
    "speaker_result": "kitty.speaker.result",
    "semantic_request": "kitty.memory.semantic",
    "upstream_speech_started": "input_audio_buffer.speech_started",
    "upstream_speech_stopped": "input_audio_buffer.speech_stopped",
    "upstream_transcription_complete": "conversation.item.input_audio_transcription.completed",
    "owner_grant_reference": "owner_grant",
    "trusted_turn_issuer": "AttestedLiveCall",
    "legacy_voice_gate": "authorized_recall(",
}


def shape(source):
    result = {"source": "readable" if isinstance(source, str) else "unavailable"}
    if source is None:
        result["python_syntax"] = "unknown"
        return {**result, **{k:"unknown" for k in MARKERS}}
    try:
        tree=ast.parse(source)
        result["python_syntax"]="valid"
        for name in ("client_events", "upstream_events", "kitty_speaker_sink"):
            count=sum(1 for x in ast.walk(tree) if isinstance(x,ast.AsyncFunctionDef)
                      and x.name==name)
            result["function_"+name]=("once" if count==1 else
                                      "absent" if count==0 else "multiple")
        for name,pattern in (
                ("client_to_provider_event_forward","await upstream.send_json(event)"),
                ("provider_to_client_event_forward","await ws.send_json(event)")):
            count=source.count(pattern)
            result[name]=("once" if count==1 else
                          "absent" if count==0 else "multiple")
    except (SyntaxError,ValueError):
        result["python_syntax"]="invalid"
    result.update({name:("present" if marker in source else "absent")
                   for name,marker in MARKERS.items()})
    result["trust_issuer_operational"]="not_verified"
    result["safe_to_enable_owner_history"]="no"
    return result


def main():
    try:
        source=SOURCE.read_text(encoding="utf-8")
    except (OSError,UnicodeError):
        source=None
    print("KITTY_V6_GATEWAY_TURN_SHAPE_READ_ONLY")
    for key,value in shape(source).items():
        print(f"{key}={value}")
    print("No container, source, service, audio, firmware or memory changes.")


if __name__=="__main__":
    main()
