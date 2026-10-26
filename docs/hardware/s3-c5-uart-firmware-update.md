# Phase 6 — LILYGO ESP32-C5 firmware updates delivered by S3 UART

**IMPLEMENTED IN SOURCE, NOT YET COMPILED OR HARDWARE-TESTED.** This is a controlled beta. Keep a direct-USB LILYGO recovery path until the entire update/reboot cycle has been verified on your specific board. Only flash/test with steady power. Existing ESP32-S3 BLE, Wi-Fi/LAN and S3↔C5 UART speed/pins have not been changed.

## What the update does

After a **one-time USB bootstrap of the C5 display**, subsequent C5 application updates are transferred by S3 over the current 921600-baud GPIO47→C5 GPIO1 and C5 GPIO6→S3 GPIO21 UART. No extra wires. C5 BLE and Wi-Fi stay disabled. The S3 sends `OTA_QUERY`; C5 returns `OTA_INFO=<running version, inactive OTA slot capacity>`. If the S3 has a newer **separately compiled and bundled** ESP32-C5 application image, the S3 sends a manifest (version, byte count, SHA-256 digest), then 40-byte binary chunks hex-encoded inside the existing CRC8-protected CuteLink UART frames, stop-and-wait with ACK/retries. The C5 writes only to its inactive OTA app slot using `Update.begin()`, `Update.write()`, `Update.setSHA256()` and `Update.end(false)`. A malformed/incomplete/wrong-hash image is rejected and does **not** cause a reboot.

During upload, a topmost **FIRMWARE UPDATE / RECEIVING FROM BRAIN** screen covers the mascot and disconnected warning and shows 0–100% progress. On completion, the C5 shows **INSTALLING UPDATE / VERIFYING / RESTARTING**, sends a final acknowledgment and invokes `ESP.restart()`. The S3 **queries the new C5 version after reboot** and only declares success when it matches the packaged version. If bootloader rollback is enabled, the C5 additionally calls `esp_ota_mark_app_valid_cancel_rollback()` after initializing its LCD and first receiving a valid S3 UART frame. On failure, the C5 displays **UPDATE FAILED** for ~10 seconds and leaves the previous app in place. The LCD and saved display settings should be restored by normal C5 boot; **this has not yet been verified experimentally**.

If the bundled image is empty (the default checked-in `C5FirmwareImage.h`), **S3 will never flash the display**. Packaging a new C5 binary is required before every actual C5 firmware release.

## Critical C5 partition prerequisite

Use the ESP32-C5 with **16MB flash and an OTA-capable two-slot partition layout** (`otadata`, `ota_0`, `ota_1`). For example, Espressif's Arduino 3.3.12 `default_16MB.csv` has application slots of 0x640000 bytes each, but your **actual flashed C5 partition table** must be verified, not assumed from board capacity. C5 returns zero capacity if no inactive OTA partition exists, and S3 refuses the update. Verify Arduino ESP32 core supports `Update.setSHA256()` (Arduino-ESP32 **3.3.12+** reference implementation).

Switching the partition table during initial bootstrap may require a **full direct USB flash** of bootloader/partition table/app and could invalidate old NVS settings if the layout changes. Back up any important display preferences. Do not erase flash unless required.

## First installation: one LAST C5 USB flash

1. Save a copy of known-working CuteDisplay firmware (before this feature, `ca00878a702a3717294c5ecdcd449ff1eb80a1f1`).
2. With both boards powered OFF, disconnect any shared +5V rail if attaching separate USB power cables. Flash **firmware/CuteDisplay/lcd.ino** together with `C5UARTOTA.h`, `C5FirmwareVersion.h`, `CuteLink.h` and all other existing dependencies, selecting the two-app OTA partition layout for your C5. The initial C5 software version is **1**.
3. Power both boards using the established wiring. Flash **firmware/CuteDisplayBrain/CuteDisplayBrain.ino** with `BrainC5OTA.h` and the **empty** `C5FirmwareImage.h` placeholder. USB Serial Monitor for S3 is **115200**, S3↔C5 UART remains **921600**.
4. Verify Kitty, two-way UART, iPhone Bluetooth, LAN fallback and S3 Wi-Fi behave as before. S3 should report `[S3 OTA] C5 reports v1, OTA slot=... bytes` and `No bundled C5 image; no update required`. **If slot is zero, fix the C5 partition selection before testing a real update.**

