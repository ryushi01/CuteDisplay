# CuteDisplay — hardware-tested base and next milestone (2026-10-28)

## CURRENT VERIFIED BASE — DO NOT BREAK
User confirmed: "ok it works" after installing the S3 UART self-recovery firmware, and explicitly requested it become the project's actual base.

- GitHub: `ryushi01/CuteDisplay`
- **Active development base:** `main` (WAV-only voice + S3 post-upload UART recovery).
- **Immutable rollback:** `stable/2026-10-28-wav-uart-autorecovery-hardware-tested` — snapshot of the exact experimental branch user tested successfully.
- Earlier working fallback: `stable/2026-10-28-wav-tts-buttons-hardware-tested`.
- Development source branch: `feature/post-flash-uart-recovery`; promoted its `firmware/CuteDisplayBrain/CuteDisplayBrain.ino` to main. On main, the build workflow already builds pushes to main; the experiment-specific workflow branch trigger need not be carried over.
- This is a hardware-tested *functionality* checkpoint, not evidence of passing every automated test. Never change stable branches; preserve a rollback when implementing new features.

## Existing hardware and behavior
- Brain: Freenove ESP32-S3, 16 MB flash, 8 MB OPI PSRAM; Arduino-ESP32 core 3.3.12.
- Face: LILYGO T-Display-C5 v13; UART TX S3 GPIO47 -> C5 RX GPIO1, C5 TX GPIO6 -> S3 RX GPIO21, 921600 baud, common ground.
- I2S BCLK GPIO41, WS GPIO42, INMP441 microphone input S3 GPIO1, MAX98357A speaker DIN S3 GPIO2.
- Arduino IDE board settings: ESP32S3 Dev Module, Arduino `setup()/loop()` CPU1 and events CPU0, flash 16 MB, OPI PSRAM, custom partition table, Erase All Flash OFF.
- Normal release path: GitHub Actions workflow `.github/workflows/build-s3-with-c5-update.yml`, script `tools/build_s3_with_c5_update.sh`, artifact `CuteDisplay-CombinedFirmware`; open artifact's `CuteDisplayBrain/CuteDisplayBrain.ino` (not bare repository placeholder firmware).
- **Voice input currently works** using 16 kHz mono **8-bit PCM WAV** to `/api/v1/audio/transcriptions`; falls back to 16-bit PCM WAV. There is **no Opus/Ogg encoder or Opus dependency** in main. Do not reintroduce it without explicit reason.
- **Voice output currently works:** Open WebUI HTTPS `/api/v1/audio/speech` → MP3 decoded using ESP8266Audio 2.4.1 → I2S MAX98357A; WAV playback also supported.
- On C5 GPIO28 BOOT button: short tap interrupts speech and active AI; hold ≥320 ms starts microphone capture, release sends recording. C5 bottom-left status: LISTENING, UPLOADING, THINKING, SPEAKING; AI text continues streaming to face.
- iPhone SwiftUI app controls and telemetry remain working, along with Kitty's voice responses.
- Brain NVS settings (Wi-Fi, Open WebUI endpoint/key), OTA, BLE, displays all preserved.
- All AI/STT/TTS requests go through the **public HTTPS Open WebUI endpoint** on Ubuntu; Ollama and TTS engine are hosted on user's **Mac** behind Open WebUI. **Do not redirect requests to a hypothetical Ubuntu Kokoro service or directly to Mac.**

## Verified post-upload reset improvement
Prior to fix: following S3 Arduino sketch upload, auto-reset often left display in BRAIN DISCONNECTED state and iPhone telemetry absent until the physical S3 RESET was pressed.
Fix: `firmware/CuteDisplayBrain/CuteDisplayBrain.ino` has `recoverFreshBootUART()`. If no C5 frames have arrived since boot, after 12s it reinitializes `Serial1` and retries (9s between attempts; up to 4), using normal HELLO/PROBE exchange. Does not reboot CPU, clear NVS or disrupt established link; user explicitly confirmed this fix works on hardware.
Leave this feature intact when implementing real-time voice mode.

