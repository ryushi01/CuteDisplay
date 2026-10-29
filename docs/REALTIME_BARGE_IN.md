# CuteDisplay realtime voice barge-in (2026-10-29)

This is a **direct feature implementation**, not an optional test mode. The existing hardware-validated baseline is preserved on `stable/2026-10-29-realtime-voice-hardware-validated` (commit `78d4abd9`).

## Changes
- S3 INMP441 capture stays active during Kitty speaker output; a sustained near-end microphone level greater than the output-audio reference threshold for eight 20 ms frames triggers barge-in.
- On detection, S3 immediately clears the PSRAM speaker ring, suppresses stale incoming audio, sends the standard `response.cancel` Realtime event, and starts streaming the new microphone speech. Existing speech recognition and `bridge.respond` process the user's new request.
- C5 continues to receive the existing `CALL_LISTENING`, `CALL_THINKING`, and `CALL_SPEAKING` states; no extra display firmware protocol.
- The Open WebUI image extension now applies `server/patch_openwebui_barge_in.py` after the existing API-key and Kitty-expression patch. This accepts only an exact `{"type":"response.cancel"}` event inside an already authenticated `client_events` session and forwards it upstream.
- No hardware pinout or TTS provider change. This is NOT acoustic echo cancellation; a speaker-aware energy gate reduces feedback but is not a guarantee against self-triggering in all acoustic environments.

## Install
1. First rebuild/redeploy the Open WebUI server image with the existing guarded `server/upgrade_kitty_expressions.sh` from this feature branch. It is designed to check the original Compose layout and create a verified backup. If its compatibility guard fails, **stop** rather than manually patch a running container.
2. Download the successful combined firmware artifact built from the same or newer feature commit, extract, upload `CuteDisplayBrain/CuteDisplayBrain.ino` only to the S3 using ESP32 3.3.12, 16 MB, OPI PSRAM, Custom partitions. Keep **Erase All Flash disabled**.
3. Start Call Mode. While Kitty is speaking, speak a short, clearly louder phrase. Kitty should stop speaker playback and transcribe the new phrase. In S3 Serial Monitor 115200 look for `[CALL] BARGE_IN: local speech detected, stopping Kitty`.
4. If the WebSocket fails after `BARGE_IN`, the server cancellation forwarding patch may not be installed/accepted; check the server's verified rollout before repeating. If Kitty repeatedly interrupts herself, the audio threshold requires calibration or proper AEC.

## Boundaries
- Firmware compilation alone is not a proof of acoustic reliability or upstream cancellation support.
- `audio.realtime.model=local`, voice `Ono_Anna`, transcription `whisper-1`; Mac Qwen3.5 9B tool test does not prove voice interruption support.
- The frozen stable voice baseline is not modified.
