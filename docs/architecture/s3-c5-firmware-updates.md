> **Update (2026-10-27):** The application-level C5 OTA receiver, Brain UART sender, image packager and progress popups are now present in beta source. They have **not been compiled or tested on hardware**. Follow the new [Phase-6 implementation and bootstrap guide](../hardware/s3-c5-uart-firmware-update.md) before flashing; this earlier document describes the design alternatives.

# Phase 6 proposal — S3-delivered firmware updates for the LILYGO ESP32-C5

**Status: researched engineering design only. NOT IMPLEMENTED or tested.** Do not interpret these notes as OTA support in the existing firmware. The user has confirmed that the S3↔C5 UART at **921600 baud**, iPhone↔S3 Bluetooth and S3 Wi-Fi/LAN fallback work. Preserve those working features.

## Goal

After a one-time bootstrap flash of OTA-capable firmware onto the C5, **every subsequent physical USB firmware update should involve only the S3**. The S3 would include (or securely obtain) the desired compiled C5 application binary, compare it with the running C5 version, transfer it over the already-wired UART and verify successful reboot before declaring success. The C5 remains display-only, with local BLE and Wi-Fi disabled.

**Crucial distinction:** Simply uploading an S3 Arduino sketch does **not** automatically compile, bundle, or update the C5. We must implement *both* an OTA receiver in the C5 and an image-packing/build process plus sender in the S3. A C5 application binary is a separately built artifact for the ESP32-C5, not an S3 sketch or arbitrary file.

## Verified chip/board facts

The LILYGO **T-Display-C5** is based on the ESP32-C5, with **16 MB flash**, **BOOT on C5 GPIO28**, **GPIO0 as a separate user button**, and **touch-interrupt on C5 GPIO27**. ESP32-C5 UART0 **ROM firmware download** defaults to **C5 GPIO11 TX / GPIO12 RX**. To force the ROM downloader, keep **GPIO27 HIGH**, pull **GPIO28 LOW** at reset, then toggle **EN/CHIP_PU** (release GPIO28 after the boot strap is latched). Hardware auto-flashing from S3 would additionally require a safe open-drain/transistor approach to BOOT and EN and S3 UART connections to C5 GPIO11/12, **not just our existing C5 GPIO1 RX/GPIO6 TX**. GPIO0 / the user's left button is not the ESP32-C5 ROM download-select pin. Whether all these signals are exposed on accessible headers/test-pads of the specific LILYGO board must be checked from the board schematic/physical board before providing a finalized wiring diagram. C5 GPIO26 is an LCD pin and GPIO27 is connected to touch INT on this board; do **not** drive them arbitrarily.

- LILYGO official board repo: https://github.com/Xinyuan-LilyGO/T-Display-C5
- Espressif C5 bootloader guide: https://docs.espressif.com/projects/esptool/en/latest/esp32c5/advanced-topics/boot-mode-selection.html
- Espressif C5 UART0 pins: https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32c5/schematic-checklist.html
- If a physical recovery/programmer method is eventually chosen, Espressif supports an S3 host flashing a C5 target using **esp-serial-flasher**: https://github.com/espressif/esp-serial-flasher

## Recommended: application-level OTA over the working UART (NO NEW WIRES)

Current UART stays exactly:
```text
Freenove S3 GPIO47 TX -> LILYGO C5 GPIO1 RX
Freenove S3 GPIO21 RX <- LILYGO C5 GPIO6 TX
GND <-> GND
UART 921600 8N1
```
Shared 5V power precautions stay unchanged; no two independently powered USB VBUS rails when the positive power jumper is installed.

### Bootstrap (one final C5 USB update)

1. Ensure C5's **actual flashed partition table** contains `otadata`, `ota_0`, `ota_1`, with a sufficient-size inactive OTA app slot. The Espressif Arduino 3.3.12 `default_16MB.csv` has app0/app1 at `0x10000` / `0x650000`, each `0x640000` (6.25 MiB); however a *menu option labelled Default* is NOT proof of what was previously flashed. Inspect the actual configuration first. Flashing a partition table once via C5 USB may be necessary and risks resetting some data if its layout changes.
2. Implement and flash a **C5-side OTA receiver** that supports `Update.begin(image_size, U_FLASH)`, streamed blocks, final cryptographic digest verification, `Update.end()`, boot checks and version reports. During an update C5 must not perform display redraws, old BLE/Wi-Fi operations, command queue work or ordinary mascot command dispatch, and must give explicit ACK/NACK/error status.
3. Keep a known-good C5 USB recovery image and **verify S3↔C5 serial status** before any further changes. No OTA should auto-trigger at boot if no validated image was bundled.