## Test the first one-S3-USB C5 upgrade (v1→v2)

1. Edit `firmware/CuteDisplay/C5FirmwareVersion.h` from `C5_FIRMWARE_VERSION=1` to **2**. Compile this **ESP32-C5** sketch (same 16MB OTA partition scheme) and export its single **application** binary (`.bin`), e.g. using Arduino IDE **Sketch → Export Compiled Binary**. Do not use a merged .bin, S3 firmware, bootloader or partition-table image.
2. On your computer, run from the repository root:

   ```bash
   python3 tools/package_c5_firmware.py --bin /path/to/C5-application.bin --version 2
   ```

   The script requires a matching source version, validates the binary's ESP32-C5 chip ID **23**, length, image magic and produces `firmware/CuteDisplayBrain/C5FirmwareImage.h` containing the separate C5 application image and SHA-256. Review/commit this generated header if maintaining release artifacts. **An S3 Arduino sketch upload alone does not compile the C5 source**.
3. Compile/upload **only the S3 Brain sketch** with this generated image header. Ensure its binary **fits the selected S3 application partition**. A full C5 binary embedded in the S3 can substantially increase the S3 sketch's flash size; the Arduino compiler may reject an oversized application, which is safer than installing a truncated image.
4. S3 detects C5's current v1, transfers v2 automatically when its UART command relay is idle. LILYGO must display **FIRMWARE UPDATE**, the percent bar, then **INSTALLING UPDATE**. After image verification it restarts automatically.
5. S3 must log **`[S3 OTA] SUCCESS: new display firmware confirmed after reboot`** and **C5 reports v2**. Until **both** appear, do not consider the upgrade complete. Verify Kitty message, button, Bluetooth, Wi-Fi icons and persistent Brain link status again.
6. On future C5 changes, bump C5 source version to 3, 4, ...; compile C5, package the C5 binary, upload **only S3**. If S3 carries the same/older C5 version, it does not reflash the display.

## Error and recovery behavior

- **Bad binary/target:** packager rejects wrong chip (ESP32-C5 image ID must be 23) and wrong source release version; C5 verifies new version and inactive slot size before writing.
- **Interrupted UART / bad CRC / timeout:** ACK/retransmission is bounded; C5 does not switch boot partitions until the full image passes verification. Update session is aborted after a long receive timeout. If there is an incomplete transfer, old application normally remains running.
- **Power loss or failed post-boot image:** dual OTA slots reduce risk, but do **not** guarantee fallback after a complete yet unbootable image unless bootloader rollback support is configured/tested. Direct C5 USB recovery must remain available. The S3 reports failure instead of marking success.
- **Application data:** `Update` only targets the inactive app slot; it should not erase NVS display state. Firmware code or partition layout changes can still affect saved settings; test after the first update.
- **Security:** SHA-256 checks transfer integrity, not publisher authenticity. The image is bundled locally into the S3 firmware, not fetched automatically from an untrusted server. For remote deployment use signed firmware images and secured update distribution.
- **Speed:** existing CuteLink payload limit is 96 bytes; image blocks are 40 bytes, with ACK pacing. Transfers may be slow for multi-MB images. Do not claim measured transfer time until hardware tests.

## No changes to the iPhone app

This update uses the S3/C5 firmware-only UART protocol. iPhone Swift app, Brain BLE bonding profile, S3 Wi-Fi fallback, original GPIO assignments and C5 radios remain unchanged. The flash-image packager and a tested C5 OTA partition scheme are prerequisites for the final one-USB workflow.

**Useful reference:** Espressif Arduino [Update SHA-256 API](https://github.com/espressif/arduino-esp32/blob/3.3.12/libraries/Update/src/Update.h); [C5 firmware image format](https://docs.espressif.com/projects/esptool/en/latest/esp32c5/advanced-topics/firmware-image-format.html).
