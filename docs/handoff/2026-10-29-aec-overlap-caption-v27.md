# CuteDisplay C5 v27 / S3 overlap audio checkpoint — 2026-10-29
Feature branch: `feature/realtime-kitty-fullscreen-expressions`. Firmware commit `61bb694420d9df7353d78e37fb32a2081ecafdae`.
Combined build: https://github.com/ryushi01/CuteDisplay/actions/runs/40808468280 (confirm success and artifact availability before flashing).
Frozen hardware-validated voice baseline: `stable/2026-10-29-realtime-voice-hardware-validated` at `78d4abd9`.

## New changes
- Core 0 I2S audio task now continuously sends microphone PCM while speaker plays. A fixed 192-tap NLMS speaker-reference filter (20 ms reference delay) estimates acoustic echo, with adaptation gated during likely double-talk. This is an embedded adaptive filter, **not validated WebRTC AEC3**; no quality guarantee without calibration.
- The previous volume reduction `bargeActive ? 22 : 100` is removed: the speaker output is never ducked for microphone overlap.
- The recent S3 `BrainRealtimeDirect.h` transcript deferral remains: recognized overlapping utterances are stored by Open WebUI item ID and sent to `bridge.respond` after upstream response finishes and buffered speaker PCM drains. This depends on upstream VAD/STT generating transcript events while playback is active.
- C5 v27 draws a tiny persistent black-on-white separated strip in Call Mode, showing latest `YOU:` or `KITTY:` caption sent over `CALL_TEXT` UART, or `WAITING FOR SPEECH`; UTF-8 Japanese clip preserves codepoint boundaries.
- Kitty's existing expression tools and model configuration remain unchanged. AI-selected multi-mood changes were observed only inconsistently by user, so do not mark them reliable.
- This work has **not been hardware validated**. The committed AEC has fixed timing, which may require delay estimation and calibration. Do not tell user it is a production-grade echo canceller.

## Testing
After successful combined firmware CI, extract `CuteDisplay-CombinedFirmware`, upload `CuteDisplayBrain/CuteDisplayBrain.ino` to S3 with Erase All Flash OFF. C5 v27 should UART OTA from previous v26 or earlier. Test: check strip, speak during Kitty's normal-volume reply, look for `OVERLAP_VOICE`, `DEFERRED_VOICE: captured`, and `DEFERRED_VOICE: processing`. If none, inspect serial with sensitive details removed. If echo recursion occurs, roll back to the verified baseline and improve filter delay/energy adaptation.
