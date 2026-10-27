# CuteDisplay handoff — S3 AI + Kitty Japanese working checkpoint

**Date:** 2026-10-27 (Japan time)  
**Repository:** https://github.com/ryushi01/CuteDisplay  
**User-confirmed milestone:** "ai works and its even kinda faster than I expected !" following the C5 v10 Japanese font fix. Clock is visible and S3 has a valid IP. **No further changes to firmware have been made after this tested SHA.**

## Start here for a new chat

> Continue CuteDisplay from the working S3-owned AI milestone. Read `docs/handoff/2026-10-27-ai-working.md`, use `feature/s3-ai-streaming` for further work, preserve `stable/2026-10-27-s3-ai-japanese-working` unchanged, and modify GitHub directly. The S3 receives HTTPS Open WebUI SSE responses and relays UTF-8 over UART to C5, which renders Japanese locally. Check GitHub Actions for each firmware build. User confirmed this works. Never erase S3 flash or directly flash C5 unless OTA bootstrap/recovery is needed.

## Immutable rollback reference

- **Checkpoint branch:** `stable/2026-10-27-s3-ai-japanese-working`
- **Exact firmware commit:** `416a6212f90a6339fd64c48e41ec341b844d5be3`
- **Successful GitHub Actions build:** https://github.com/ryushi01/CuteDisplay/actions/runs/40476408769
- **Version:** C5 v10. The combined firmware image includes both S3 app and C5 OTA image.
- **Development branch:** `feature/s3-ai-streaming` (same firmware SHA at checkpoint time; documentation changes may move HEAD).
- **Prior audio stable branch:** `stable/2026-10-27-audio-tested`, SHA `baf2b0b98dfa12b2d732c4618c060ea55e92d804`.
- **Main branch is deliberately not merged** with experimental S3 AI: retain the old baseline until a deliberate release/merge decision.

## Confirmed board arrangement and wiring

**S3 Brain:** Freenove ESP32-S3 CAM (16 MB Flash/8 MB PSRAM), programmed as Arduino IDE ESP32S3 Dev Module; custom 16 MB partitions; OPI PSRAM; esp32 Arduino core 3.3.12. Wi-Fi, bonded/encrypted iPhone BLE, HTTPS AI client, I²S microphone and speaker.

**C5 Kitty:** LILYGO T-Display-C5 v1.0, ST7789 320×170, existing display controller, clock/mascots/typewriting/Japanese text/battery HUD. **No SPI link retrofit was performed and no new inter-board wires are required.**

| Connection | S3 | C5 |
|---|---|---|
| UART S3 → C5 | TX GPIO47 | RX GPIO1 |
| UART C5 → S3 | RX GPIO21 | TX GPIO6 |
| Ground | GND | GND |
| UART speed | 921600 baud | 921600 baud |

**Audio on S3:** INMP441 and MAX98357A share I²S BCLK GPIO41, WS GPIO42; INMP441 data → S3 GPIO1; S3 GPIO2 → MAX98357A data; 8Ω / 1W speaker connected to amp SPK± only. Audio beep and short record/play were user tested before this AI milestone. Do not reassign pins casually. Current S3 and C5 are on different local networks than phone; phone-to-S3 configuration uses encrypted Bluetooth, and S3 independently accesses internet Open WebUI via its own Wi-Fi.

## Working software architecture

