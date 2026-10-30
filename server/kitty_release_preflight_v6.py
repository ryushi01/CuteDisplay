#!/usr/bin/env python3
"""Read-only release inspection; never deploys or changes release state."""
import argparse
import hashlib
import json
from pathlib import Path

S3_16M_SLOT_BYTES = 0x640000
C5_IMAGE_MAX = 0x640000

def inspect_release(release_dir, installed_next_slot=None):
    directory = Path(release_dir)
    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    name = metadata["filename"]
    if "/" in name or "\\" in name or name.startswith(".") or ".." in name:
        raise ValueError("unsafe artifact name")
    image = directory / name
    if image.is_symlink() or not image.is_file():
        raise ValueError("artifact missing or symlinked")
    digest = hashlib.sha256()
    size = 0
    first_byte = None
    with image.open("rb") as f:
        while chunk := f.read(65536):
            if first_byte is None:
                first_byte = chunk[0]
            size += len(chunk)
            digest.update(chunk)
    result = {
        "id": metadata["id"],
        "kind": metadata["kind"],
        "filename": name,
        "size": size,
        "sha256": digest.hexdigest(),
        "checksum_valid": size == metadata["size"] and digest.hexdigest() == metadata["sha256"],
        "image_header_valid": first_byte == 0xE9 if name.lower().endswith(".bin") else None,
        "release_slot_fit": None,
        "installed_slot_fit": None,
        "deploy_allowed": False,
        "blockers": [],
    }
    if not result["checksum_valid"]:
        result["blockers"].append("artifact checksum or length mismatch")
    if name.lower().endswith(".bin"):
        if not result["image_header_valid"]:
            result["blockers"].append("invalid ESP application image header")
        if metadata["kind"] in ("s3", "bundle"):
            result["release_slot_fit"] = size <= S3_16M_SLOT_BYTES
            if not result["release_slot_fit"]:
                result["blockers"].append("exceeds reference S3 16 MB OTA slot")
            if installed_next_slot is None:
                result["blockers"].append("installed S3 OTA partition size unknown")
            else:
                result["installed_slot_fit"] = size <= installed_next_slot
                if not result["installed_slot_fit"]:
                    result["blockers"].append("exceeds installed S3 OTA slot")
        elif metadata["kind"] == "c5" and size > C5_IMAGE_MAX:
            result["blockers"].append("exceeds expected C5 OTA slot")
    if metadata.get("state") != "quarantined":
        result["blockers"].append("artifact is not quarantined")
    result["blockers"].append("authenticated S3 OTA receiver and verified rollback not implemented")
    return result

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("release_dir")
    ap.add_argument("--installed-s3-next-slot", type=int, default=None)
    args = ap.parse_args()
    print(json.dumps(inspect_release(args.release_dir, args.installed_s3_next_slot),
                     indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
