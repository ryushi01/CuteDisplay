# CuteDisplay realtime voice — hardware-validated stable checkpoint

Date: 2026-10-29 (Asia/Tokyo)
Project: ryushi01/CuteDisplay
Status: **User-accepted hardware baseline; frozen for recovery**
Validated code commit: `78d4abd9e227ad20c956a471024e6e858c72fe0c`
Frozen branch: `stable/2026-10-29-realtime-voice-hardware-validated`

## Acceptance evidence

- GitHub Actions [combined firmware build #40727085322](https://github.com/ryushi01/CuteDisplay/actions/runs/40727085322) **completed successfully** from the exact validated code SHA.
- Published artifact name: `CuteDisplay-CombinedFirmware`, artifact ID `12833149118`.
- GitHub ZIP digest (SHA-256): `0e99db37cfaf562ba16de78e2597617190fa5ae6acf6d02170b5c6b488ad0e3e`.
- Downloaded ZIP `CuteDisplay-Realtime-Speaker-Buffer-Fix-78d4abd9.zip` was verified: archive test succeeded, `SOURCE_COMMIT.txt` matches validated SHA, and all 9 `SHA256SUMS.txt` entries match extracted files.
- After uploading that build, the user explicitly confirmed: **"worked very well and very responsive ! no cut or anything."** This is real-device acceptance of the previously failing realtime conversation / voice playback path.
- Previous observed faults were I2S initialization memory pressure and `SPEAKER_QUEUE_OVERFLOW` during `CALL_SPEAKING`. The accepted build includes the reduced-memory I2S driver, PSRAM speaker ring, and nonfatal bounded overflow handling.
- Normal long-hold manual PTT activity display was previously corrected after `CALL_ERROR`; no new user-confirmed retest of every recovery/UI state is claimed in this acceptance statement.
- Native Open WebUI HTTPS/WSS API-key authentication and 24 kHz ping/pong had separately passed their existing server probe.

## Preserve these exact design choices

1. Existing **dual-board** design: LILYGO T-Display-C5 screen and Freenove ESP32-S3 Brain.
2. Same S3 pin plan: GPIO41 BCLK / GPIO42 WS shared; GPIO1 INMP441 microphone data; GPIO2 MAX98357A speaker data. No rewiring required.
3. 24 kHz PCM16 mono realtime audio over existing secure Open WebUI WebSocket, authenticated with user-scoped saved `sk-` key from iPhone BLE configuration. Do not add a gateway, secondary URL, OTP, or password to firmware.
4. PSRAM-backed microphone and speaker buffering. Speaker ring prefers 24 seconds and falls back to 12 or 6 seconds; extreme overflow remains **nonfatal** and is counted via `call status`, with oldest pending samples skipped as the bounded-latency fallback.
5. C5 v22 automatic version-checked UART OTA from S3 combined image; OTA waits for idle and verifies installed C5 version. Do **not** reinstate any manual `c5 ota enable` gate.
6. Short-press C5 left button toggles realtime Call Mode. Long-hold while Call Mode is off remains manual STT/PTT. Failed calls must not permanently mask PTT Listening/Thinking/Speaking labels.
7. Avoid regressions in clock overlay, BLE reconnect, iPhone app, Japanese Kitty rendering, previous text chat, and existing manual audio paths.

## Known limits — do not misstate as validated

- User confirmed responsive uninterrupted conversation on their hardware; continuous multi-hour uptime, heavy network degradation, all fault recovery paths, and every UI state were not separately tested.
- Current acoustic path is **half-duplex** during speech, with the mic muted during assistant playback and a 300 ms tail. No acoustic echo cancellation or barge-in yet.
- Buffer overflow intentionally favors staying connected over perfect fidelity; check `playback_skipped_ms` if speech ever sounds truncated.
- Github Actions verifies compilation and bundling, not all hardware behavior. Real-device success is the user's separate acceptance evidence.

## Future changes: mandatory baseline protection

- Treat this checkpoint as **read-only**. Do not update, rebase, reset, or force-push this stable branch.
- Perform future features/fixes on a distinct `feature/` branch from the stable SHA. Do not move the known-good baseline.
- Keep this exact artifact ZIP and checksum as a firmware recovery reference. The GitHub Actions artifact may eventually expire.
- Do not replace this build on real hardware without a specific reason, a verified firmware artifact, and a rollback plan.
- Use `call status` for diagnostics: `playback_buffer_ms`, `playback_peak_ms`, `playback_skipped_ms`, `underruns`, `mic_dropped`.
