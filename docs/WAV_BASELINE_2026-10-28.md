# CuteDisplay WAV + spoken replies baseline (2026-10-28)

User hardware-tested `feature/wav-only-baseline-candidate` and confirmed "the base is stable".

- Permanent rollback: `stable/2026-10-28-wav-tts-buttons-hardware-tested`.
- `main` was fast-forwarded to this WAV-only checkpoint (no force pushes).
- Keep **ESP8266Audio 2.4.1** for MP3 playback, no external Opus dependency.
- Voice uploads: 16 kHz mono **8-bit PCM WAV** first; 16-bit PCM WAV fallback if server rejects the first.
- TTS: Open WebUI HTTPS -> MP3 playback via MAX98357A.
- C5 v13: tap-to-stop/hold-to-talk, and bottom-left LISTENING/THINKING/SPEAKING indications.
- Arduino IDE: ESP32S3 Dev Module; Arduino runs on CPU1; events on CPU0; 16MB flash; OPI PSRAM; custom partition table; erase flash **off**.

## After-upload link problem (unverified fix)
On the tested build, Arduino's upload-end S3 reset can leave C5 showing BRAIN DISCONNECTED and the iPhone app without current Brain status until the physical S3 RESET is pressed. Cause has **not** yet been established. Do not claim it is fixed in the stable branch.

Experimental fix: `feature/post-flash-uart-recovery` reinitializes S3 UART1 (not the whole CPU) after 12s if no C5 frame was ever received and retries at most 4 times. It also logs `[S3 UART] No C5 frames since boot...`. Does **not** reset Wi-Fi config, audio tasks, or NVS. Firmware remains untested; if startup hangs before Arduino `loop()`, this mechanism cannot recover and the S3 serial boot log is required.

### Verification
Flash the experimental branch through the combined GitHub Actions artifact. On first USB auto-restart, inspect S3 Serial at 115200 and ensure C5 automatically recovers, iPhone status updates, WAV transcription succeeds, and Kitty speaks. Repeat one more firmware upload; physical S3 RESET should no longer be required. If it fails, restore the stable branch.
