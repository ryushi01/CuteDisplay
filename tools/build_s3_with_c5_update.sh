#!/usr/bin/env bash
# Build a C5 v1 bootstrap, C5 v2 OTA image, and an S3 with C5 v2 embedded.
# Runs on macOS or a GitHub Actions Linux runner; never flashes a USB device.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/release"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
C5_FQBN="esp32:esp32:esp32c5:FlashSize=16M,PSRAM=enabled,PartitionScheme=default_16MB"
S3_FQBN="esp32:esp32:esp32s3:FlashSize=16M,PSRAM=opi,PartitionScheme=default_16MB"

for program in arduino-cli git python3; do
  command -v "$program" >/dev/null || { echo "Missing $program" >&2; exit 1; }
done
echo "[1/7] Fetch official LILYGO C5 board/AXP2602/ST7789 drivers"
git clone --quiet --depth 1 --filter=blob:none --sparse \
  https://github.com/Xinyuan-LilyGO/T-Display-C5.git "$WORK/vendor"
git -C "$WORK/vendor" sparse-checkout set include lib/AXP2602 lib/esp_lcd_st7789

# Arduino requires the main lcd.ino sketch in a folder called lcd.
mkdir -p "$WORK/lcd" "$OUT"
cp -R "$ROOT/firmware/CuteDisplay/." "$WORK/lcd/"
cp "$WORK/vendor/include/board_config.h" "$WORK/lcd/"
cp "$WORK/vendor/lib/AXP2602/axp2602.h" "$WORK/lcd/"
cp "$WORK/vendor/lib/AXP2602/axp2602.cpp" "$WORK/lcd/"
# On case-insensitive macOS APFS these paths refer to the same file.
if [ ! -f "$WORK/lcd/AXP2602.h" ]; then
  cp "$WORK/lcd/axp2602.h" "$WORK/lcd/AXP2602.h"
fi
cp "$WORK/vendor/lib/esp_lcd_st7789/esp_lcd_st7789.h" "$WORK/lcd/"
cp "$WORK/vendor/lib/esp_lcd_st7789/esp_lcd_st7789.c" "$WORK/lcd/"

echo "[2/7] Build initial C5 version 1 firmware (one-time USB bootstrap)"
grep -q 'C5_FIRMWARE_VERSION=1;' "$WORK/lcd/C5FirmwareVersion.h"
arduino-cli compile --clean --fqbn "$C5_FQBN" \
  --build-path "$WORK/build-c5-v1" "$WORK/lcd"
test -s "$WORK/build-c5-v1/lcd.ino.bin"
mkdir -p "$OUT/lcd"
cp -R "$WORK/lcd/." "$OUT/lcd/"
cp "$WORK/build-c5-v1/lcd.ino.bin" "$OUT/C5-bootstrap-v1-application.bin"

echo "[3/7] Bump C5 version in temporary build copy ONLY"
python3 - "$WORK/lcd/C5FirmwareVersion.h" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
source = path.read_text()
old = "C5_FIRMWARE_VERSION=1;"
assert source.count(old) == 1, "Unexpected version header"
path.write_text(source.replace(old, "C5_FIRMWARE_VERSION=2;"))
PY

echo "[4/7] Build C5 version 2 application binary"
arduino-cli compile --clean --fqbn "$C5_FQBN" \
  --build-path "$WORK/build-c5-v2" "$WORK/lcd"
test -s "$WORK/build-c5-v2/lcd.ino.bin"
cp "$WORK/build-c5-v2/lcd.ino.bin" "$OUT/C5-update-v2-application.bin"

echo "[5/7] Embed C5 v2 image into the S3 sketch"
mkdir -p "$WORK/CuteDisplayBrain"
cp -R "$ROOT/firmware/CuteDisplayBrain/." "$WORK/CuteDisplayBrain/"
python3 "$ROOT/tools/package_c5_firmware.py" \
  --bin "$WORK/build-c5-v2/lcd.ino.bin" --version 2 \
  --version-header "$WORK/lcd/C5FirmwareVersion.h" \
  --output "$WORK/CuteDisplayBrain/C5FirmwareImage.h"

echo "[6/7] Compile S3 Brain firmware, bundled with the C5 v2 binary"
arduino-cli compile --clean --fqbn "$S3_FQBN" \
  --build-path "$WORK/build-s3" "$WORK/CuteDisplayBrain"
test -s "$WORK/build-s3/CuteDisplayBrain.ino.bin"
mkdir -p "$OUT/CuteDisplayBrain"
cp -R "$WORK/CuteDisplayBrain/." "$OUT/CuteDisplayBrain/"
cp "$WORK/build-s3/CuteDisplayBrain.ino.bin" \
  "$OUT/S3-Brain-includes-C5-v2-application.bin"

cat > "$OUT/READ_ME_FIRST.txt" <<'EOF'
CuteDisplay: S3 Brain firmware + LILYGO C5 update v2
==================================================
BOOTSTRAP (one time only, if C5 has never received OTA support):
  - Disconnect the positive 5V bridge BEFORE attaching a second USB.
  - Open lcd/lcd.ino in Arduino IDE; select ESP32C5 Dev Module with
    16 MB flash, enabled PSRAM, default_16MB OTA partitions.
  - Click Upload to the C5 USB once (installs OTA receiver, v1).

FUTURE UPDATES: UPLOAD ONLY THE S3 VIA ITS USB:
  - Open CuteDisplayBrain/CuteDisplayBrain.ino in Arduino IDE.
  - Select ESP32S3 Dev Module, 16 MB flash, OPI PSRAM and
    default_16MB OTA partitions; choose the S3 USB port.
  - Click Upload. S3 checks the C5's version and, if it is v1,
    transfers the bundled v2 image over the existing UART.
  - Check S3 USB Serial Monitor at 115200 baud for:
    [S3 OTA] SUCCESS: new display firmware confirmed after reboot

S3-Brain-includes-C5-v2-application.bin is an APP-only image, not a
whole-chip factory image. Never flash it to address 0x0; its normal
application offset is 0x10000 ONLY if your existing S3 partition table
and bootloader match. Arduino IDE Upload from source is safer.

NOT HARDWARE VERIFIED. Retain a C5 USB recovery path until the
first real UART upgrade/reboot has been tested successfully.
EOF
echo "[7/7] Combined firmware available at: $OUT"
ls -lh "$OUT/"*.bin
echo "Open $OUT/CuteDisplayBrain/CuteDisplayBrain.ino in Arduino IDE"
