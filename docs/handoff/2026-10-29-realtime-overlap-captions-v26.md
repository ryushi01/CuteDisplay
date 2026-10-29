# Realtime conversation / C5 captions checkpoint — October 29, 2026

Feature branch: `feature/realtime-kitty-fullscreen-expressions`.
Frozen hardware-validated rollback: `stable/2026-10-29-realtime-voice-hardware-validated` (commit `78d4abd9`).

## What has changed
- Keep recording and transmitting microphone frames during Kitty speech (no cancellation); provider voice activity detection/transcription may capture a new question while Kitty is still speaking.
- After `conversation.item.input_audio_transcription.completed`, the S3 retains the latest transcribed input item while a response or buffered speaker PCM is active. It sends `bridge.respond` when the existing reply is finished.
- Speaker ducking: when S3 detects substantial local mic energy over the playback reference, lower speaker amplification during overlap without stopping playback. The detector is a heuristic, **not** calibrated acoustic echo cancellation, and could miss quiet speech or respond to speaker leakage.
- C5 v26 receives a new UART `CALL_TEXT` side channel. A compact transcript strip at bottom-right of the full-screen face shows the latest recognized `YOU:` utterance or, if provided by upstream, `KITTY:` spoken transcript. UTF-8 payloads limited to 78 bytes, not a full scrolling log. Normal C5 message mode unaffected.
- Queued expression delivery: several explicit model-selected emotions are retained in an eight-entry S3 queue and shown sequentially during speech, minimum 850ms each. C5-local Thinking face remains unchanged. These emotions are **not synchronized with individual words**.
- No new server patch needed beyond the previous deployed realtime gateway for this update. Realtime server still reports `audio.realtime.model=local` voice `Ono_Anna` transcription model `whisper-1`.

## Installation
- Download the completed `CuteDisplay-CombinedFirmware` from GitHub Actions for the latest commit after this checkpoint.
- Arduino IDE upload **only the S3** project inside the artifact. ESP32 core 3.3.12; ESP32S3 Dev Module; 16MB flash; OPI PSRAM; custom partitions in bundle; keep **Erase All Flash OFF**.
- C5 v26 should update automatically over existing UART OTA once the S3 is flashed.
- Test with one brief overlapping question while Kitty speaks. Observe the bottom transcript and UART serial diagnostics:
  - `[CALL] OVERLAP_VOICE` means local overlap detected.
  - `[CALL] DEFERRED_VOICE: captured during reply` means upstream transcribed a voice item.
  - `[CALL] DEFERRED_VOICE: processing saved utterance` means S3 requested the deferred reply.
- If YOU text never appears, provider transcription is not receiving intelligible overlapped speech. The simple energy gate alone cannot guarantee success: proper far-end audio reference AEC or reducing speaker volume/using headphones is then needed.

## Validation status
Code changes are not hardware validated. GitHub Actions compilation is required and must be checked before flashing. Do not treat this checkpoint as a confirmed working hardware fix until user tests.
