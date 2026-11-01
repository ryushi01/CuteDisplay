# Kitty V6 — C5 Bluetooth ownership migration (implementation contract)

Status: **architecture reviewed; not flashed or deployed**. Preserve v36 working baseline `cf507454edb5379001479364301ca043430ecc89`. Do not enable the dormant legacy C5 `initBLE()` as-is.

## Objective

Move the entire phone-facing BLE stack, bonds, GATT and notifications to C5. S3 stays responsible for Wi-Fi, LAN fallback, credentials, AI, realtime 24 kHz duplex audio, SD, CPU voice profiles and OTA. Keep the existing 921600 baud UART and C5 display, buttons and animations.

## Findings on feature/kitty-semantic-v6-cpu

* C5 `firmware/CuteDisplay/lcd.ino` includes a legacy BLE server, but setup deliberately disables it. Its FFF1 does not support authenticated encrypted read, notifications, `PROXY_READY` or the S3 command acknowledgement model. Never merely call `initBLE()`.
* S3 `firmware/CuteDisplayBrain/CuteDisplayBrain.ino` owns encrypted FFF1, encrypted FFF6, bonded Just Works pairing, network key delivery, command routing, LAN fallback and AI provisioning. BLE is initialized near setup's end.
* iOS `ios/CuteDisplay/BluetoothManager.swift` reads encrypted FFF1 before it enables app commands. Uses FFF0/FFF1 control, 180F/2A19 battery, FFF3/FFF4 power and FFF5/FFF6 network notifications. It retains an authorized BLE identifier; C5 must be paired as a new accessory.
* C5 and S3 already exchange framed `CuteLink` messages including OTA, status, battery, clock, realtime face, button control. C5 BOOT/display firmware is not a replacement for S3.

## Required change set (all-or-nothing)

1. **C5 BLE**: use S3-compatible authenticated encrypted GATT services and notifications; connect/disconnect/bond callbacks; bounded command queue with zero-length, NUL and length rejection. C5 phone identity `CuteDisplay-Kitty`; iPhone picker matches `CuteDisplay`. C5 must only consider encrypted-read success session authenticated, and announce `PROXY_READY` only after its UART peer completes liveness handshake. Do not forward untrusted notifications as authorization.
2. **UART app bridge**: add explicitly versioned bounded `APP_CMD`, `APP_REPLY`, `APP_NET`, `APP_STATUS` framing or equivalent using CuteLink CRC. Split/reassemble payloads inside existing maximum frame size; include transaction ID, length, timeout, retry, duplicate suppression and valid source checks. Reuse existing UART reader and command queue, never block audio or create another large S3 task. C5 can execute local display controls but S3-only requests `W:`, `AI:`, `A:`, `TIME:` must reach S3; every app command must get one final reply, not an optimistic ACK.
3. **Security**: BLE pairing is bonded Just Works (encrypted but no MITM). Current UART is not secure against a physical attacker: do not claim BLE encryption continues across UART. Protect provisioning against unsolicited C5 transport and add origin/session gating; for higher assurance require an authenticated board-to-board protocol, encrypted UART, or an explicit physical provisioning confirmation. Never send secrets to Serial logs. S3 LAN HMAC secret remains S3-owned; only send the key over an appropriately secured authorized phone provisioning path. Do not weaken S3 Wi-Fi command restrictions. No owner-private memories are authorized from BLE pairing or voice match.
4. **S3**: preserve Wi-Fi and LAN functions, AI provisioning and realtime audio. Remove BLE library initialization, callbacks, GATT allocations and client queues only once the new C5 UART route replaces every consumer. Measure free internal heap and largest contiguous block before/after. Releasing unused controller memory is conditional on Arduino/ESP-IDF configuration; verify rather than assume.
5. **C5 OTA**: quiesce/disconnect BLE before flash write, refuse app commands during OTA, reboot into bonded advertising after successful update, and keep USB recovery. Keep S3 single-upload combined firmware image and C5 version increment.
6. **iOS**: new C5 accessory identity, new Keychain scope/migration for LAN key only after authenticated provisioning, preserved FFF1 read/notifications/ACK, Wi-Fi and AI controls, loss/reconnect handling and LAN fallback behavior. Keep CoreBluetooth / AccessorySetupKit authorization semantics.
7. **Validation**: CI compile both sketches + relevant app syntax; one S3 combined upload → C5 OTA; one phone reconnect/re-pair and one display command; one Wi-Fi provisioning/status; one realtime audio call; print S3 heap and largest free block. Check SD archive and voice profiles still present. Revert to checkpoint if audio, provisioning or C5 OTA fails.

## Deployment guard

Until **all** new firmware and iOS paths compile and pass review, **do not flash or disable S3 BLE**. Baseline: `docs/KITTY_V6_WORKING_BASELINE_AND_NEXT_STEPS_2026-10-31.md` and combined GitHub Actions run `41199575994`.

## Follow-on memory work

After a stable BLE migration, coordinate durable speaker-scoped SD claims, authoritative write acknowledgement, asynchronous per-turn speaker-specific direct realtime context, CPU voice recognition consistency, and bounded idempotent server cleanup in one change set. Protect live SQLite, voice profiles, current/rollback snapshots and private env. One final test: save preference → SD ACK → reboot → correctly scoped recall in direct realtime voice, with guest-leakage negative check.
