#!/usr/bin/env python3
"""Offline S3 SD receipt -> owner-index roundtrip; no real device or keys."""
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from kitty_attested_live_call_v6 import issue_external_attestation
from kitty_owner_session_v6 import issue_grant
from kitty_owner_sd_receipts_v6 import (
    issue_owner_receipt, read_verified_owner_receipts, configured_receipt_secret
)
from kitty_semantic_attribution_v6 import iter_archive_with_speakers
from kitty_memory_context_v6 import recall_context
from kitty_sd_semantic_index import build, search


ISSUER = b"I"*32
OWNER = b"O"*32
RECEIPT = b"R"*32
NOW = 1900000000
SID = "gateway_session_owner_1234567"
ITEM = "provider_item_owner_7"
TRANSCRIPT = "My hidden color is purple."
AUDIO_HASH = hashlib.sha256(b"synthetic-captured-mic").hexdigest()


class FakeModel:
    def encode(self, texts, **kwargs):
        import numpy as np
        return np.ones((len(texts), 4), dtype="float32")


class OwnerReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.sd = Path(self.temp.name) / "snapshot-test"
        self.kitty = self.sd / "kitty"
        self.kitty.mkdir(parents=True)
        self.path = self.kitty / "conversations.tsv"
        self.raw = f"{NOW}\t{TRANSCRIPT}\t[voice transcript]\n".encode()
        self.path.write_bytes(self.raw)
        self.receipt_file = self.kitty / "owner_turn_receipts_v6.tsv"
        self.db = str(Path(self.temp.name) / "derived.sqlite3")
        self.grant = issue_grant(OWNER, True, SID, now=NOW, ttl=120)
        self.ticket = issue_external_attestation(
            ISSUER, session_id=SID, item_id=ITEM, transcript=TRANSCRIPT,
            speaker_id="person:owner", speaker_role="owner",
            audio_sha256=AUDIO_HASH, now=NOW, ttl=10)
        self.ack = {
            "source": "trusted_s3_sd_worker_ack", "session_id": SID,
            "item_id": ITEM, "stamp": NOW, "offset": 0, "raw_line": self.raw,
        }
        self.validated = []

    def trusted_ack(self, **kwargs):
        self.validated.append(kwargs)
        return kwargs == {
            "session_id": SID, "item_id": ITEM, "stamp": NOW,
            "offset": 0, "raw_line": self.raw,
        }

    def mint(self, **overrides):
        args = {
            "session_id": SID, "item_id": ITEM, "transcript": TRANSCRIPT,
            "audio_sha256": AUDIO_HASH, "owner_grant": self.grant,
            "signed_turn": self.ticket, "archive_ack": self.ack,
            "trusted_ack_validator": self.trusted_ack, "now": NOW,
        }
        args.update(overrides)
        return issue_owner_receipt(RECEIPT, OWNER, ISSUER, **args)

    def test_authorized_exact_audio_and_trusted_s3_ack_are_both_required(self):
        row = self.mint()
        self.assertIsInstance(row, bytes)
        self.assertNotIn(TRANSCRIPT.encode(), row)
        self.assertNotIn(self.grant.encode(), row)
        self.assertNotIn(self.ticket.encode(), row)
        self.assertEqual(len(self.validated), 1)
        self.receipt_file.write_bytes(row)
        self.assertEqual(read_verified_owner_receipts(self.sd, RECEIPT),
                         {(NOW, 0): hashlib.sha256(self.raw).hexdigest()})
        attributed = list(iter_archive_with_speakers(
            self.sd, owner_receipt_secret=RECEIPT))
        self.assertEqual(attributed[0]["speaker_id"], "person:owner")
        self.assertEqual(attributed[0]["speaker_role"], "owner")
        self.assertEqual(attributed[0]["provenance"], "session_verified")
        # The same SD snapshot must *never* gain owner identity by a claim.
        self.assertEqual(
            list(iter_archive_with_speakers(self.sd))[0]["speaker_id"],
            "unknown")

    def test_derived_index_only_recalls_owner_with_valid_receipt_key(self):
        self.receipt_file.write_bytes(self.mint())
        self.kitty.joinpath("speaker_claims_v6.tsv").write_text(
            f"{NOW}\tperson:owner\tcolor\tpurple\tvoice_probable\n")
        with patch("kitty_sd_semantic_index.get_model", return_value=FakeModel()):
            build(self.sd, self.db, owner_receipt_secret=b"wrong-key"*4)
            self.assertEqual(
                search(self.db, "hidden color", speaker_id="person:owner"), [])
            build(self.sd, self.db, owner_receipt_secret=RECEIPT)
            found = search(self.db, "hidden color", speaker_id="person:owner")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["speaker_role"], "owner")
        self.assertEqual(found[0]["provenance"], "session_verified")
        self.assertIn("purple", recall_context(
            self.db, "hidden color", "person:owner",
            search_fn=lambda *a, **k: found))

    def test_modified_row_and_duplicate_signed_receipt_are_denied(self):
        good = self.mint()
        self.receipt_file.write_bytes(good)
        self.path.write_bytes(self.raw.replace(b"purple", b"orange"))
        self.assertEqual(read_verified_owner_receipts(self.sd, RECEIPT), {})
        self.path.write_bytes(self.raw)
        self.receipt_file.write_bytes(good + good)
        self.assertEqual(read_verified_owner_receipts(self.sd, RECEIPT), {})
        self.receipt_file.write_bytes(good[:-3] + b"bad\n")
        self.assertEqual(read_verified_owner_receipts(self.sd, RECEIPT), {})

    def test_reject_unsigned_or_guest_learning_and_mismatched_audio(self):
        cases = [
            {"signed_turn": "person:owner"},
            {"owner_grant": "bad-grant"},
            {"session_id": "different_session_123456789"},
            {"item_id": "other_item"},
            {"transcript": "My hidden color is orange."},
            {"audio_sha256": hashlib.sha256(b"other mic").hexdigest()},
            {"archive_ack": {**self.ack, "source": "unverified_voice_candidate"}},
            {"archive_ack": {**self.ack, "item_id": "other_item"}},
            {"archive_ack": {**self.ack, "raw_line": self.raw+b"extra"}},
            {"trusted_ack_validator": lambda **kwargs: False},
            {"trusted_ack_validator": None},
            {"now": NOW + 800},
        ]
        for change in cases:
            with self.subTest(change=change):
                self.assertIsNone(self.mint(**change))
        guest = issue_external_attestation(
            ISSUER, session_id=SID, item_id=ITEM, transcript=TRANSCRIPT,
            speaker_id="person:guest", speaker_role="guest",
            audio_sha256=AUDIO_HASH, now=NOW)
        self.assertIsNone(self.mint(signed_turn=guest))
        learning = issue_external_attestation(
            ISSUER, session_id=SID, item_id=ITEM, transcript=TRANSCRIPT,
            speaker_id="person:owner", speaker_role="owner",
            audio_sha256=AUDIO_HASH, now=NOW, purpose="learning")
        self.assertIsNone(self.mint(signed_turn=learning))
        self.assertIsNone(issue_owner_receipt(
            RECEIPT, OWNER, OWNER, session_id=SID, item_id=ITEM,
            transcript=TRANSCRIPT, audio_sha256=AUDIO_HASH,
            owner_grant=self.grant, signed_turn=self.ticket,
            archive_ack=self.ack, trusted_ack_validator=self.trusted_ack,
            now=NOW))

    def test_missing_key_symlink_and_unverified_sd_cannot_promote_owner(self):
        self.receipt_file.write_bytes(self.mint())
        self.assertEqual(read_verified_owner_receipts(self.sd, None), {})
        self.assertEqual(read_verified_owner_receipts(self.sd, b"invalid"), {})
        with patch.dict(os.environ, {"KITTY_OWNER_ARCHIVE_RECEIPT_SECRET_HEX": ""}):
            self.assertIsNone(configured_receipt_secret())
        with patch.dict(os.environ, {
                "KITTY_OWNER_ARCHIVE_RECEIPT_SECRET_HEX": RECEIPT.hex()}):
            self.assertEqual(configured_receipt_secret(), RECEIPT)
        self.receipt_file.unlink()
        external = Path(self.temp.name) / "external.tsv"
        external.write_bytes(self.mint())
        self.receipt_file.symlink_to(external)
        self.assertEqual(read_verified_owner_receipts(self.sd, RECEIPT), {})
        self.assertEqual(list(iter_archive_with_speakers(
            self.sd, owner_receipt_secret=RECEIPT))[0]["speaker_id"],
            "unknown")

    def test_wrong_sd_offset_replay_and_bad_canonical_row(self):
        self.receipt_file.write_bytes(self.mint())
        with self.path.open("ab") as f:
            f.write(self.raw)
        original = self.receipt_file.read_bytes()
        # Shifting the identical text to a new offset cannot reuse a receipt.
        self.path.write_bytes(b"something irrelevant\n" + self.raw)
        self.assertEqual(read_verified_owner_receipts(self.sd, RECEIPT), {})
        self.path.write_bytes(self.raw)
        self.assertEqual(len(read_verified_owner_receipts(self.sd, RECEIPT)), 1)
        self.receipt_file.write_bytes(original)
        self.assertIsNone(self.mint(archive_ack={
            **self.ack, "raw_line": self.raw.replace(b"\t", b"|", 1)}))


if __name__ == "__main__":
    unittest.main()
