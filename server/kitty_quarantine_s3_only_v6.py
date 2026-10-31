#!/usr/bin/env python3
"""Quarantine a compiled S3-only application in Kitty Update Center.

No OTA publication, service restart, boot-slot modification, or flashing.
"""
import argparse
import hashlib
import json
from pathlib import Path

from kitty_update_center_v6 import ROOT, store_release

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", type=Path, required=True)
    ap.add_argument("--checksum-file", type=Path, required=True)
    args = ap.parse_args()
    image = args.image.resolve(strict=True)
    if image.name != "S3-Brain-application.bin" or image.is_symlink():
        ap.error("Expected the S3-only build artifact, not a combined release")
    data = image.read_bytes()
    if not (1024 <= len(data) <= 6553600) or data[:1] != bytes([0xE9]):
        ap.error("Invalid or oversized ESP32 application image")
    digest = hashlib.sha256(data).hexdigest()
    entries = args.checksum_file.read_text().splitlines()
    expected = f"{digest}  S3-Brain-application.bin"
    if expected not in entries:
        ap.error("SHA256SUMS.txt does not match the S3-only image")
    # The output directory and on-disk release metadata remain distinct.
    metadata = store_release("s3", image.name, data)
    print(json.dumps({
        "quarantined_release_id": metadata["id"],
        "kind": metadata["kind"],
        "size": metadata["size"],
        "sha256": metadata["sha256"],
        "release_directory": str(ROOT / metadata["id"]),
        "published_to_ota": False,
        "device_updated": False
    }, indent=2))
    print("Stored in quarantine ONLY. Existing OTA approval and running S3 are unchanged.")

if __name__ == "__main__":
    main()
