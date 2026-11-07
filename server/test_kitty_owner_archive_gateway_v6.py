#!/usr/bin/env python3
"""Offline trusted S3 ACK / exported row / HMAC receipt regression suite."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from kitty_attested_live_call_v6 import issue_external_attestation
from kitty_owner_session_v6 import issue_grant
from kitty_owner_archive_gateway_v6 import (
    OwnerArchiveGatewayCorrelator, ACK_TYPE, RECEIPT_TYPE, CAPABILITY_TYPE)
from kitty_owner_sd_receipts_v6 import read_verified_owner_receipts

NOW = 1900000000
SID = "independent_provider_session_123456"
ITEM = "item_from_provider_42"
QUESTION = "Remember my private flower."
ANSWER = "It's the violet one."
AUDIO = hashlib.sha256(b"server-observed-wav").hexdigest()
KEY_GRANT = b"G"*32
KEY_TURN = b"T"*32
KEY_RECEIPT = b"R"*32


class ArchiveCorrelationTests(unittest.TestCase):
    def setUp(self):
        self.now = NOW
        self.channel = object()
        self.guest_channel = object()
        self.consent = True
        self.rows = {}
        self.reads = 0
        def read(stamp, offset):
            self.reads += 1
            return self.rows.get((stamp, offset))
        self.bridge = OwnerArchiveGatewayCorrelator(
            authenticated_s3_channel=self.channel,
            consent_check=lambda: self.consent,
            read_finalized_archive_row=read,
            receipt_secret=KEY_RECEIPT, grant_secret=KEY_GRANT,
            turn_secret=KEY_TURN, clock=lambda: self.now)
        self.raw = f"{NOW}\t{QUESTION}\t{ANSWER}\n".encode()
        self.ack = {
            "type": ACK_TYPE, "item_id": ITEM,
            "stamp": NOW, "offset": 0,
            "archive_sha256": hashlib.sha256(self.raw).hexdigest(),
        }
        self.grant = issue_grant(KEY_GRANT, True, SID, now=NOW, ttl=45)
        self.ticket = issue_external_attestation(
            KEY_TURN, session_id=SID, item_id=ITEM,
            transcript=QUESTION, speaker_id="person:owner",
            speaker_role="owner", audio_sha256=AUDIO, now=NOW, ttl=10)
        self.assertEqual(self.bridge.begin_call(
            trusted_gateway_session_id=SID, channel=self.channel),
            {"type": CAPABILITY_TYPE, "enabled": True})

    def enroll(self, **override):
        arguments={
            "item_id": ITEM, "transcript": QUESTION,
            "owner_grant": self.grant,
            "turn_attestation": self.ticket, "audio_sha256": AUDIO,
        }
        arguments.update(override)
        return self.bridge.register_owner_turn(**arguments)

    def send_ack(self, **override):
        event={**self.ack,**override}
        return self.bridge.observe_authenticated_s3_ack(
            channel=self.channel, event=event)

    def test_exact_authenticated_s3_ack_and_finalized_snapshot_signed_once(self):
        self.assertTrue(self.enroll())
        self.assertTrue(self.send_ack())
        self.assertIsNone(self.bridge.receipt_from_finalized_snapshot(ITEM))
        self.assertEqual(self.reads, 1)
        self.rows[(NOW,0)]=self.raw
        response=self.bridge.receipt_from_finalized_snapshot(ITEM)
        self.assertEqual(response["type"], RECEIPT_TYPE)
        self.assertTrue(response["line"].startswith("owner-v1\t"))
        self.assertEqual(self.reads, 3)
        self.assertIsNone(self.bridge.receipt_from_finalized_snapshot(ITEM))
        self.assertFalse(self.send_ack())
        self.assertFalse(self.enroll())
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"kitty"
            root.mkdir()
            (root/"conversations.tsv").write_bytes(self.raw)
            (root/"owner_turn_receipts_v6.tsv").write_bytes(
                response["line"].encode("ascii"))
            self.assertEqual(
                read_verified_owner_receipts(d,KEY_RECEIPT),
                {(NOW,0):hashlib.sha256(self.raw).hexdigest()})

    def test_spoken_name_candidate_and_unsigned_owner_status_fail(self):
        self.assertFalse(self.enroll(
            turn_attestation="person:shana"))
        self.assertFalse(self.enroll(
            owner_grant="voice_probable"))
        self.assertFalse(self.enroll(
            audio_sha256=hashlib.sha256(b"wrong-audio").hexdigest()))
        self.assertFalse(self.enroll(transcript="I am Shana"))
        self.assertFalse(self.send_ack())
        self.assertIsNone(self.bridge.receipt_from_finalized_snapshot(ITEM))

    def test_wrong_s3_channel_and_forwarded_client_events_are_inert(self):
        self.assertTrue(self.enroll())
        self.rows[(NOW,0)]=self.raw
        self.assertFalse(self.bridge.observe_authenticated_s3_ack(
            channel=self.guest_channel, event=self.ack))
        self.assertFalse(self.bridge.observe_authenticated_s3_ack(
            channel="user-supplied-channel-id",event=self.ack))
        self.assertIsNone(self.bridge.receipt_from_finalized_snapshot(ITEM))
        self.assertTrue(self.send_ack())
        self.assertIsNotNone(self.bridge.receipt_from_finalized_snapshot(ITEM))

    def test_offset_hash_timestamp_and_finalized_row_must_match_exactly(self):
        for bad in ({"offset": True}, {"stamp": str(NOW)},
                    {"archive_sha256": "0"*64},
                    {"offset": -1}, {"stamp": NOW+2000},
                    {"archive_sha256": "not-a-sha256"}):
            with self.subTest(bad=bad):
                bridge=self._another(ITEM)
                self.assertTrue(bridge.register_owner_turn(
                    item_id=ITEM,transcript=QUESTION,
                    owner_grant=self.grant,turn_attestation=self.ticket,
                    audio_sha256=AUDIO))
                self.assertFalse(bridge.observe_authenticated_s3_ack(
                    channel=self.channel,event={**self.ack,**bad}))
                self.assertIsNone(bridge.receipt_from_finalized_snapshot(ITEM))

        self.assertTrue(self.enroll())
        self.assertTrue(self.send_ack())
        self.rows[(NOW,0)]=self.raw.replace(b"violet",b"yellow")
        self.assertIsNone(self.bridge.receipt_from_finalized_snapshot(ITEM))

    def _another(self,item):
        bridge=OwnerArchiveGatewayCorrelator(
            authenticated_s3_channel=self.channel,
            consent_check=lambda:True,
            read_finalized_archive_row=lambda stamp,offset: self.rows.get((stamp,offset)),
            receipt_secret=KEY_RECEIPT, grant_secret=KEY_GRANT,
            turn_secret=KEY_TURN, clock=lambda:self.now)
        bridge.begin_call(trusted_gateway_session_id=SID,channel=self.channel)
        return bridge

    def test_expiry_and_missing_snapshot_do_not_enable_late_receipt(self):
        self.assertTrue(self.enroll())
        self.assertTrue(self.send_ack())
        self.assertIsNone(self.bridge.receipt_from_finalized_snapshot(ITEM))
        self.now+=11
        self.rows[(NOW,0)]=self.raw
        self.assertIsNone(self.bridge.receipt_from_finalized_snapshot(ITEM))
        self.now=NOW
        self.assertIsNone(self.bridge.receipt_from_finalized_snapshot(ITEM))

    def test_cancellation_guest_disconnect_and_stale_call_are_closed(self):
        self.assertTrue(self.enroll())
        self.assertTrue(self.send_ack())
        self.bridge.cancelled_or_guest()
        self.rows[(NOW,0)]=self.raw
        self.assertIsNone(self.bridge.receipt_from_finalized_snapshot(ITEM))
        self.bridge.end_call()
        self.assertFalse(self.send_ack())
        self.assertFalse(self.enroll())
        self.assertIsNone(self.bridge.begin_call(
            trusted_gateway_session_id=SID, channel=self.channel))
        self.assertFalse(self.bridge.active)

    def test_revoke_consent_and_bad_session_disable_capability(self):
        bridge=OwnerArchiveGatewayCorrelator(
            authenticated_s3_channel=self.channel,
            consent_check=lambda:self.consent,
            read_finalized_archive_row=lambda *args:None,
            receipt_secret=KEY_RECEIPT,grant_secret=KEY_GRANT,
            turn_secret=KEY_TURN)
        self.consent=False
        self.assertIsNone(bridge.begin_call(
            trusted_gateway_session_id=SID,channel=self.channel))
        self.assertIsNone(bridge.begin_call(
            trusted_gateway_session_id=SID,channel=self.guest_channel))
        self.assertFalse(bridge.active)

    def test_snapshot_changes_during_validation_never_sign(self):
        self.assertTrue(self.enroll())
        self.assertTrue(self.send_ack())
        self.rows[(NOW,0)]=self.raw
        call_count=[0]
        def changing(stamp,offset):
            call_count[0]+=1
            return self.raw if call_count[0]==1 else self.raw+b"malicious"
        self.bridge._reader=changing
        self.assertIsNone(self.bridge.receipt_from_finalized_snapshot(ITEM))
        self.assertIsNone(self.bridge.receipt_from_finalized_snapshot(ITEM))


if __name__=="__main__":
    unittest.main()