### Regular one-S3-USB update (later, after OTA receiver is proven)

1. **Build BOTH architectures**: compile C5's `.bin` targeting ESP32-C5 with the same partition scheme and compile the S3 firmware targeting ESP32-S3. The build process must **bundle the C5 binary with the S3 application**, or stage it in a dedicated S3 flash data partition. Arduino IDE 'Upload' alone will not do this unless the image has been packaged beforehand. A scripted arduino-cli/PlatformIO build is recommended for repeatability.
2. On boot, S3 asks C5 for **firmware version, board/chip identity and OTA-slot capacity**. Only if a *newer* compatible C5 image is bundled, the display is not performing a critical task, and power is stable, S3 begins the update.
3. S3 sends a manifest (`target=ESP32-C5`, version, length, SHA-256 digest) and transfers numbered, CRC-protected blocks over **CuteLink UART** with stop-and-wait ACK / retransmissions and explicit limits. Existing CuteLink payload is 96 bytes max; hex transfer overhead is significant, but it avoids changing proven UART wiring.
4. C5 writes into **inactive** app slot only, validates every block + final image hash, sets boot partition **only after full verification** and reboots. Maintain an update timeout; a dropped UART connection should fail safely and **retain the old running image**. Do not write to `nvs`, `otadata` directly or the current app region outside verified OTA APIs.
5. S3 resumes normal heartbeat, waits for a valid **C5 post-reboot version**, and records success only on that positive confirmation. On failure, report the issue and require explicit recovery before trying again. Never enter an infinite erase/flash loop. ESP-IDF automatic rollback requires checking the active bootloader rollback setting; do **not** assume dual OTA slots alone guarantee application health rollback.
6. Authenticate update manifest/image as part of the S3 build, reject incorrect chip/version and old downgrade images. CRC/SHA alone provide error detection, **not authorship/authenticity**. For a deployed product, require signed images or a trusted update chain. Avoid remote automatic firmware source fetching until full verification is in place.

### Recovery caveat

This application-level method depends on a functioning C5 firmware OTA receiver. If the C5 is corrupted or won't boot, its ROM serial bootloader **cannot** be reached via the existing GPIO1/GPIO6 UART. Recovery would then require the C5 USB cable or the additional hardware ROM programming connections. This is why the first rollout must be controlled with a guaranteed known-good USB recovery path.

### Alternative: permanent S3-as-ROM-programmer wiring

If **recovery from corrupted/unbootable C5 firmware** is a hard requirement, add a hardware programming path. In addition to the working UART, connect S3-controlled, appropriately protected lines to **C5 GPIO28 BOOT** and **EN RESET**, and wire an additional S3 UART to **C5 ROM UART0 GPIO12 RX/GPIO11 TX**. Then integrate Espressif's `esp-serial-flasher` on the S3. No C5 OTA receiver bootstrap is required, but four extra signal connections and careful 3.3V/strap-level validation are needed. Never use the LCD/TP/boot strap pins interchangeably.

## Implementation gates before claiming support

- [ ] Confirm C5 partition layout and firmware binary length via actual build/flash settings
- [ ] Implement C5 OTA receiver; compile; one-time USB flash; confirm original CuteDisplay UI unaffected
- [ ] Implement packaged C5 binary and S3 OTA sender; compile both architectures
- [ ] Simulate interrupted transfer and CRC mismatch; verify original C5 continues to boot
- [ ] Verify successful C5 update and exact post-reboot version; check persistence of display settings
- [ ] Verify iPhone BLE reconnect, local Wi-Fi fallback, mascot, Japanese glyphs, and C5 long-press Wi-Fi toggle still work
- [ ] Test power recovery (with safe independent supplies/no bridged USB 5V) and verify no boot loops or bricking

**No flashing code has been activated yet.** The stable head of main remains the Phase 5 firmware.
