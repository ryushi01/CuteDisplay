#!/usr/bin/env python3
"""Offline owner proof -> S3 archive ACK -> delayed snapshot verification."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from kitty_attested_live_call_v6 import issue_external_attestation
from kitty_owner_session_v6 import issue_grant
from kitty_owner_sd_receipts_v6 import (
    issue_provisional_owner_receipt, read_verified_owner_receipts,
)
from kitty_owner_archive_gateway_v6 import (
    OwnerArchiveGatewayCorrelator, ACK_TYPE, RECEIPT_TYPE,
)

NOW = 1900000000
SID = "trusted_gateway_session_123456789"
ITEM = "provider_item_007"
WORDS = "Remember my secret blue umbrella."
AUDIO = hashlib.sha256(b"trusted-S3-microphone-sample").hexdigest()
G, T, R = b"G"*32, b"T"*32, b"R"*32
ROW = f"{NOW}\t{WORDS}\tIt's on the shelf.\n".encode()
ROW_HASH = hashlib.sha256(ROW).hexdigest()


class ImmediateReceiptTests(unittest.TestCase):
    def setUp(self):
        self.time = NOW
        self.sock = object()
        self.consent = True
        self.rows = {}
        self.reads = 0
        def read(stamp,offset):
            self.reads += 1
            return self.rows.get((stamp,offset))
        self.c = OwnerArchiveGatewayCorrelator(
            authenticated_s3_channel=self.sock,
            consent_check=lambda:self.consent,
            read_finalized_archive_row=read,
            receipt_secret=R, grant_secret=G, turn_secret=T,
            clock=lambda:self.time)
        self.assertEqual(self.c.begin_call(
            trusted_gateway_session_id=SID, channel=self.sock)["enabled"],True)
        self.grant = issue_grant(G,True,SID,now=NOW,ttl=60)
        self.ticket = issue_external_attestation(
            T, session_id=SID, item_id=ITEM, transcript=WORDS,
            speaker_id="person:owner", speaker_role="owner",
            audio_sha256=AUDIO, now=NOW, ttl=10)
        self.ack = {
            "type": ACK_TYPE,"item_id":ITEM,"stamp":NOW,
            "offset":0,"archive_sha256":ROW_HASH,
        }

    def register(self,**kw):
        data=dict(item_id=ITEM, transcript=WORDS, owner_grant=self.grant,
                  turn_attestation=self.ticket, audio_sha256=AUDIO)
        data.update(kw)
        return self.c.register_owner_turn(**data)

    def acknowledge(self,**kw):
        return self.c.observe_authenticated_s3_ack(
            channel=self.sock, event={**self.ack,**kw})

    def test_receipt_before_snapshot_and_later_exact_microSD_verification(self):
        self.assertTrue(self.register())
        self.assertTrue(self.acknowledge())
        receipt = self.c.receipt_from_authenticated_ack(ITEM)
        self.assertEqual(receipt["type"],RECEIPT_TYPE)
        self.assertEqual(self.reads,0)  # No snapshot access on call path
        self.assertIsNone(self.c.receipt_from_authenticated_ack(ITEM))
        self.assertIsNone(self.c.receipt_from_finalized_snapshot(ITEM))
        self.assertNotIn(WORDS,receipt["line"])
        self.assertNotIn(self.grant,receipt["line"])
        self.assertNotIn(self.ticket,receipt["line"])
        # Much later, after ticket/grant expiry, *read-only* S3 snapshot
        # becomes available. Only exact SD archive bytes unlock owner index.
        self.time += 3600
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/"kitty"
            root.mkdir()
            (root/"owner_turn_receipts_v6.tsv").write_bytes(
                receipt["line"].encode("ascii"))
            archive=root/"conversations.tsv"
            archive.write_bytes(ROW)
            self.assertEqual(read_verified_owner_receipts(folder,R),
                             {(NOW,0): ROW_HASH})
            archive.write_bytes(ROW.replace(b"blue",b"red"))
            self.assertEqual(read_verified_owner_receipts(folder,R),{})
            archive.write_bytes(ROW)
            self.assertEqual(read_verified_owner_receipts(folder,R),
                             {(NOW,0): ROW_HASH})
            # Wrong transcript, even with an alternative row containing
            # the original bytes elsewhere, can never gain owner status.
            archive.write_bytes(b"unrelated archive row\n"+ROW)
            self.assertEqual(read_verified_owner_receipts(folder,R),{})

    def test_fake_ack_digest_is_not_owner_evidence(self):
        self.assertTrue(self.register())
        self.assertTrue(self.acknowledge(archive_sha256="0"*64))
        receipt=self.c.receipt_from_authenticated_ack(ITEM)
        self.assertIsNotNone(receipt)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/"kitty"
            root.mkdir()
            (root/"conversations.tsv").write_bytes(ROW)
            (root/"owner_turn_receipts_v6.tsv").write_bytes(
                receipt["line"].encode("ascii"))
            self.assertEqual(read_verified_owner_receipts(folder,R),{})
        # A signed S3 claim is NOT proof the actual archive matches.

    def test_wrong_socket_and_unauthenticated_event_never_sign(self):
        self.assertTrue(self.register())
        self.assertFalse(self.c.observe_authenticated_s3_ack(
            channel=object(),event=self.ack))
        self.assertIsNone(self.c.receipt_from_authenticated_ack(ITEM))
        self.assertTrue(self.acknowledge())
        self.c.cancelled_or_guest()
        self.assertIsNone(self.c.receipt_from_authenticated_ack(ITEM))

    def test_stale_or_forged_proofs_declined(self):
        self.assertFalse(self.register(turn_attestation="person:shana"))
        self.assertFalse(self.register(audio_sha256="0"*64))
        self.assertFalse(self.register(transcript="My name is Shana"))
        self.assertTrue(self.register())
        self.assertTrue(self.acknowledge())
        self.time += 11
        self.assertIsNone(self.c.receipt_from_authenticated_ack(ITEM))
        self.assertIsNone(self.c.receipt_from_finalized_snapshot(ITEM))

    def test_immediate_signing_exactly_once_and_revocation(self):
        self.assertTrue(self.register())
        self.assertTrue(self.acknowledge())
        self.assertFalse(self.acknowledge())
        self.consent=False
        self.assertIsNone(self.c.receipt_from_authenticated_ack(ITEM))
        self.consent=True
        self.assertIsNone(self.c.receipt_from_authenticated_ack(ITEM))
        self.assertFalse(self.register())

    def test_receipt_signer_does_not_trust_ack_json_alone(self):
        kwargs=dict(
            session_id=SID,item_id=ITEM,transcript=WORDS,audio_sha256=AUDIO,
            owner_grant=self.grant,signed_turn=self.ticket,
            authenticated_archive_ack={
                "source":"trusted_s3_sd_worker_ack",
                "session_id":SID,"item_id":ITEM,"stamp":NOW,
                "offset":0,"archive_sha256":ROW_HASH,
            },now=NOW,
        )
        self.assertIsNone(issue_provisional_owner_receipt(
            R,G,T,**kwargs,trusted_ack_validator=None))
        self.assertIsNone(issue_provisional_owner_receipt(
            R,G,T,**kwargs,trusted_ack_validator=lambda **_:False))
        self.assertIsNone(issue_provisional_owner_receipt(
            R,G,T,**{**kwargs,"authenticated_archive_ack":{
                **kwargs["authenticated_archive_ack"],"source":"client-json"}},
            trusted_ack_validator=lambda **_:True))
        self.assertIsNone(issue_provisional_owner_receipt(
            R,G,T,**{**kwargs,"authenticated_archive_ack":{
                **kwargs["authenticated_archive_ack"],"offset":True}},
            trusted_ack_validator=lambda **_:True))
        self.assertIsNone(issue_provisional_owner_receipt(
            R,G,T,**{**kwargs,"signed_turn":"untrusted"},
            trusted_ack_validator=lambda **_:True))
        self.assertIsNone(issue_provisional_owner_receipt(
            R,G,T,**{**kwargs,"audio_sha256":"f"*64},
            trusted_ack_validator=lambda **_:True))
        self.assertIsNone(issue_provisional_owner_receipt(
            R,G,T,**{**kwargs,"session_id":"another_session_123456789"},
            trusted_ack_validator=lambda **_:True))

    def test_cannot_sign_after_disconnect_or_reconnect(self):
        self.assertTrue(self.register())
        self.assertTrue(self.acknowledge())
        self.c.end_call()
        self.assertIsNone(self.c.receipt_from_authenticated_ack(ITEM))
        self.assertIsNone(self.c.begin_call(
            trusted_gateway_session_id=SID,channel=self.sock))


if __name__=="__main__":
    unittest.main()
