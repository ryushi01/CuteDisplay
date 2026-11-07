#!/usr/bin/env python3
"""Source-only trusted S3 archive-ACK -> owner receipt correlation.

This is a *gateway-side internal adapter*, never a public HTTP / WebSocket
handler and never installed in the running gateway by importing it.
The session handle and the finalized-S3-export reader MUST originate from the
trusted gateway, never from JSON supplied by Kitty, a phone or a model.

S3's ACK proves neither owner identity nor final snapshot availability.
The original owner grant and audio-bound turn ticket must STILL be valid when
a finalized exported row becomes available. An expired proof is NOT renewed
from a candidate match; an unavailable snapshot causes a safe missed receipt.
"""
import hashlib
import math
import re
import time

from kitty_attested_live_call_v6 import ITEM, SESSION, AUDIO_HASH, _digest
from kitty_owner_sd_receipts_v6 import (
    _archive_question, issue_owner_receipt, MAX_OFFSET, MAX_TIMESTAMP_DRIFT,
)
from kitty_owner_session_v6 import verify_grant
from kitty_attested_live_call_v6 import verify_external_attestation

ACK_TYPE = "kitty.memory.owner_archive.ack"
RECEIPT_TYPE = "kitty.memory.owner_archive.receipt"
CAPABILITY_TYPE = "kitty.memory.owner_archive.capabilities"
MAX_PENDING = 8
MAX_ITEMS_PER_CALL = 256