1. **iPhone SwiftUI:** connects to bonded S3 Brain using encrypted BLE; provisions Open WebUI URL/model/test API key and submits prompts over acknowledged, max 96 UTF-8 byte BLE commands (`AI:BEGIN:<field>:<length>`, hex `AI:DATA:`, `AI:END`, `AI:GO`). An `AI:PING` diagnostic produces `[AI CTRL] Ping: ACK:AI_PONG`; user verified this. The phone is no longer the HTTP/SSE inference client.
2. **S3 Brain:** `firmware/CuteDisplayBrain/BrainAI.h` provisions settings to NVS, asynchronously calls Open WebUI over verified HTTPS with public CA bundle and `stream:true`, parses SSE chunks, queues incremental UTF-8 text, and sends `AI_BEGIN/AI_DATA/AI_END` over acknowledged UART. Model is configured via Open WebUI workspace ID; Ollama and voice services run on user's MacBook, Open WebUI on AI-SERVER.
3. **AI endpoint:** Open WebUI base URL `https://ragnarok-project.com`, chat endpoint `https://ragnarok-project.com/api/chat/completions`. **Never commit the API key**; use revocable testing credentials. User confirmed URL directly opens Open WebUI.
4. **S3 Wi-Fi:** uses DHCP with explicit `IPAddress(0,0,0,0)`, **not** `INADDR_NONE` (previously caused 255.255.255.255 IP/gateway). Validates station IP, recovers if invalid. User confirmed valid assigned IP after fix.
5. **S3 time:** `BrainClock.h` starts SNTP after Wi-Fi; tries gateway then public NTP servers. Hourly synchronization, UTC internal time used for HTTPS cert validation. Sends formatted `HH:mm` over UART with `CLOCK` frame. iPhone timezone picker with saved S3 POSIX timezone selection (Japan default, UTC, Central Europe, US Eastern/Pacific, UK, Sydney). C5 displays clock just left of Bluetooth icon; user confirmed visible.
6. **C5 graphics:** mascot and all LCD rendering remain on C5, independent of Open WebUI. On `AI_BEGIN`, resets streaming bubble and starts typewriter; on `AI_DATA`, appends text; on `AI_END`, marks generation finished. Mouth animation follows character revelation. Bubble uses fixed-size font and scrolls visible lines upward.
7. **Japanese font v10:** C5 `C5JapaneseFont.h` is generated at build time by `tools/generate_c5_japanese_font.py` using Ubuntu `fonts-noto-cjk` and `python3-pil`. C5 embedded fallback covers Japanese characters, using existing cached iPhone glyphs first; necessary because S3 streaming no longer sends iPhone-generated glyph bitmaps. Previous photo showed scattered Hiragana as only five built-in glyphs existed; user confirmed AI works after new font build. Build emits generated header in downloadable artifact, not in source-tree placeholder.

## How to build and flash safely

- GitHub Actions workflow: `.github/workflows/build-s3-with-c5-update.yml` builds C5, packages C5 app in S3 application, checks compile, and publishes `CuteDisplay-CombinedFirmware` artifact.
- Build script `tools/build_s3_with_c5_update.sh` clones LILYGO display drivers, generates Japanese font header, compiles **both** Arduino sketches. Current workflow build: https://github.com/ryushi01/CuteDisplay/actions/runs/40476408769 (success).
- Download and extract artifact. Open **`CuteDisplayBrain/CuteDisplayBrain.ino` FROM ARTIFACT**, not repo's source sketch (which has placeholder embedded-image header).
- Arduino IDE esp32 core 3.3.12; ESP32S3 Dev Module; Flash 16 MB, OPI PSRAM, Custom partition scheme; choose **S3** USB port. Keep **Erase All Flash disabled** so Wi-Fi credentials/NVS persist.
- Flash **S3 only**. S3 UART OTA updates C5 automatically when C5 version increments. **Never upload `lcd/lcd.ino` to S3** (wrong board GPIO and possible crash). Direct C5 USB only for recovery.
- After flashing, monitor **S3 USB Serial at 115200**, check C5 upgrade acknowledgement and display. Keep S3/C5 ground and UART connections secure.
- For Swift changes, copy matching `ios/CuteDisplay/ContentView.swift` and `ios/CuteDisplay/BluetoothManager.swift` into Xcode. Firmware CI does **not** validate Xcode; build the iOS app locally.

## Current confirmation and limitations

**Confirmed by user:**
- S3↔C5 UART and C5 automatic OTA worked; BLE reconnect fixed in prior milestone.
- Microphone and audio amplifier local playback functional in prior stable tests.
- AI query works using S3-owned Open WebUI connection and C5 displays response quickly; recent user feedback explicitly positive.
- Correct S3 IP, NTP clock visible on Kitty top status bar.
- C5 v10 combined firmware CI completed successfully.

