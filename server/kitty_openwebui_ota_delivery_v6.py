#!/usr/bin/env python3
"""Read-only, explicit-release HTTPS OTA delivery for existing Kitty Update Center.

No firmware installation, approval, boot switching, or automatic publication.
Register with Open WebUI FastAPI only after secure configuration and review.
Never serve an arbitrary path or the quarantined release by default.
"""
import hashlib
import hmac
import json
import os
import re
from pathlib import Path
from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

PREFIX = "/kitty-v6/update"
ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$")
MAX_IMAGE = 6553600

def register(app):
    if os.getenv("KITTY_WEBUI_OTA_ENABLED") != "1":
        return False
    token_file = Path(os.environ["KITTY_WEBUI_OTA_DEVICE_TOKEN_FILE"])
    root = Path(os.environ["KITTY_WEBUI_OTA_RELEASE_ROOT"]).resolve(strict=True)
    approved = os.environ.get("KITTY_WEBUI_OTA_APPROVED_ID", "")
    if not ID.fullmatch(approved):
        raise RuntimeError("No explicit OTA release approval")
    if not token_file.is_file() or token_file.is_symlink():
        raise RuntimeError("OTA token file invalid")
    token = token_file.read_text().strip()
    if len(token) < 32:
        raise RuntimeError("OTA token too short")
    release_dir = root / approved
    if release_dir.is_symlink() or not release_dir.is_dir():
        raise RuntimeError("OTA release missing")
    metadata = json.loads((release_dir / "metadata.json").read_text())
    if metadata.get("id") != approved or metadata.get("kind") != "s3":
        raise RuntimeError("Wrong OTA release")
    image_name = metadata.get("filename")
    # Only these application-image names are eligible for OTA delivery.
    # An S3-only release cannot trigger the C5 updater via embedded payload.
    # Explicit approval, kind=s3, immutable checksum and image-size checks
    # remain mandatory; no release is published or activated here.
    if image_name not in ("CuteDisplay-CombinedFirmware.bin", "S3-Brain-application.bin"):
        raise RuntimeError("Unexpected OTA image name")
    image_file = release_dir / image_name
    if image_file.is_symlink() or not image_file.is_file():
        raise RuntimeError("OTA image invalid")
    size = image_file.stat().st_size
    if not (1024 <= size <= MAX_IMAGE) or metadata.get("size") != size:
        raise RuntimeError("OTA image size incompatible")
    digest = hashlib.file_digest(image_file.open("rb"), "sha256").hexdigest()
    if image_file.open("rb").read(1) != bytes([0xE9]) or not hmac.compare_digest(digest, str(metadata.get("sha256", ""))):
        raise RuntimeError("OTA image checksum or header invalid")
    manifest = {"release_id":approved, "size":size, "sha256":digest,
                "image_path":PREFIX+"/image", "application_only":True,
                "requires_manual_boot_authorization":True}

    def authorized(request):
        return hmac.compare_digest(request.headers.get("authorization", ""), "Bearer "+token)

    async def describe(request: Request):
        if not authorized(request):
            return JSONResponse({"error":"unauthorized"},status_code=401)
        return JSONResponse(manifest,headers={"Cache-Control":"no-store"})

    async def download(request: Request):
        if not authorized(request):
            return JSONResponse({"error":"unauthorized"},status_code=401)
        # No range requests: a consumer must verify the full image checksum.
        if request.headers.get("range"):
            return JSONResponse({"error":"range_not_supported"},status_code=416)
        def chunks():
            with image_file.open("rb") as f:
                while piece := f.read(4096):
                    yield piece
        return StreamingResponse(chunks(), media_type="application/octet-stream",
                headers={"Content-Length":str(size),"Cache-Control":"no-store",
                         "X-Content-Type-Options":"nosniff"})
    app.add_api_route(PREFIX+"/manifest", describe, methods=["GET"], include_in_schema=False)
    app.add_api_route(PREFIX+"/image", download, methods=["GET"], include_in_schema=False)
    return True