## NEXT PROJECT STEP: REAL-TIME CONVERSATION (Open WebUI voice mode)
User wants **natural real-time, low-latency voice conversation**, akin to Open WebUI's voice mode, without needing the press/record/send/wait/entire-response cycle. This is a **planned** milestone, NOT yet implemented.
- First research current Open WebUI voice/real-time capabilities, protocols and backend compatibility, including its actual real-time endpoint (if any), and whether its browser voice mode is native server streaming or client-side VAD/STT/TTS orchestration. Do not presume OpenAI Realtime API compatibility or invent endpoints.
- Proposed exploration: listening detection/VAD, interruption/barge-in (stop spoken TTS when user speaks), incremental STT and/or utterance segmentation, streamed LLM text, sentence-chunk or streaming TTS playback, optional continuous hands-free mode; continue using public Open WebUI HTTPS and Mac-hosted backends.
- Preserve C5 rendering, existing tap-to-stop / hold-to-talk fallback, audio I2S pin ownership, independent text streaming, Wi-Fi/BLE stability, and UART reset recovery. Ensure no simultaneous incompatible mic/speaker ownership; address echo/feedback and adequate buffering. Avoid introducing a second competing audio codec library.
- Focus on reliable staged rollout with opt-in, instrument latency, and retain WAV-only proven rollback.
- Do not claim this is already supported or implemented; confirm architecture with user once external capability has been investigated.

## Safety and workflow
Work on a new `feature/realtime-voice` branch from `main`; keep the tested stable branch immutable. Build both C5 and S3 via GitHub Actions and verify physical device after each stage. Never label merely compiled firmware stable. Update this handoff after significant changes.

## 2026-10-28 ADDENDUM — Robust MP3 TTS service checkpoint
See [CHECKPOINT_ROBUST_MP3_TTS_2026-10-28.md](CHECKPOINT_ROBUST_MP3_TTS_2026-10-28.md) for the verified production architecture, service managers, rollback, testing and known limits.

**Most recent service state:** MacBook Qwen3-TTS now runs `server_robust:app` on port 8321 with `local.kittychan.qwen3tts` LaunchAgent; Ubuntu `kitty-tts.service` on 8322 provides FFmpeg-encoded MP3 (32 kbps mono) to Open WebUI; MacKitty Realtime on 8765 and Open WebUI Docker are managed services. User confirmed production MP3 speaker-button playback and service cleanup checks. Previous TTS `uuuu` humming was mitigated with per-sentence retries and heuristic audio validation, but more live use is needed to establish long-term reliability.

**Source gap:** The deployed MacBook `server_robust.py` and Ubuntu `/opt/kitty-tts/adapter.py` were not directly fetched into GitHub in this checkpoint. Obtain exact files from the respective hosts before claiming reproducible TTS source backup. Never commit `/etc/kitty-tts.env` or other keys. **Firmware real-time conversation is still planned, not implemented**, and the stable hardware-tested firmware branch must remain untouched.

## 2026-10-28 LATEST — bounded TTS now in production; long conversation worked
**This supersedes the older `server_robust:app` service-status note above.** The MacBook `local.kittychan.qwen3tts` LaunchAgent now launches `server_bounded:app` on port 8321. The bounded version limits per-sentence `max_tokens` to `min(600, max(100, 48 + len(text)*5))`, inherits retries and heuristic validation, and was validated with two standalone successful MP3 requests before being switched into production. The user subsequently reported a **successful long conversation with Kitty-chan**. This is a useful acceptance checkpoint, **not proof that previous intermittent humming or realtime disconnects can never recur**.

Ubuntu adapter 8322 continues 32 kbps MP3 encoding and forwards `temperature=0.7`, `top_k=40`, `top_p=0.9`, `repetition_penalty=1.05`; Open WebUI remains the central endpoint. **Production source files are not yet committed**: `server_bounded.py` is only on the MacBook; `adapter.py` is only on Ubuntu. Exact sanitized code needs to be copied from hosts for a reproducible source checkpoint. See [the updated TTS checkpoint](CHECKPOINT_ROBUST_MP3_TTS_2026-10-28.md). Hardware-tested firmware branches and the separate future real-time firmware feature remain unchanged.
