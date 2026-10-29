# CuteDisplay checkpoint — 2026-10-29 — realtime Kitty expressions

## Fixed checkpoint
- Feature branch: `feature/realtime-kitty-fullscreen-expressions`
- Firmware commit before this documentation checkpoint: `8b396ec8cfd6c3b4410c25490d9f34a692f644b9`.
- Exact successful GitHub Actions run: https://github.com/ryushi01/CuteDisplay/actions/runs/40799220742
- Combined firmware artifact: https://github.com/ryushi01/CuteDisplay/actions/runs/40799220742/artifacts/12864649768 (`CuteDisplay-CombinedFirmware`; check artifact expiry).
- Earlier hardware-validated voice baseline MUST remain unchanged: `stable/2026-10-29-realtime-voice-hardware-validated`, commit `78d4abd9`.

## Architecture and tests already confirmed
- LILYGO T-Display C5: 320x170 fullscreen Kitty face in realtime Call Mode, normal saved mascot restored outside Call Mode.
- Freenove ESP32-S3: existing 24 kHz I2S microphone/speaker realtime audio, WebSocket to Open WebUI, UART to C5, C5 firmware embedded in S3 combined build.
- Ubuntu ai-server Open WebUI container: `cutedisplay/openwebui:kitty-expressions-20261029000738` was seen healthy; custom `set_expression` source, `kitty_expressions` opt-in and automatic tool choice were confirmed present on the running server.
- Realtime database settings observed: `audio.realtime.model=local`, `audio.realtime.voice=Ono_Anna`, `audio.realtime.transcription_model=whisper-1`. This does **not** identify the actual upstream voice engine, and it is not necessarily the Mac Ollama model.
- Language model and TTS run on the user's Mac; Mac Ollama `qwen3.5:9b` advertises `tools`. A harmless tool calling test emitted `set_expression(sad)`, then `set_expression(excited)`, then final text in one logical response. This proves sequential text tool calling, **not** mid-stream spoken emotion switches.
- Open WebUI realtime server's `bridge.animation.respond` continuation at inspected lines ~300–307 sends only `CHAT_TOOL` (or no tools on delegated continuation). The voice instructions favor an expression before speech and at most one per answer. Mid-speech expression switching is **unverified and not reliably enabled**. Do not claim otherwise.

## Current code changes (compiled, not hardware validated)
- C5 v24 (`firmware/CuteDisplay/C5FirmwareVersion.h`): full-screen face with locally animated thinking expression when `CALL_THINKING` is received, independent of server/tool emotion selection. Existing eight AI mood IDs 0..7: neutral, happy, sad, angry, hungry, sleepy, excited, shy.
- C5 no longer auto-resets emotion after 10 seconds of speech; S3 controls return to happy at end of reply.
- S3 response lifecycle now debounces apparently empty audio/tool gaps by 2 seconds before resetting mood to happy; this was implemented to address user report that moods flashed for only a split second. The precise behavior remains **untested on hardware**.
- Existing I2S audio pipeline/pinout, iOS application and model personality prompt not changed by this checkpoint.
- New code is in CI successful run above, but passing compilation is not hardware acceptance.

## Installation/recovery
- Download the *exact* combined artifact from run 40799220742, extract it on Mac, and open its `CuteDisplayBrain/CuteDisplayBrain.ino` in Arduino IDE; upload to S3 only. Arduino ESP32 core 3.3.12, ESP32S3 Dev Module, 16 MB flash, OPI PSRAM, Custom partition layout using included `partitions.csv`; WebSockets 2.7.2 and ESP8266Audio 2.4.1.
- **Erase All Flash OFF**: keep S3 stored Wi-Fi and Open WebUI API key.
- C5 embedded v24 is newer than v23 and should update automatically through existing UART OTA when connected/idle; no manual C5 USB update is normally needed.
- After firmware installation: start a call with short C5 left press; validate listening -> animated thinking -> speaking with a selected mood held through reply -> normal happy after audio. Stop with another short press. Do not change server as part of firmware-only testing.
- If new firmware fails, reupload previously validated v22 S3 combined firmware from stable commit `78d4abd9` without erasing flash. C5 may remain at higher version; only perform direct C5 recovery if specifically needed.
- Server installation state must be checked on host before any further patch. Safeguarded `server/upgrade_kitty_expressions.sh` is intended for the documented `/home/ryushi/docker-compose.yaml` deployment; do not rerun blindly. Keep verified data backups and rollback yaml.

## Next work
1. Verify the latest v24+S3 buffer-grace firmware *on actual hardware*, especially emotion persistence, idle reset and thinking face. Do not label hardware validated until the user confirms.
2. Decide whether a deterministic emotion-during-speech mechanism is worth implementing. Preserve responsive audio. Native upstream tool interleaving remains unproven; do not confuse the Mac's sequential Ollama tool calls with realtime voice interleaving.
3. If changing Open WebUI, use a safely backed-up incremental deployment and verify exact server source; avoid changing model settings/prompt unless requested.
4. User's original Kitty persona prompt was good; no full rewrite necessary. It prohibits emojis in character output, not visual screen drawings.
