#!/usr/bin/env python3
"""Inspect the installed ESP32-S3 partition table through USB.

Reads exactly 4096 bytes at flash offset 0x8000 using esptool; DOES NOT
write firmware, erase flash, or modify partitions. USB inspection resets the
board briefly. Never use during a realtime conversation or C5 update.
"""
import argparse
import json
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

PARTITION_OFFSET = 0x8000
PARTITION_LENGTH = 0x1000
ENTRY_LENGTH = 32
MAGIC = 0x50AA
OTA_SUBTYPES = {0x10: "ota_0", 0x11: "ota_1"}

def decode_table(data):
    if len(data) != PARTITION_LENGTH:
        raise ValueError("Expected exactly 4096 partition bytes")
    entries = []
    for offset in range(0, len(data), ENTRY_LENGTH):
        chunk = data[offset:offset+ENTRY_LENGTH]
        magic, kind, subtype, address, size, label, flags = struct.unpack("<HBBII16sI", chunk)
        if magic == 0xFFFF:
            break
        if magic == 0xEBEB:  # optional MD5 table entry
            break
        if magic != MAGIC:
            raise ValueError(f"Unexpected partition entry magic at +0x{offset:x}: 0x{magic:04X}")
        entries.append({"name": label.split(b"\x00", 1)[0].decode("ascii", errors="replace"),
                        "type": kind, "subtype": subtype, "offset": address,
                        "size": size, "flags": flags,
                        "ota_name": OTA_SUBTYPES.get(subtype) if kind == 0 else None})
    if not entries:
        raise ValueError("No valid partition entries")
    slots = [e for e in entries if e["ota_name"]]
    return {"entries": entries,
            "ota_slots": slots,
            "has_two_ota_slots": len(slots) == 2,
            "combined_image_bytes": 4166400,
            "combined_fits_both_slots": len(slots) == 2 and all(e["size"] >= 4166400 for e in slots),
            "note": "Partition capacity check only; S3 OTA receiver and rollback still required."}

def main():
    p = argparse.ArgumentParser(description="Read-only USB inspection of installed S3 partition sizes")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--port", help="USB serial device physically connected to ESP32-S3")
    group.add_argument("--partition-bin", type=Path, help="Previously read 4096-byte partition table")
    p.add_argument("--image", type=Path, help="Combined S3 application .bin to compare")
    args = p.parse_args()
    if args.partition_bin:
        data = args.partition_bin.read_bytes()
    else:
        with tempfile.TemporaryDirectory(prefix="kitty-s3-partitions-") as tmp:
            dest = Path(tmp) / "partition-table.bin"
            # esptool 4.x/5.x supports the read_flash spelling.
            command = [sys.executable, "-m", "esptool", "--chip", "esp32s3",
                       "--port", args.port, "read_flash", hex(PARTITION_OFFSET),
                       hex(PARTITION_LENGTH), str(dest)]
            print("USB read only: flash 0x8000..0x8FFF. S3 may reset. No writes.", file=sys.stderr)
            subprocess.run(command, check=True)
            data = dest.read_bytes()
    report = decode_table(data)
    if args.image:
        image = args.image.read_bytes()
        if not image or image[0] != 0xE9:
            raise ValueError("Invalid ESP image header")
        report["combined_image_bytes"] = len(image)
        report["combined_fits_both_slots"] = report["has_two_ota_slots"] and all(
            e["size"] >= len(image) for e in report["ota_slots"])
    print(json.dumps(report, indent=2))
    print("No flash modifications performed. Capability size does not authorize OTA.")
if __name__ == "__main__":
    main()
