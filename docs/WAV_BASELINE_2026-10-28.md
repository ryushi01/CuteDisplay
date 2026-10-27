# CuteDisplay WAV + spoken replies baseline (2026-10-28)

User hardware-tested `feature/wav-only-baseline-candidate` and confirmed "the base is stable".

- Permanent rollback: `stable/2026-10-28-wav-tts-buttons-hardware-tested`.
- `main` was fast-forwarded to this WAV-only checkpoint (no force pushes).
- Keep **ESP8266Audio 2.4.1** for MP3 playback, no external Opus dependency.
- Voice uploads: 16 kHz mono **8-bit PCM WAV** first; 16-bit PCM WAV fallback if server rejects the first.
- TTS: Open WebUI HTTPS -> MP3 playback via MAX98357A.
- C5 v13: tap-to-stop/hold-to-talk, and bottom-left LISTENING/THINKING/SPEAKING indications.
- Arduino IDE: ESP32S3 Dev Module; Arduino runs on CPU1; events on CPU0; 16MB flash; OPI PSRAM; custom partition table; erase flash **off**.

## After-upload link problem (fixed and hardware-tested)
The WAV-only baseline initially exhibited BRAIN DISCONNECTED after Arduino USB upload auto-reset, requiring physical S3 RESET. User subsequently tested the UART self-recovery fix and confirmed it works. The exact electrical/software root cause has not been independently proven.

Hardware-tested fix (now in `main`): `feature/post-flash-uart-recovery` introduced code that reinitializes S3 UART1 (not the whole CPU) after 12s if no C5 frame was ever received and retries at most 4 times. It also logs `[S3 UART] No C5 frames since boot...`. Does **not** reset Wi-Fi config, audio tasks, or NVS. User confirmed successful hardware behavior. If startup hangs before Arduino `loop()`, this mechanism cannot recover and S3 serial boot logs are still needed.

### Verification
Confirmed functional by user on the experimental branch. Main now includes the fix. Permanent working snapshot: `stable/2026-10-28-wav-uart-autorecovery-hardware-tested`. Next project milestone documented in `docs/NEXT_CHAT_HANDOFF_REALTIME_VOICE_2026-10-28.md`.
