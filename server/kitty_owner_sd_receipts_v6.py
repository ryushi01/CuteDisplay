#!/usr/bin/env python3
"""Immutable owner-turn provenance receipts for S3 microSD archive rows.

SOURCE ONLY: no live receipt issuer, S3 acknowledgement handler, SD writer,
or configured signing key. No probable voice match, claimed name, device
token, or owner session grant alone becomes verified owner memory.

A future trusted gateway adapter may mint a receipt ONLY after a verified
owner grant, exact microphone-audio-bound per-turn speaker ticket, and an
independently checked S3 SD-worker archive acknowledgement. The receipt
belongs on S3 microSD, not a second Ubuntu memory authority. Ubuntu's
derived index verifies the long-lived HMAC over exact archive bytes.

Do not use caller JSON or an SD sidecar as the archive-ack validator.
Do not expose issue_owner_receipt as a public API endpoint.
"""
import base64
import hashlib
import hmac
import os
from pathlib import Path
import re
import time

from kitty_attested_live_call_v6 import (
    ITEM, SESSION, AUDIO_HASH, _digest, verify_external_attestation,
)
from kitty_owner_session_v6 import verify_grant

RECEIPT_NAME = "owner_turn_receipts_v6.tsv"
VERSION = "owner-v1"
MAX_RECEIPTS_BYTES = 4 * 1024 * 1024
MAX_RECEIPT_LINE = 1024
MAX_RECEIPTS = 4096
MAX_ARCHIVED_LINE = 1200
MAX_TIMESTAMP_DRIFT = 600
MAX_OFFSET = (1 << 32) - 1
HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
MAC = re.compile(r"[A-Za-z0-9_-]{43}\Z")


def _mac(key, payload):
    return base64.urlsafe_b64encode(
        hmac.new(key, payload, hashlib.sha256).digest()
    ).rstrip(b"=").decode("ascii")


def _archive_question(raw_line, stamp):
    """Extract exact archived user input from original S3 TSV bytes."""
    if (not isinstance(raw_line, bytes)
            or not 5 <= len(raw_line) <= MAX_ARCHIVED_LINE
            or not raw_line.endswith(b"\n")
            or b"\r" in raw_line or b"\0" in raw_line):
        return None
    parts = raw_line[:-1].split(b"\t")
    if len(parts) != 3 or parts[0] != str(stamp).encode("ascii"):
        return None
    try:
        text = parts[1].decode("utf-8", "strict")
        answer = parts[2].decode("utf-8", "strict")
    except UnicodeDecodeError:
        return None
    if not text or not answer or _digest(text) is None:
        return None
    return text


def issue_owner_receipt(
        receipt_secret, owner_grant_secret, turn_issuer_secret, *,
        session_id, item_id, transcript, audio_sha256,
        owner_grant, signed_turn, archive_ack, trusted_ack_validator,
        now=None):
    """Sign an exact S3 row after independent owner and SD-ack verification.

    archive_ack MUST originate from an S3 SD-worker acknowledgement matched
    by the trusted gateway to the very same upstream provider item.
    The injected trusted_ack_validator MUST verify that independently.
    A caller-provided flag or JSON echo is never sufficient.
    """
    secrets = (receipt_secret, owner_grant_secret, turn_issuer_secret)
    if (any(not isinstance(s, bytes) or len(s) < 32 for s in secrets)
            or len(set(secrets)) != 3
            or not isinstance(session_id, str) or not SESSION.fullmatch(session_id)
            or not isinstance(item_id, str) or not ITEM.fullmatch(item_id)
            or _digest(transcript) is None
            or not isinstance(audio_sha256, str)
            or not AUDIO_HASH.fullmatch(audio_sha256)
            or not isinstance(signed_turn, str)
            or not callable(trusted_ack_validator)
            or not isinstance(archive_ack, dict)):
        return None
    wall = int(time.time() if now is None else now)
    if not verify_grant(owner_grant_secret, owner_grant, session_id, now=wall):
        return None
    # Require this audio hash: transcript-only and learning tickets do not
    # satisfy the durable-owner record policy.
    if verify_external_attestation(
            turn_issuer_secret, signed_turn, session_id=session_id,
            item_id=item_id, transcript=transcript,
            audio_sha256=audio_sha256, now=wall, purpose="turn") != (
            "person:owner", "owner"):
        return None
    if archive_ack.get("source") != "trusted_s3_sd_worker_ack":
        return None
    if archive_ack.get("session_id") != session_id or archive_ack.get("item_id") != item_id:
        return None
    stamp, offset = archive_ack.get("stamp"), archive_ack.get("offset")
    raw = archive_ack.get("raw_line")
    if (type(stamp) is not int or type(offset) is not int
            or not 1 <= stamp <= MAX_OFFSET
            or not 0 <= offset <= MAX_OFFSET
            or abs(wall - stamp) > MAX_TIMESTAMP_DRIFT
            or _archive_question(raw, stamp) != transcript):
        return None
    try:
        if trusted_ack_validator(
                session_id=session_id, item_id=item_id, stamp=stamp,
                offset=offset, raw_line=raw) is not True:
            return None
    except Exception:
        return None
    fields = (
        VERSION, str(stamp), str(offset), session_id, item_id,
        _digest(transcript), audio_sha256, hashlib.sha256(raw).hexdigest(),
        hashlib.sha256(signed_turn.encode("utf-8")).hexdigest(), str(wall),
    )
    body = "\t".join(fields).encode("ascii")
    return body + b"\t" + _mac(receipt_secret, body).encode("ascii") + b"\n"



