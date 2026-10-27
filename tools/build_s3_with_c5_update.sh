#!/usr/bin/env bash
# Build the current C5 application and embed it in the S3 Brain firmware.
# Runs on macOS or a GitHub Actions Linux runner; never flashes a USB device.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/release"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
C5_FQBN="esp32:esp32:esp32c5:FlashSize=16M,PSRAM=enabled,PartitionScheme=custom"
VERSION="$(sed -nE 's/.*C5_FIRMWARE_VERSION[[:space:]]*=[[:space:]]*([0-9]+);.*/\1/p' "$ROOT/firmware/CuteDisplay/C5FirmwareVersion.h")"
if ! [[ "$VERSION" =~ ^[0-9]+$ ]] || [ "$VERSION" -lt 2 ]; then
  echo "Invalid C5 firmware version. Set C5_FIRMWARE_VERSION to 2 or higher." >&2; exit 1
fi
echo "Packaging C5 firmware version $VERSION"
S3_FQBN="esp32:esp32:esp32s3:FlashSize=16M,PSRAM=opi,PartitionScheme=custom"

for program in arduino-cli git python3; do
  command -v "$program" >/dev/null || { echo "Missing $program" >&2; exit 1; }
done
# Arduino-ESP32 menu has PartitionScheme=custom, NOT default_16MB.
# Bundling the official dual-slot 16MB table inside both sketches ensures
# Arduino IDE Upload uses identical partitions to the compiled artifact.
PARTITIONS=""
for core in "$HOME/.arduino15/packages/esp32/hardware/esp32/3.3.12" \
            "$HOME/Library/Arduino15/packages/esp32/hardware/esp32/3.3.12"; do
  if [ -f "$core/tools/partitions/default_16MB.csv" ]; then
    PARTITIONS="$core/tools/partitions/default_16MB.csv"
    break
  fi
done
if [ -z "$PARTITIONS" ]; then
  echo "Cannot find Arduino-ESP32 3.3.12 default_16MB.csv; install the board core." >&2
  exit 1
fi
echo "[1/7] Fetch official LILYGO C5 board/AXP2602/ST7789 drivers"
git clone --quiet --depth 1 --filter=blob:none --sparse \
  https://github.com/Xinyuan-LilyGO/T-Display-C5.git "$WORK/vendor"
git -C "$WORK/vendor" sparse-checkout set include lib/AXP2602 lib/esp_lcd_st7789

# Arduino requires the main lcd.ino sketch in a folder called lcd.
rm -rf "$OUT"
mkdir -p "$WORK/lcd" "$OUT"
cp -R "$ROOT/firmware/CuteDisplay/." "$WORK/lcd/"
cp "$PARTITIONS" "$WORK/lcd/partitions.csv"
cp "$WORK/vendor/include/board_config.h" "$WORK/lcd/"
cp "$WORK/vendor/lib/AXP2602/axp2602.h" "$WORK/lcd/"
cp "$WORK/vendor/lib/AXP2602/axp2602.cpp" "$WORK/lcd/"
# On case-insensitive macOS APFS these paths refer to the same file.
if [ ! -f "$WORK/lcd/AXP2602.h" ]; then
  cp "$WORK/lcd/axp2602.h" "$WORK/lcd/AXP2602.h"
fi
cp "$WORK/vendor/lib/esp_lcd_st7789/esp_lcd_st7789.h" "$WORK/lcd/"
cp "$WORK/vendor/lib/esp_lcd_st7789/esp_lcd_st7789.c" "$WORK/lcd/"
# Generate an onboard Japanese bitmap fallback, avoiding BLE glyph requests for AI.
# The release contains the generated C5JapaneseFont.h for Arduino IDE users.
python3 "$ROOT/tools/generate_c5_japanese_font.py" --out "$WORK/lcd/C5JapaneseFont.h"

echo "[2/5] Build current C5 v$VERSION application"
arduino-cli compile --clean --fqbn "$C5_FQBN" \
  --build-path "$WORK/build-c5" "$WORK/lcd"
test -s "$WORK/build-c5/lcd.ino.bin"
mkdir -p "$OUT/lcd"
cp -R "$WORK/lcd/." "$OUT/lcd/"
cp "$WORK/build-c5/lcd.ino.bin" "$OUT/C5-v${VERSION}-application.bin"