**Not yet explicitly retested/confirmed:**
- Whether mascot mouth stops precisely when text reveal finishes (user was asked but hasn't answered).
- Perfect typewriter pacing relative to AI token rate, scroll layout for longer Japanese text, CJK fallback coverage, behavior under extended answers.
- Multi-turn AI conversation history, cancellation/retry UX, phone display of stream status, and voice integration with MacBook backend.
- Credential provisioning is encrypted BLE Just Works (no verified MITM protection); API key is in Preferences/NVS and is not presumed encrypted at rest. Use limited-scope revocable test key, and harden before shipping.
- Embedded Japanese font license notice distribution should be reviewed; generator uses Noto Sans CJK (OFL), font binary itself should never be shared from system environment.
- Local user report is not an end-to-end test suite; do not claim every feature is verified.

## Where to work next

1. **First preserve checkpoint.** If implementing any update, branch from feature and keep stable checkpoint fixed.
2. Ask user for actual behavior or logs only when needed to debug a concrete issue; prefer modifying code and successful CI builds over repetitive instructions.
3. Prioritize mascot talking animation ends exactly after typewriting; polish scrolling, wrapping, and stream pacing. Text is already fast enough; **do not add extra SPI connections without measurements**.
4. Improve iPhone AI status and multi-turn conversation; secure credential lifecycle; multilingual C5 glyph edge cases.
5. Plan future local audio + remote MacBook speech services separately; no assumption of an existing directly usable ESP32 voice API.
6. Update this handoff whenever major features change, preserving exact tested commit and firmware/action references.

## Continuation — conversational memory (development, not stable)
- S3 BrainAI.h now holds up to **4 completed user/assistant exchanges in RAM**, replayed as `messages` before the new prompt. Failed/incomplete responses are not committed. Stored assistant text is capped at 1,600 UTF-8 bytes per answer; longer replies may have incomplete remembered context.
- iPhone Home > Kitty AI offers **New conversation**, sending the acknowledged `AI:NEW` command. The S3 rejects reset if an AI request is busy; verify S3 command status before assuming it succeeded. Follow-up prompts continue the chat by default.
- Context is **volatile**: an S3 reboot clears it. The C5 v11 two-minute return to regular Message Mode does **not** clear conversation context.
- Updated development files: `firmware/CuteDisplayBrain/BrainAI.h` and `ios/CuteDisplay/ContentView.swift`. No S3/C5 pins changed, C5 version stays v11. Do not change `stable/2026-10-27-s3-ai-japanese-working`.
- **Verification pending:** GitHub connector did not expose a firmware Actions run for the latest commits, and Xcode compilation/hardware testing are not verified. Check the combined workflow run before flashing.

## Continuation — 24-hour conversation expiration
- S3 saves up to 4 completed turns in a separate `brain-chat` NVS namespace; the lifetime is 86,400 seconds from the first successful completed exchange (not a sliding window). NTP/valid system time is needed before loading context. The original 24-hour deadline survives S3 reboot. Check for expiry every minute while idle and before subsequent prompts.
- `AI:NEW` clears conversation history and its persisted slots; failed requests are not saved. Normal C5 message timeout remains 2 minutes after `AI_END`.
- This is not a server-side Open WebUI chat creation workflow: S3 supplies the messages array on each direct completion request without `chat_id`. Other Open WebUI logging/filter persistence policies must be checked separately.
- Latest development is **not confirmed by firmware CI or a hardware test**. Build and inspect artifacts before flashing. Stable branch remains untouched.

## 2026-10-27 hardware acceptance checkpoint — C5 v11 + S3 24-hour chat

**User reported 9/9 PASS on physical hardware**: S3 valid DHCP IP, C5 clock, BLE reconnect, C5 v11 OTA, Japanese AI text, return to last regular message after 2 minutes, follow-up memory, S3 reboot memory persistence, and New Conversation clearing.

**New immutable rollback branch:** `stable/2026-10-27-c5-v11-conversation-24h-hardware-tested`
**Exact code SHA:** `a5dc985e94e89d44219d1dcaae839d55514a458e`
**Previous stable v10 remains:** `stable/2026-10-27-s3-ai-japanese-working` at `416a6212f90a6339fd64c48e41ec341b844d5be3`.

This is a **user-confirmed hardware acceptance checkpoint**, not an independently verified GitHub Actions build: connector commit checks did not return Actions evidence. The reported checks do not independently establish that expiration occurs exactly at 24 hours, nor long-run stability. Do not modify the new stable branch; continue enhancements on `feature/s3-ai-streaming`.

**Next phases requested:** (2) AI error/status reporting; (3) Stop/Retry; (4) memory/streaming-limit hardening; then microphone/voice AI. Preserve UART/wiring, NTP, Japanese font, OTA and the working AI streaming implementation.

## Step 2 — S3 AI progress/error status (development)
- New S3 `BrainAI.h` status queue emits `AI:STATUS:QUEUED`, `CONNECTING`, `STREAMING`, `COMPLETE`, and granular failures (`WIFI_ERROR`, `CLOCK_ERROR`, `CONFIG_ERROR`, `NETWORK_ERROR`, `AUTH_ERROR`, `MODEL_OR_URL_ERROR`, `RATE_LIMIT`, `SERVER_ERROR`, `STREAM_INCOMPLETE`, `FAILED`).
- Existing encrypted BLE control notifications carry these asynchronously; this does not change C5 UART text frames. iOS BluetoothManager handles statuses separately from ACK processing, and ContentView shows user-friendly status/error text.
- **S3-only firmware change:** C5 firmware version stays v11; no pin or electrical changes. No new stable branch until physical regression test confirms working behavior.
- GitHub Actions and iOS/Xcode builds must be validated; connector commit-status endpoint does not expose all push-triggered workflow runs.

## Step 3 — Stop / Retry AI (development, untested)
- S3 `BrainAI.h` supports `AI:STOP`. Stop sets a cooperative cancellation flag, and the ESP HTTP event callback aborts when invoked, discarding staged/queued AI text and emitting `AI:STATUS:CANCELLED`. C5 receives `AI_END`; cancelled content does not enter conversation history.
- If the HTTP library is waiting without receiving callbacks, Stop may take until the request times out; do not claim it is guaranteed instantaneous.
- iPhone Home > AI has **Stop AI** (active request) and **Retry** (last submitted prompt). Retry occurs in the existing conversation and is unavailable during active generation; New conversation clears the previous retry target.
- BluetoothManager displays Stopping and Stopped states. The C5 app and wiring remain unchanged; C5 v11 OTA is not required again.
- GitHub CI and physical validation remain pending. Keep `stable/2026-10-27-c5-v11-conversation-24h-hardware-tested` untouched. Proceed to Step 4 only after verifying Stop, Retry, and normal completion.

## Step 3 acceptance and Step 4 streaming / flash-write hardening
- User explicitly reported **6/6 PASS** on physical hardware: regular AI completion, long response stopped, iPhone showed Stopped, Retry succeeded, New Conversation cleared context, and Japanese rendering / 2-minute return continued working.
- **Step 4 development changes:** `BrainAI.h` now avoids rewriting conversation NVS keys whose values have not changed, while preserving each completed-turn persistence and deletion. It also processes unusually large valid streaming text deltas in smaller UTF-8-boundary-aligned pieces, instead of marking a response failed solely because an SSE delta exceeded the 512-byte staging threshold.
- C5 v11 sketch and wiring are unchanged. The last hardware-tested checkpoint (`stable/2026-10-27-c5-v11-conversation-24h-hardware-tested`) remains unmodified.
- **Outstanding verification:** compile combined firmware, flash S3, test long Japanese replies and multi-turn conversation after S3 reboot, verify 24-hour expiry with real elapsed time; do not claim these Step 4 changes have passed hardware tests.

## Step 4 physical validation + voice preparation (2026-10-27)
- User reported **6/6 PASS** for Japanese chat, long Japanese response, Stop AI, Retry, S3 reboot persistence, and New Conversation clearing.
- Created immutable rollback branch `stable/2026-10-27-step4-streaming-hardware-tested` at commit `e7d31bbd7925c69173306e268378045834dff16e`. Older stable checkpoints untouched.
- 24-hour *elapsed* expiry still requires an overnight test, not established by the six checks.
- Audio preparation: reuse existing `firmware/CuteDisplayBrain/BrainAudioTest.h` local 16 kHz 2-second record→playback loopback and the existing `A:TEST` BLE command / USB audio test. I2S BCLK GPIO41, WS GPIO42, DIN GPIO1, DOUT GPIO2 on S3; do not change pins. Start with standalone mic capture/level and speaker diagnostics before STT/TTS networking. Record logs for mic left-channel amplitude/saturation, intelligible speaker playback, and BLE/Wi-Fi coexistence.
- Planned voice flow: S3 mic PCM -> server STT -> existing Open WebUI chat -> server TTS -> S3 I2S speaker, initially push-to-talk. Audio network protocol, latency and buffer strategy require implementation and testing; no claim that streaming voice is implemented.

## First voice milestone — S3 microphone -> Open WebUI STT -> existing text AI
- Added `firmware/CuteDisplayBrain/BrainVoiceSTT.h`: three-second 16-kHz mono PCM WAV recording from INMP441 via I2S (S3 pins unchanged); 96-KB raw audio stored in PSRAM; multipart HTTPS request to `{brain-ai.url}/api/v1/audio/transcriptions` with the **existing** Open WebUI bearer key; read JSON `text` (maximum 1024-byte transcript). No audio transferred to the C5. The configured Open WebUI audio STT engine handles recognition.
- Added `A:VOICE` BLE command to launch capture; firmware main loop takes finished transcription and passes it through `BrainAI::startWithPrompt`, preserving 24-hour conversation context and C5 text streaming. iPhone Home AI UI includes `Talk to Kitty (3 seconds)`.
- Important: this requires Open WebUI's own STT route to support authenticated multipart WAV upload; check server `/api/v1/audio/transcriptions` and its STT configuration. The chat model ID is not used as the STT model.
- Voice response through MAX98357A is **not implemented**. First verify voice recognition, transcript, and Japanese response on C5. **This development commit is not yet confirmed compiled or tested on hardware**; only flash after a successful combined firmware workflow. Existing stable branches remain intact.
- Privacy: audio is uploaded only to the configured HTTPS Open WebUI server with existing API key. Open WebUI may retain temporary uploaded audio/transcript logs per its server configuration; do not assume STT artifacts are deleted after 24 h.

## Voice recording: user-controlled stop and 30-second limit
- S3 `BrainVoiceSTT.h` records mono 16 kHz/16-bit WAV into PSRAM up to **30 seconds**. `A:VOICE` starts recording; `A:VOICE:STOP` requests Stop & Send. At 30 seconds capture automatically ends and submits to configured Open WebUI STT endpoint. Actual WAV header/content length uses captured samples, avoiding silence padding when stopped early; recordings under 250 ms or near-silent are rejected.
- C5 firmware, UART, pinout unchanged. iPhone Home > AI uses one toggle button `Talk to Kitty (30 sec max)` / `Stop & Send`. A `VOICE_UPLOADING` event resets button state at recording end, including the automatic timeout. Other voice status and text AI history behavior are unchanged.
- 30 seconds consumes ~960 KB raw PCM PSRAM and ~960 KB multipart request staging, plus other buffers. Memory/headroom and actual performance **require device testing**. Latest development firmware CI success is not yet confirmed; keep stable branches untouched.

## OGG/Opus compression research — not yet implemented
- The working voice flow uploads 16-kHz mono 16-bit PCM WAV (roughly 960 kB/30 seconds). Do **not** change the upload's Content-Type or extension to `.ogg` without encoding actual Ogg/Opus data.
- Open WebUI accepts `.ogg` as a configured audio extension by default, but the actual configured backend must be tested with real Opus-in-Ogg, not just file name.
- Investigated `sh123/esp32_opus_arduino` (Arduino Opus encoder; GPLv3) and Espressif `esp_audio_codec` (ESP-IDF component with ESP32-S3 Opus support). A codec produces Opus frames; **Ogg framing/muxing, CRCs, granule positions, OpusHead/OpusTags, 48-kHz granule accounting, and Arduino 3.3.12 compatibility are still required.** Neither dependency is integrated or validated on this branch.
- Maintain a *real* WAV fallback, enable compressed format only after a reproducible S3 CI build and a successful Open WebUI transcription from uploaded .ogg on the user's specific server. Consider a server-side endpoint with explicit Opus support only after measuring latency/CPU usage.
