#!/usr/bin/env bash
# Compile and package S3 Brain only. Does not upload, flash, reboot or touch SD.
# Intentionally excludes any C5 application payload.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CORE="$HOME/.arduino15/packages/esp32/hardware/esp32/3.3.12"
FQBN='esp32:esp32:esp32s3:FlashSize=16M,PSRAM=opi,PartitionScheme=custom,CDCOnBoot=cdc,LoopCore=1,EventsCore=0,CPUFreq=240'
ARDUINO_CLI="${ARDUINO_CLI:-arduino-cli}"
OUT="${KITTY_S3_ONLY_OUT:-$ROOT/s3-only-candidate}"
HEADER="$ROOT/firmware/CuteDisplayBrain/CombinedFirmwareImage.h"
PARTITIONS="$CORE/tools/partitions/default_16MB.csv"
for cmd in "$ARDUINO_CLI" python3 sha256sum; do
  command -v "$cmd" >/dev/null || { echo "Missing command: $cmd" >&2; exit 1; }
done
test -s "$PARTITIONS" || { echo "Missing ESP32 core partition table" >&2; exit 1; }
test -s "$HEADER" || { echo "Missing C5 image placeholder" >&2; exit 1; }
# Reject a previously generated combined firmware header, even if copied by accident.
python3 - "$HEADER" <<'PY'
import pathlib, re, sys
source = pathlib.Path(sys.argv[1]).read_text()
checks = (
    r'inline\s+constexpr\s+uint32_t\s+version\s*=\s*0\s*;',
    r'inline\s+constexpr\s+size_t\s+length\s*=\s*0\s*;',
    r'inline\s+constexpr\s+char\s+sha256\[\]\s*=\s*""\s*;',
    r'bytes\[\]\s+PROGMEM\s*=\s*\{0\}\s*;',
)
if not all(re.search(pattern, source) for pattern in checks):
    sys.exit("REFUSED: C5 image is not the empty placeholder")
print("PASS: no embedded C5 OTA image")
PY
if [ -e "$OUT" ]; then
  echo "Refusing to overwrite existing output: $OUT" >&2
  echo "Set KITTY_S3_ONLY_OUT to a NEW path if needed." >&2
  exit 1
fi
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/CuteDisplayBrain" "$WORK/build" "$OUT"
cp -R "$ROOT/firmware/CuteDisplayBrain/." "$WORK/CuteDisplayBrain/"
cp "$PARTITIONS" "$WORK/CuteDisplayBrain/partitions.csv"
"$ARDUINO_CLI" compile --clean --fqbn "$FQBN" \
  --build-path "$WORK/build" "$WORK/CuteDisplayBrain"
BIN="$WORK/build/CuteDisplayBrain.ino.bin"
test -s "$BIN" || { echo "S3 application binary not generated" >&2; exit 1; }
cp "$BIN" "$OUT/S3-Brain-application.bin"
( cd "$OUT" && sha256sum S3-Brain-application.bin > SHA256SUMS.txt )
cat > "$OUT/README.txt" <<EOF
Kitty V6 S3-only compile candidate
Source revision: $(git -C "$ROOT" rev-parse HEAD)
FQBN: $FQBN
C5 image payload: absent (version 0, length 0)
File: S3-Brain-application.bin
SHA256: $(sha256sum "$OUT/S3-Brain-application.bin" | cut -d' ' -f1)

This is an application-only binary. NOT a full-flash/factory image.
DO NOT flash at offset 0x0.
This build script never uploads to a board or performs a C5 OTA.
Do not use the combined firmware release script to prepare an S3-only update.
No hardware validation or flash partition/NVS preservation is implied.
EOF
echo "S3-only compile succeeded: $OUT/S3-Brain-application.bin"
echo "No flash performed, no C5 image embedded."