def issue_provisional_owner_receipt(
        receipt_secret, owner_grant_secret, turn_issuer_secret, *,
        session_id, item_id, transcript, audio_sha256,
        owner_grant, signed_turn, authenticated_archive_ack,
        trusted_ack_validator, now=None):
    """Sign a *pending* S3 owner receipt before the next finalized SD export.

    This is a receipt-writing authorization, NOT proof that snapshot contents
    have been verified. The eventual snapshot index independently checks the
    HMAC, exact archived question and original row SHA-256. If S3 changes or
    misreports the row, the receipt confers no owner identity.

    Only call this privately from an authenticated gateway handling the
    original S3 SD-worker ACK on the same live socket. The trusted validator
    MUST corroborate channel identity, epoch, item, one-time ACK provenance;
    it must NOT be an echo of client-controlled JSON.
    """
    keys = (receipt_secret, owner_grant_secret, turn_issuer_secret)
    if (any(not isinstance(k, bytes) or len(k) < 32 for k in keys)
            or len(set(keys)) != 3
            or not isinstance(session_id, str) or not SESSION.fullmatch(session_id)
            or not isinstance(item_id, str) or not ITEM.fullmatch(item_id)
            or _digest(transcript) is None
            or not isinstance(audio_sha256, str)
            or not AUDIO_HASH.fullmatch(audio_sha256)
            or not isinstance(signed_turn, str)
            or not isinstance(authenticated_archive_ack, dict)
            or not callable(trusted_ack_validator)):
        return None
    wall = int(time.time() if now is None else now)
    if (not verify_grant(owner_grant_secret, owner_grant, session_id,
                         now=wall)
            or verify_external_attestation(
                turn_issuer_secret, signed_turn, session_id=session_id,
                item_id=item_id, transcript=transcript,
                audio_sha256=audio_sha256, now=wall, purpose="turn"
            ) != ("person:owner", "owner")):
        return None
    ack = authenticated_archive_ack
    stamp, offset, row_hash = (
        ack.get("stamp"), ack.get("offset"), ack.get("archive_sha256"))
    if (ack.get("source") != "trusted_s3_sd_worker_ack"
            or ack.get("session_id") != session_id
            or ack.get("item_id") != item_id
            or type(stamp) is not int or not 1 <= stamp <= MAX_OFFSET
            or type(offset) is not int or not 0 <= offset <= MAX_OFFSET
            or type(row_hash) is not str or not HEX_SHA256.fullmatch(row_hash)
            or abs(wall - stamp) > MAX_TIMESTAMP_DRIFT):
        return None
    try:
        if trusted_ack_validator(
                session_id=session_id, item_id=item_id, stamp=stamp,
                offset=offset, archive_sha256=row_hash) is not True:
            return None
    except Exception:
        return None
    # The index will independently open the finalized snapshot, read exactly
    # offset+row and require this hash AND transcript digest to match.
    body = "\t".join((
        VERSION, str(stamp), str(offset), session_id, item_id,
        _digest(transcript), audio_sha256, row_hash,
        hashlib.sha256(signed_turn.encode("utf-8")).hexdigest(), str(wall)
    )).encode("ascii")
    return body + b"\t" + _mac(receipt_secret, body).encode("ascii") + b"\n"

