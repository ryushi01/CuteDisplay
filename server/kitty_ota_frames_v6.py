"""Kitty V6 bounded authenticated-LAN OTA framing (offline preparation only).

Frames are for a future idle-only device transport. This module never opens a
socket or deploys a release; an authenticated transport must be established
separately. Framing explicitly binds sequence/offset/chunk bytes to the digest.
"""
import hashlib
import hmac

MAX_FRAME_BYTES = 187
CHUNK_BYTES = 48

def decode_key(value):
    if len(value) != 64:
        raise ValueError("device key must be 64 hexadecimal characters")
    try:
        return bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError("bad device key") from exc

def start_frame(size, digest):
    if not isinstance(size, int) or not 1024 <= size <= 0x640000:
        raise ValueError("invalid firmware size")
    if len(digest) != 64:
        raise ValueError("invalid SHA256")
    bytes.fromhex(digest)
    return f"OTA_BEGIN {size} {digest.lower()}"

def chunk_frame(key, session_nonce, offset, data):
    if len(key) != 32 or len(session_nonce) != 16:
        raise ValueError("missing per-session credentials")
    if not isinstance(offset, int) or offset < 0 or offset > 0xffffffff:
        raise ValueError("invalid offset")
    if not data or len(data) > CHUNK_BYTES:
        raise ValueError("invalid chunk length")
    payload = offset.to_bytes(4, "big") + data
    mac = hmac.new(key, session_nonce + payload, hashlib.sha256).hexdigest()[:32]
    frame = f"OTA_DATA {offset:08x} {data.hex()} {mac}"
    if len(frame) > MAX_FRAME_BYTES:
        raise ValueError("frame too large")
    return frame

def iter_frames(data, key, nonce):
    for offset in range(0, len(data), CHUNK_BYTES):
        yield chunk_frame(key, nonce, offset, data[offset:offset + CHUNK_BYTES])
