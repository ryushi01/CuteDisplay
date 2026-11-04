# Kitty V6 — C5 v40 five-line Call Mode and responsive stop

Status: source committed on `main`; hardware v40 testing remains required. The operator previously flashed the privately configured S3+C5 v39 combined release successfully and reported normal calls and surprising use of the name Shana. That observation alone does **not** establish trusted private-owner historical recall.

## Requested improvements

1. Five transparent C5 full-screen conversation rows (not two): `C5CallFace.h` uses five black UTF-8-aware rows, 16-pixel line spacing, top position y=2, wrapping within 304 px, showing recent utterances plus the live speaker caption. The existing animated Kitty background, 16 expressions, lip sync and transparent status text remain. Last five **wrapped lines** are visible, not guaranteed five complete speaker turns.
2. Responsive left BOOT GPIO28 stop: `lcd.ino` polls the button at the start of the main C5 loop, before caption redraws and network work. A debounced press while Call Mode is active immediately issues a new stop-only UART `CALL_STOP` to S3 and removes the face locally. Release and holds cannot swallow the stop, and the C5 may retry the idempotent frame up to four times at 650 ms spacing. `CuteDisplayBrain.ino` handles `CALL_STOP` by invoking `BrainRealtimeDirect::stop()` **only if** a call is active, then resends authoritative `ACTIVITY`; it never toggles to start on a delayed stop. When idle, short tap still starts Call Mode and a >=320 ms long hold retains existing manual PTT. Right GPIO0 button/Wi-Fi behavior is unchanged.
3. No leftover ordinary chat bubble after full-screen calls: the C5 saves the normal message, suspends legacy AI scroll/typewriter and suppresses ordinary bubble rendering while Call Mode runs and after it closes; a new normal chat message may resume the user's saved bubble preference. The `AI_BEGIN`/`AI_DATA`/`AI_END` legacy display stream is rejected while a live call or stop confirmation is pending. No NVS preference value changes. The S3 realtime AI audio/chat integration is unchanged.
4. High-frequency `CALL_TEXT` and `CALL_LIP` UART frames now coalesce into a single LCD refresh per `serviceBrain` iteration to reduce display-induced input polling delays.

## Security and hardware guards

- C5 version is bumped from v39 to **v40**, so the existing version-checked S3 UART OTA can upgrade the C5 without a separate C5 USB flash.
- The *private combined* builder `tools/build_s3_with_c5_update.sh` retains the original `KittySyncPrivateConfig.h` in the generated **local** Arduino IDE S3 project and embeds it into the S3 image. The header and binary contain the device bearer and must **never** be uploaded to GitHub, public CI, files in chat, or unsecured channels.
- S3 microSD stays the memory authority, with no format/erase; C5 v39 is the previous physical fallback. Keep a rollback-capable v39 release and the original firmware image before installing v40. Do not use an application-only `.bin` as a factory image at flash offset `0x0`.
- Realtime gateway, Ubuntu memory service, Mac AI/TTS, BLE-to-C5 migration and owner 403 private-memory guard are untouched. Recognizing a spoken name does not authorize private history.

## Release checks

Offline C5 v40 tests: `server/test_kitty_c5_call_mode_v40.py`, updated `server/test_kitty_c5_transparent_caption_v39.py` and `server/test_kitty_display_contract_v6.py`, wired into `.github/workflows/build-s3-with-c5-update.yml` before the full C5+S3 firmware build. Source checks are not a substitute for physical call latency, touch and UART packet measurements.

Build privately on the existing Ubuntu server from GitHub `main` pinned via `FETCH_HEAD`, using the previously validated local header at `$HOME/kitty-v6/private/kitty-sync-deployment/KittySyncPrivateConfig.h`. The builder creates a *new* private `combined-*` directory under `$HOME/.local/share/kitty-v6/private-builds/`, and does not flash. Do not use the previous `s3-only-20261104T081701Z-937137` image: it has no C5 update payload. The new combined S3 application must have C5 image version 40 and the private config.

After local compilation, verify its `SHA256SUMS.txt`, copy it to the Mac user's `~/Downloads/Kitty-private/` using SSH/SCP to `ryushi@10.5.5.245`, and flash **S3 only** from the generated private `CuteDisplayBrain/CuteDisplayBrain.ino` with the previously validated board/partition settings. The S3 then attempts the C5 v40 UART update while idle. Preserve existing NVS, voice profiles and microSD; do not erase flash.

On hardware, verify (a) C5 reports v40, iPhone BLE still pairs, (b) five latest wrapped conversation rows show while speaking and listening, (c) a short or long press on the **left** C5 BOOT button stops during LISTENING, THINKING and SPEAKING without starting another call, (d) no old bubble animates in the background or returns on exit, (e) normal chat mode still works on its next new message, (f) `memory sync status` reports `configured=1`, `running=1`, and later a completed upload, (g) normal bidirectional audio and lip sync remain working. If a button stop is delayed, collect only brief `CALL`/UART timestamps and avoid repeated reflashes.
