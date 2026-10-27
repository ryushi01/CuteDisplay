#!/usr/bin/env python3
"""Create/upload a complete S3 project from one generated C5FirmwareImage.h.

Run inside a current CuteDisplay repository checkout:
  python3 tools/prepare_s3_from_c5_header.py ~/Downloads/C5FirmwareImage.h
  python3 tools/prepare_s3_from_c5_header.py ~/Downloads/C5FirmwareImage.h --compile
  python3 tools/prepare_s3_from_c5_header.py ~/Downloads/C5FirmwareImage.h --compile --upload --port /dev/cu.usbmodemXXXX

Only the supplied C5 firmware header is replaced in the *generated* project;
the S3 source and supporting headers come from this repository.
"""
import argparse
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "firmware" / "CuteDisplayBrain"
DEFAULT_OUT = ROOT / "prepared-firmware"
BOARD = "esp32:esp32:esp32s3:FlashSize=16M,PSRAM=opi,PartitionScheme=custom"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("header", type=Path, help="Generated (nonempty) C5FirmwareImage.h")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--compile", action="store_true", help="Compile the prepared S3 project using arduino-cli")
    parser.add_argument("--upload", action="store_true", help="Upload compiled sketch over S3 USB (requires --port)")
    parser.add_argument("--port", help="S3 USB serial port, e.g. /dev/cu.usbmodem1234")
    args = parser.parse_args()

    if args.upload and (not args.compile or not args.port):
        parser.error("--upload requires --compile and --port")
    header = args.header.expanduser().resolve()
    if not header.is_file():
        parser.error("C5 header not found: " + str(header))
    if header.name != "C5FirmwareImage.h":
        parser.error("Expected the generated file named C5FirmwareImage.h")
    # Check version, nonzero firmware size, and image magic before building.
    # Do not parse the huge firmware hex array into Python memory.
    data = header.read_text(encoding="ascii")
    def field(pattern):
        match = re.search(pattern, data)
        return int(match.group(1)) if match else 0
    version = field(r"inline\s+constexpr\s+uint32_t\s+version\s*=\s*(\d+)\s*(?:UL)?\s*;")
    length = field(r"inline\s+constexpr\s+size_t\s+length\s*=\s*(\d+)\s*(?:UL)?\s*;")
    if version < 2 or not 1024 <= length <= 0x640000:
        parser.error("C5 firmware header is empty or invalid; use the generated build artifact")
    if not re.search(r"static\s+const\s+uint8_t\s+bytes\[\]\s+PROGMEM\s*=\s*\{\s*0x[eE]9\s*,", data):
        parser.error("C5 image does not start with ESP application image magic 0xE9")

    output = args.output.expanduser().resolve()
    sketch = output / "CuteDisplayBrain"
    if output == ROOT or SOURCE == sketch or SOURCE in sketch.parents:
        parser.error("Output must be separate from original firmware source")
    if output.exists():
        shutil.rmtree(output)
    shutil.copytree(SOURCE, sketch)
    shutil.copy2(header, sketch / "C5FirmwareImage.h")
    # The sketch's custom 16MB partition layout must match the OTA-capable C5.
    if not (sketch / "partitions.csv").exists():
        search = [
            Path.home() / "Library/Arduino15/packages/esp32/hardware/esp32/3.3.12/tools/partitions/default_16MB.csv",
            Path.home() / ".arduino15/packages/esp32/hardware/esp32/3.3.12/tools/partitions/default_16MB.csv",
        ]
        partition = next((p for p in search if p.is_file()), None)
        if not partition:
            parser.error("Arduino-ESP32 core 3.3.12 required for its custom partitions.csv")
        shutil.copy2(partition, sketch / "partitions.csv")

    print(f"Prepared S3 firmware with embedded C5 v{version} ({length:,} bytes):")
    print(f"  {sketch / 'CuteDisplayBrain.ino'}")
    if args.compile:
        if not shutil.which("arduino-cli"):
            parser.error("Install arduino-cli, or omit --compile and upload in Arduino IDE")
        subprocess.run(["arduino-cli", "compile", "--clean", "--fqbn", BOARD, str(sketch)], check=True)
        print("S3 compilation succeeded.")
    if args.upload:
        print("Uploading to S3 only on", args.port)
        subprocess.run(["arduino-cli", "upload", "--fqbn", BOARD,
                        "--port", args.port, str(sketch)], check=True)
        print("S3 upload requested. Monitor at 115200 for any C5 UART OTA update.")
    else:
        print("Open CuteDisplayBrain.ino in Arduino IDE (ESP32S3 Dev Module, 16MB, OPI PSRAM, Custom partitions).")
    print("NOTE: C5 updates only if its version is older than the bundled image.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, subprocess.CalledProcessError) as error:
        sys.exit(f"ERROR: {error}")