class OwnerArchiveGatewayCorrelator:
    """Per-call volatile correlation. Never touches the realtime audio loop.

    authenticated_s3_channel: unforgeable gateway-local connection object. Its
    identity is checked with 'is', NOT a channel ID or request JSON.
    read_finalized_archive_row: trusted callback (stamp,offset)->bytes or None,
    which MUST read only an immutable, verified, finished S3 SD snapshot.
    Do not point it to an arbitrary client path, live mutable file, or a
    second Ubuntu-authoritative owner-memory database.
    """

    def __init__(self, *, authenticated_s3_channel, consent_check,
                 read_finalized_archive_row, receipt_secret, grant_secret,
                 turn_secret, clock=time.time):
        if (authenticated_s3_channel is None
                or not callable(consent_check)
                or not callable(read_finalized_archive_row)
                or not callable(clock)
                or any(not isinstance(v, bytes) or len(v) < 32
                       for v in (receipt_secret, grant_secret, turn_secret))
                or len({receipt_secret, grant_secret, turn_secret}) != 3):
            raise ValueError("trusted owner archive gateway configuration required")
        self._device = authenticated_s3_channel
        self._consent = consent_check
        self._reader = read_finalized_archive_row
        self._receipt_key = receipt_secret
        self._grant_key = grant_secret
        self._turn_key = turn_secret
        self._clock = clock
        self._session = None
        self._pending = {}
        self._used_items = set()
        self._used_offsets = set()

    @property
    def active(self):
        return self._session is not None

    def begin_call(self, *, trusted_gateway_session_id, channel):
        """Gateway-created session only. Return optional capability message.

        The adapter cannot authenticate a physical S3 connection; the caller
        must provide the exact server-held socket handle after device auth.
        This capability merely enables S3 ACKs, never owner access.
        """
        self.end_call()
        if (channel is not self._device
                or not isinstance(trusted_gateway_session_id, str)
                or not SESSION.fullmatch(trusted_gateway_session_id)):
            return None
        try:
            consent = self._consent()
        except (OSError, ValueError, TypeError, RuntimeError):
            return None
        if consent is not True:
            return None
        self._session = trusted_gateway_session_id
        return {"type": CAPABILITY_TYPE, "enabled": True}

    def end_call(self):
        self._session = None
        self._pending.clear()
        self._used_items.clear()
        self._used_offsets.clear()

    def cancelled_or_guest(self):
        """Barge-in, unknown speaker, provider error or cancel: no old proofs."""
        self._pending.clear()

    def register_owner_turn(self, *, item_id, transcript,
                            owner_grant, turn_attestation, audio_sha256):
        """Internal callback only: exact transcript from the provider socket.

        The callback must not be exposed to client events, self-claims,
        probable voice results or S3-sidecar source labels.
        """
        if (self._session is None or not isinstance(item_id, str)
                or not ITEM.fullmatch(item_id)
                or item_id in self._used_items
                or len(self._used_items) >= MAX_ITEMS_PER_CALL
                or len(self._pending) >= MAX_PENDING
                or not isinstance(transcript, str)
                or _digest(transcript) is None
                # The S3 sanitizes and truncates UTF-8 questions to 255 bytes.
                # Only EXACT unmodified questions are eligible.
                or not 1 <= len(transcript.encode("utf-8")) <= 255
                or any(c in transcript for c in ("\r", "\n", "\t", "\0"))
                or not isinstance(audio_sha256, str)
                or not AUDIO_HASH.fullmatch(audio_sha256)):
            return False
        now = int(self._clock())
        if not self._fresh_proof(item_id, transcript, owner_grant,
                                 turn_attestation, audio_sha256, now):
            return False
        self._used_items.add(item_id)
        self._pending[item_id] = {
            "transcript": transcript, "owner_grant": owner_grant,
            "ticket": turn_attestation, "audio": audio_sha256, "ack": None,
        }
        return True

    def _fresh_proof(self, item, text, grant, ticket, audio_hash, now):
        if not verify_grant(self._grant_key, grant, self._session, now=now):
            return False
        return verify_external_attestation(
            self._turn_key, ticket, session_id=self._session,
            item_id=item, transcript=text, audio_sha256=audio_hash,
            purpose="turn", now=now) == ("person:owner", "owner")

    def observe_authenticated_s3_ack(self, *, channel, event):
        """Only raw events from the authenticated *device receive loop*.

        This is NOT a client-facing handler; the channel object is never
        serialized into JSON or made available to an HTTP caller.
        """
        if (self._session is None or channel is not self._device
                or not isinstance(event, dict)
                or event.get("type") != ACK_TYPE):
            return False
        item = event.get("item_id")
        pending = self._pending.get(item) if isinstance(item, str) else None
        if pending is None or pending["ack"] is not None:
            return False
        # Malformed ACK burns this item: do not let an attacker retry until
        # one happens to match a signed owner proof.
        stamp, offset, hash_value = (
            event.get("stamp"), event.get("offset"),
            event.get("archive_sha256"))
        now = int(self._clock())
        if (type(stamp) is not int or type(offset) is not int
                or not 1 <= stamp <= MAX_OFFSET
                or not 0 <= offset <= MAX_OFFSET
                or not isinstance(hash_value, str)
                or not AUDIO_HASH.fullmatch(hash_value)
                or abs(now - stamp) > MAX_TIMESTAMP_DRIFT
                or (stamp, offset) in self._used_offsets
                or not self._fresh_proof(
                    item, pending["transcript"], pending["owner_grant"],
                    pending["ticket"], pending["audio"], now)):
            self._pending.pop(item, None)
            return False
        self._used_offsets.add((stamp, offset))
        pending["ack"] = (stamp, offset, hash_value)
        return True

    def receipt_from_finalized_snapshot(self, item_id):
        """Try to issue ONE signed row, only if original proof remains fresh.

        If the finalized snapshot is not yet available, return None and keep
        a bounded pending item while its original 10-second ticket is valid.
        Once expired, permanently drop the item; never reissue retroactively
        with a new proof or a stated name.
        """
        if self._session is None or not isinstance(item_id, str):
            return None
        pending = self._pending.get(item_id)
        if pending is None or pending["ack"] is None:
            return None
        now = int(self._clock())
        if not self._fresh_proof(
                item_id, pending["transcript"], pending["owner_grant"],
                pending["ticket"], pending["audio"], now):
            self._pending.pop(item_id, None)
            return None
        stamp, offset, digest = pending["ack"]
        try:
            raw = self._reader(stamp, offset)
        except (OSError, ValueError, TypeError, RuntimeError):
            return None
        if raw is None:
            return None
        if (not isinstance(raw, bytes) or not 5 <= len(raw) <= 1200
                or _archive_question(raw, stamp) != pending["transcript"]
                or hashlib.sha256(raw).hexdigest() != digest):
            self._pending.pop(item_id, None)
            return None
        # Validator independently repeats the trusted snapshot read to
        # reject changed/mixed-revision rows. A callback must supply only
        # snapshot-finalized immutable bytes, not S3/client JSON.
        def check_snapshot(*, session_id, item_id, stamp, offset, raw_line):
            if session_id != self._session or item_id not in self._pending:
                return False
            try:
                reread = self._reader(stamp, offset)
            except (OSError, ValueError, TypeError, RuntimeError):
                return False
            return isinstance(reread, bytes) and reread == raw_line
        line = issue_owner_receipt(
            self._receipt_key, self._grant_key, self._turn_key,
            session_id=self._session, item_id=item_id,
            transcript=pending["transcript"], audio_sha256=pending["audio"],
            owner_grant=pending["owner_grant"], signed_turn=pending["ticket"],
            archive_ack={
                "source": "trusted_s3_sd_worker_ack",
                "session_id": self._session, "item_id": item_id,
                "stamp": stamp, "offset": offset, "raw_line": raw,
            },
            trusted_ack_validator=check_snapshot, now=now)
        # One attempt per verified final row. No automatic retry after a
        # signing or snapshot error, to avoid duplicates on microSD.
        self._pending.pop(item_id, None)
        if line is None:
            return None
        return {"type": RECEIPT_TYPE, "line": line.decode("ascii")}