def read_verified_owner_receipts(snapshot_root, receipt_secret):
    """Map (timestamp, byte offset) to a verified exact archive-line digest.

    Absent key or bad/symlinked/corrupted/oversized input returns no owner
    records. Duplicate signed receipts for the same offset invalidate it.
    """
    if not isinstance(receipt_secret, bytes) or len(receipt_secret) < 32:
        return {}
    root = Path(snapshot_root)
    path = root / "kitty" / RECEIPT_NAME
    archive = root / "kitty" / "conversations.tsv"
    if (root.is_symlink() or (root / "kitty").is_symlink()
            or path.is_symlink() or archive.is_symlink()
            or not path.is_file() or not archive.is_file()):
        return {}
    try:
        size = path.stat().st_size
        if not 1 <= size <= MAX_RECEIPTS_BYTES:
            return {}
        accepted, repeated = {}, set()
        archive_size = archive.stat().st_size
        with archive.open("rb") as source, path.open("rb") as receipt_file:
            for i, line in enumerate(receipt_file):
                if i >= MAX_RECEIPTS:
                    return {}
                if len(line) > MAX_RECEIPT_LINE or not line.endswith(b"\n"):
                    continue
                cells = line[:-1].split(b"\t")
                if len(cells) != 11:
                    continue
                try:
                    (version, stamp_s, offset_s, sid, item, transcript_hash,
                     audio_hash, row_hash, ticket_hash, issued_s, signature) = (
                        c.decode("ascii", "strict") for c in cells)
                except UnicodeDecodeError:
                    continue
                if (version != VERSION or not stamp_s.isdecimal()
                        or not offset_s.isdecimal() or not issued_s.isdecimal()
                        or not SESSION.fullmatch(sid) or not ITEM.fullmatch(item)
                        or not HEX_SHA256.fullmatch(transcript_hash)
                        or not HEX_SHA256.fullmatch(audio_hash)
                        or not HEX_SHA256.fullmatch(row_hash)
                        or not HEX_SHA256.fullmatch(ticket_hash)
                        or not MAC.fullmatch(signature)):
                    continue
                stamp, offset, issued = int(stamp_s), int(offset_s), int(issued_s)
                if (not 1 <= stamp <= MAX_OFFSET
                        or not 0 <= offset <= MAX_OFFSET
                        or not 1 <= issued
                        or abs(issued - stamp) > MAX_TIMESTAMP_DRIFT
                        or stamp_s != str(stamp) or offset_s != str(offset)
                        or issued_s != str(issued)):
                    continue
                body = b"\t".join(cells[:-1])
                if not hmac.compare_digest(signature, _mac(receipt_secret, body)):
                    continue
                key = (stamp, offset)
                if key in repeated:
                    continue
                if key in accepted:
                    del accepted[key]
                    repeated.add(key)
                    continue
                if offset >= archive_size:
                    continue
                source.seek(offset)
                raw = source.readline(MAX_ARCHIVED_LINE + 1)
                question = _archive_question(raw, stamp)
                if (question is None or _digest(question) != transcript_hash
                        or hashlib.sha256(raw).hexdigest() != row_hash):
                    continue
                accepted[key] = row_hash
        return accepted
    except (OSError, ValueError, OverflowError):
        return {}


def configured_receipt_secret():
    """Never auto-generate an archive signing key from device credentials."""
    encoded = os.environ.get("KITTY_OWNER_ARCHIVE_RECEIPT_SECRET_HEX", "")
    try:
        secret = bytes.fromhex(encoded) if encoded else b""
    except ValueError:
        return None
    return secret if len(secret) >= 32 else None
