# One S3 upload for the C5 v2 OTA test (automated combined build)

**What is provided:** GitHub Actions can compile the LILYGO ESP32-C5 OTA bootstrap firmware (v1), compile an ESP32-C5 app with version **2**, embed the actual C5 v2 application image in the ESP32-S3 Brain sketch, and compile a matching S3 application. A build artifact contains both generated binaries and ready-to-open Arduino IDE sketch folders with all required LILYGO headers/drivers. This avoids editing C5 version numbers, manually exporting .bin or running the packager.

**THIS IS NOT A VERIFIED, SUCCESSFUL BUILD YET.** GitHub Actions must finish successfully. Firmware OTA and reset have not been tested on user hardware; recover C5 over USB if something goes wrong. Do not flash an app-only binary at flash offset 0.

## Easy workflow on a Mac

1. Open [GitHub Actions → Build S3 firmware with C5 OTA update](https://github.com/ryushi01/CuteDisplay/actions/workflows/build-s3-with-c5-update.yml). Select **Run workflow → Run workflow** if no successful run exists yet. A `push` to the firmware/build workflow paths also triggers it.
2. Open a **successful green run**, find **Artifacts**, and download **CuteDisplay-S3-includes-C5-v2**. Unzip the download.
3. **One-time requirement, only if you have NOT yet flashed OTA support on the C5:** With the shared positive 5V jumper removed and USB attached directly to C5, open `lcd/lcd.ino` from the downloaded artifact in Arduino IDE. Use **ESP32C5 Dev Module**, 16 MB flash, enabled PSRAM and the **default_16MB two-slot OTA partition**. Select C5's USB port and click **Upload**. This installs the OTA-enabled C5 version 1 receiver. You cannot skip this on an older C5 firmware.
4. Disconnect C5's USB safely, restore the existing crossed UART and common GND. With power removed and 5V wiring safe, connect USB **only to the S3 Brain**. Open `CuteDisplayBrain/CuteDisplayBrain.ino` from the downloaded artifact. Select **ESP32S3 Dev Module**, **16MB flash**, **OPI PSRAM**, **default_16MB** partition scheme, S3 USB port, then click **Upload**.
5. The S3 application **contains** the C5 v2 app. It queries the C5 running v1, transfers the update through the existing **921600-baud** UART, and C5 shows the persistent **FIRMWARE UPDATE** progress overlay, then **INSTALLING UPDATE**. After image validation C5 restarts. In S3 USB Serial Monitor **115200 baud**, look for `[S3 OTA] SUCCESS: new display firmware confirmed after reboot`.
6. If the C5 already runs v2, the S3 leaves it untouched. If the C5 does not have an OTA receiver, the S3 will report `C5 OTA receiver not detected` and **cannot** update that C5 without the one-time C5 USB flash.

**Important:** You can only download a precompiled firmware artifact from GitHub Actions **after that workflow passes**. Do not confuse the checked-in `firmware/CuteDisplayBrain/C5FirmwareImage.h` file with a bundled release—the file is deliberately empty in repository source until the build script creates the combined artifact.

## Local alternative

If GitHub Actions are unavailable, install [Arduino CLI](https://arduino.github.io/arduino-cli/latest/installation/) and the ESP32 **3.3.12** Arduino board core on your Mac. Then, in the CuteDisplay project folder, run:

```bash
bash tools/build_s3_with_c5_update.sh
```

The script downloads the missing `board_config.h`, AXP2602 and ST7789 drivers directly from LILYGO's official repository, compiles C5 v1, C5 v2 and S3 with the packaged v2 image, and writes `release/`. Open `release/CuteDisplayBrain/CuteDisplayBrain.ino` in Arduino IDE and click **Upload** to the S3. **The script never flashes hardware itself.**

## Known conditions

- Existing iPhone BLE, Brain Wi-Fi/LAN fallback, LILYGO UART wiring, GPIO0 button and C5 radio-disable remain untouched by this build automation.
- Arduino-ESP32 core 3.3.12 is pinned because the C5 updater needs `Update.setSHA256`.
- GitHub Actions must have permission to run for this repository. On build failures, inspect the **Compile C5 v1/v2 and bundled S3 firmware** step for the exact first error.
- The prebuilt `S3-Brain-includes-C5-v2-application.bin` is **an app partition image**, not a whole-chip merged flashing image. The simplest installation is via the matching Arduino IDE sketch, not arbitrary binary flashing.
- Two USB supplies must never have their positive 5V rails bridged. UART wires/GND are unchanged.
- Firmware images are not over-the-air fetched: the S3 embeds the compiled C5 binary produced by this build. SHA-256 checks transport integrity, not vendor signing or firmware authorship.
- Reboot/rollback behavior remains experimentally unverified. A valid but unbootable new C5 app may still require direct USB recovery if bootloader rollback is disabled.