echo "[3/5] Embed C5 v$VERSION in S3 firmware"
mkdir -p "$WORK/CuteDisplayBrain"
cp -R "$ROOT/firmware/CuteDisplayBrain/." "$WORK/CuteDisplayBrain/"
cp "$PARTITIONS" "$WORK/CuteDisplayBrain/partitions.csv"
python3 "$ROOT/tools/package_c5_firmware.py" \
  --bin "$WORK/build-c5/lcd.ino.bin" --version "$VERSION" \
  --version-header "$WORK/lcd/C5FirmwareVersion.h" \
  --output "$WORK/CuteDisplayBrain/CombinedFirmwareImage.h"
# A missing or empty image must NEVER produce a seemingly valid release artifact.
grep -Eq "inline constexpr uint32_t version=${VERSION}(UL)?;" "$WORK/CuteDisplayBrain/CombinedFirmwareImage.h" || { echo "Bundled image version mismatch" >&2; exit 1; }
if grep -Eq 'inline constexpr size_t length=0(UL)?;' "$WORK/CuteDisplayBrain/CombinedFirmwareImage.h"; then
  echo "ERROR: bundled C5 image is empty" >&2; exit 1
fi

echo "[4/5] Compile S3 Brain firmware with embedded C5 application"
arduino-cli compile --clean --fqbn "$S3_FQBN" \
  --build-path "$WORK/build-s3" "$WORK/CuteDisplayBrain"
test -s "$WORK/build-s3/CuteDisplayBrain.ino.bin"
mkdir -p "$OUT/CuteDisplayBrain"
cp -R "$WORK/CuteDisplayBrain/." "$OUT/CuteDisplayBrain/"
cp "$WORK/build-s3/CuteDisplayBrain.ino.bin" \
  "$OUT/CuteDisplay-CombinedFirmware.bin"
cp "$WORK/build-s3/CuteDisplayBrain.ino.bin" \
  "$OUT/S3-Brain-includes-C5-v${VERSION}-application.bin"

cat > "$OUT/READ_ME_FIRST.txt" <<EOF
CuteDisplay combined firmware build: S3 Brain + C5 v$VERSION
=======================================================
HARDWARE-TESTED: on 2026-10-27 user confirmed C5 v1 -> v2 UART OTA,
C5 reboot, post-boot version success, Kitty and iPhone app functionality.

NORMAL UPLOAD (existing C5 OTA-capable firmware v1 or later):
1. Open CuteDisplayBrain/CuteDisplayBrain.ino FROM THIS ARTIFACT.
2. Choose ESP32S3 Dev Module, 16 MB flash, OPI PSRAM, Custom
   partition scheme (included partitions.csv); select S3 USB port.
3. Before compiling in Arduino IDE, install:
   - esp32_opus from https://github.com/sh123/esp32_opus_arduino\n     (Code > Download ZIP, then Sketch > Include Library > Add .ZIP Library).\n     Confirm Serial Monitor prints Opus compiled=1 in [VOICE] logs; if 0,\n     the library was not found by the local Arduino IDE build.
   - MP3 playback uses bundled minimp3.h; no ESP8266Audio library needed.
   The combined GitHub Actions build installs these dependencies.
4. Upload ONLY the S3 sketch, then open Serial Monitor at 115200.
5. S3 upgrades C5 automatically ONLY if bundled version is newer.
   Expect: [S3 OTA] SUCCESS: new display firmware confirmed after reboot

The CombinedFirmwareImage.h from the normal repository is deliberately EMPTY.
Never upload the repository's S3 sketch as a combined firmware release;
always use the generated CuteDisplayBrain folder from this artifact.
Never overwrite the generated header with the repository placeholder.

FIRST-TIME BOOTSTRAP ONLY (if C5 does not yet have OTA receiver):
Open lcd/lcd.ino from this artifact and upload to the C5 over USB
with ESP32C5 Dev Module, 16 MB flash, enabled PSRAM, Custom partition.
Future upgrades need only the S3 USB. Keep direct C5 USB recovery available.
Avoid powering two USB sources with a shared 5V bridge connected.

CuteDisplay-CombinedFirmware.bin is the SINGLE compiled S3 application that embeds the C5 firmware.\nIt already contains all S3 .ino/.h/.cpp changes and the C5 firmware update.\nThe .bin files are APPLICATION images, NOT complete factory images.
Do not flash app-only binaries to offset 0x0.
EOF
echo "[5/5] Combined firmware available at: $OUT"
ls -lh "$OUT/"*.bin
echo "Open $OUT/CuteDisplayBrain/CuteDisplayBrain.ino in Arduino IDE"
