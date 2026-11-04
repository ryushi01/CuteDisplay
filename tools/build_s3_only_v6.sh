#!/usr/bin/env bash
# Compile and package S3 Brain only. Does not upload, flash, reboot or touch SD.
# Intentionally excludes any C5 application payload.
set -euo pipefail
umask 077
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PRIVATE_HEADER="${KITTY_SYNC_PRIVATE_HEADER:-}"
if [ -n "$PRIVATE_HEADER" ]; then
  if [ "${GITHUB_ACTIONS:-}" = "true" ] || [ "${CI:-}" = "true" ]; then
    echo "REFUSED: private sync credentials must never be included in CI" >&2
    exit 1
  fi
  python3 - "$PRIVATE_HEADER" <<'PY'
from pathlib import Path
import json, re, sys
p = Path(sys.argv[1])
if not p.is_file() or p.is_symlink() or p.stat().st_size > 65536:
    sys.exit("REFUSED: private sync header unavailable or unsafe")
try:
    source = p.read_text(encoding="utf-8")
    values = {}
    for name in ("KITTY_SYNC_V6_URL", "KITTY_SYNC_V6_DEVICE_TOKEN", "KITTY_SYNC_V6_CA_PEM"):
        rows = re.findall(r"^#define[ \\t]+" + name + r"[ \\t]+(.+)$", source, re.M)
        if len(rows) != 1:
            raise ValueError("macro missing or repeated")
        values[name] = json.loads(rows[0].strip())
    if (values["KITTY_SYNC_V6_URL"] != "https://ragnarok-project.com/kitty-v6/sync"
            or not isinstance(values["KITTY_SYNC_V6_DEVICE_TOKEN"], str)
            or len(values["KITTY_SYNC_V6_DEVICE_TOKEN"]) < 32
            or any(c.isspace() for c in values["KITTY_SYNC_V6_DEVICE_TOKEN"])
            or not isinstance(values["KITTY_SYNC_V6_CA_PEM"], str)
            or "-----BEGIN CERTIFICATE-----" not in values["KITTY_SYNC_V6_CA_PEM"]
            or "-----END CERTIFICATE-----" not in values["KITTY_SYNC_V6_CA_PEM"]):
        raise ValueError("incomplete sync settings")
except (OSError, UnicodeError, TypeError, ValueError):
    sys.exit("REFUSED: private sync header has invalid settings (values hidden)")
print("PASS: private sync settings validated (credentials hidden)")
PY
fi

FQBN='esp32:esp32:esp32s3:FlashSize=16M,PSRAM=opi,PartitionScheme=custom,CDCOnBoot=cdc,LoopCore=1,EventsCore=0,CPUFreq=240'
ARDUINO_CLI="${ARDUINO_CLI:-arduino-cli}"
if [ -n "$PRIVATE_HEADER" ]; then
  # Credential-bearing S3 binaries/sketches must never enter a repo or CI artifact.
  OUT="${KITTY_S3_ONLY_OUT:-$HOME/.local/share/kitty-v6/private-builds/s3-only-$(date -u +%Y%m%dT%H%M%SZ)-$}"
  python3 - "$ROOT" "$OUT" <<'PY'
from pathlib import Path
import sys
repo = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2]).expanduser().resolve()
if out == repo or repo in out.parents:
    sys.exit("REFUSED: private build output inside Git repository")
PY
else
  OUT="${KITTY_S3_ONLY_OUT:-$ROOT/s3-only-candidate}"
fi
HEADER="$ROOT/firmware/CuteDisplayBrain/CombinedFirmwareImage.h"
PARTITIONS=""
for core in "$HOME/.arduino15/packages/esp32/hardware/esp32/3.3.12" \\
            "$HOME/Library/Arduino15/packages/esp32/hardware/esp32/3.3.12"; do
  if [ -f "$core/tools/partitions/default_16MB.csv" ]; then
    PARTITIONS="$core/tools/partitions/default_16MB.csv"
    break
  fi
done
for cmd in "$ARDUINO_CLI" python3 sha256sum; do
  command -v "$cmd" >/dev/null || { echo "Missing command: $cmd" >&2; exit 1; }
done
test -n "$PARTITIONS" && test -s "$PARTITIONS" || { echo "Missing ESP32 core 3.3.12 partition table" >&2; exit 1; }
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
if [ -e "$OUT" ] || [ -L "$OUT" ]; then
  echo "Refusing to overwrite existing output: $OUT" >&2
  echo "Set KITTY_S3_ONLY_OUT to a NEW path if needed." >&2
  exit 1
fi
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/CuteDisplayBrain" "$WORK/build" "$OUT"
chmod 700 "$OUT"
cp -R "$ROOT/firmware/CuteDisplayBrain/." "$WORK/CuteDisplayBrain/"
# Never inherit an unreviewed private header from a checkout.
rm -f "$WORK/CuteDisplayBrain/KittySyncPrivateConfig.h"
if [ -n "$PRIVATE_HEADER" ]; then
  cp "$PRIVATE_HEADER" "$WORK/CuteDisplayBrain/KittySyncPrivateConfig.h"
  chmod 600 "$WORK/CuteDisplayBrain/KittySyncPrivateConfig.h"
fi
cp "$PARTITIONS" "$WORK/CuteDisplayBrain/partitions.csv"
"$ARDUINO_CLI" compile --clean --fqbn "$FQBN" \
  --build-path "$WORK/build" "$WORK/CuteDisplayBrain"
BIN="$WORK/build/CuteDisplayBrain.ino.bin"
test -s "$BIN" || { echo "S3 application binary not generated" >&2; exit 1; }
cp "$BIN" "$OUT/S3-Brain-application.bin"
chmod 600 "$OUT/S3-Brain-application.bin"
if [ -n "$PRIVATE_HEADER" ]; then
  # Private local IDE project. Never copy this source bundle to public artifacts.
  mkdir -p "$OUT/CuteDisplayBrain"
  cp -R "$WORK/CuteDisplayBrain/." "$OUT/CuteDisplayBrain/"
  chmod 700 "$OUT/CuteDisplayBrain"
  chmod 600 "$OUT/CuteDisplayBrain/KittySyncPrivateConfig.h"
fi
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
echo "No flash performed, no C5 image embedded.
Sync private configuration: $([ -n "$PRIVATE_HEADER" ] && echo included || echo absent).
$([ -n "$PRIVATE_HEADER" ] && printf '%s' "PRIVATE BUILD: contains credential-bearing S3 binary and Arduino source.
Keep this directory private. Do not attach, publish, upload to GitHub Actions, or share.
To upload: open CuteDisplayBrain/CuteDisplayBrain.ino from this private output
in Arduino IDE with ESP32S3 Dev Module, 16MB Flash, OPI PSRAM, Custom
partitions (included partitions.csv), USB CDC On Boot enabled, Loop/Arduino
Core 1, Events Core 0, CPU 240MHz. Upload only S3; DO NOT erase NVS/SD.
Check memory sync status after boot. C5 version remains unchanged.
" || true)"
