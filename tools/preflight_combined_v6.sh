#!/usr/bin/env bash
# Verify known combined S3/C5 dependencies before any release output is created.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CLI="${ARDUINO_CLI:-arduino-cli}"
CORE="$HOME/.arduino15/packages/esp32/hardware/esp32/3.3.12"
FONT="/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FAIL=0
check(){ if "$@" >/dev/null 2>&1; then printf 'PASS %s\n' "$*"; else printf 'FAIL %s\n' "$*" >&2; FAIL=1; fi; }
echo "Kitty V6 combined release dependency preflight"
for cmd in git python3 curl sha256sum; do check command -v "$cmd"; done
check command -v "$CLI"
check test -s "$FONT"
check python3 -c 'from PIL import Image, ImageFont, ImageDraw'
check test -s "$CORE/tools/partitions/default_16MB.csv"
check test -s "$ROOT/tools/package_c5_firmware.py"
check test -s "$ROOT/tools/generate_c5_japanese_font.py"
check test -s "$ROOT/firmware/CuteDisplay/C5FirmwareVersion.h"
check test -s "$ROOT/firmware/CuteDisplayBrain/CuteDisplayBrain.ino"
check test -s "$ROOT/firmware/CuteDisplay/lcd.ino"
if command -v "$CLI" >/dev/null 2>&1; then
  check "$CLI" core list
  for lib in WebSockets ESP8266Audio; do
    if "$CLI" lib list 2>/dev/null | grep -q "^$lib "; then
      echo "PASS Arduino library $lib"
    else
      echo "FAIL Arduino library $lib" >&2; FAIL=1
    fi
  done
  if "$CLI" core list | grep -Eq '^esp32:esp32[[:space:]]+3\.3\.12([[:space:]]|$)'; then
    echo 'PASS Arduino ESP32 3.3.12'
  else
    echo 'FAIL Arduino ESP32 3.3.12' >&2; FAIL=1
  fi
fi
if [ -d "$ROOT/.git" ]; then
  echo "Git commit: $(git -C "$ROOT" rev-parse --short HEAD)"
fi
echo 'Network requirement: GitHub access is needed to fetch LILYGO drivers (checked during build).'
echo 'Disk space:'
df -h "$ROOT"
if [ "$FAIL" -ne 0 ]; then
  echo 'Dependency preflight FAILED; do not start combined build.' >&2
  exit 1
fi
echo 'Dependency preflight PASS'
