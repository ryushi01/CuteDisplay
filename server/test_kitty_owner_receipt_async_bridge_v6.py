#!/usr/bin/env python3
"""Offline integrated async voice owner -> S3 ACK -> delayed SD snapshot tests."""
import asyncio
import hashlib
import io
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch
import wave

from kitty_owner_receipt_async_bridge_v6 import AsyncOwnerReceiptBridge
from kitty_owner_archive_gateway_v6 import (
    OwnerArchiveGatewayCorrelator, ACK_TYPE, CAPABILITY_TYPE, RECEIPT_TYPE,
)
from kitty_owner_voice_auth_issuer_v6 import VoiceOwnerIssuer
from kitty_owner_sd_receipts_v6 import read_verified_owner_receipts

NOW = 1900000000
SID = "gateway_issuer_session_authenticated_1234"
G, T, R = b"G"*32, b"T"*32, b"R"*32
OWNER = "person:shana"


def make_wav(seed):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"".join(
            struct.pack("<h", 2500 if (i+seed) % (87+seed) < 43 else -2500)
            for i in range(32000)))
    return buffer.getvalue()


class AsyncOwnerArchiveBridgeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.time=NOW
        self.mono=100.0
        self.channel=object()
        self.live=True
        self.consent=True
        self.records={}
        self.words={}
        self.events=[]
        self.score={
            "source":"issuer_local_model",
            "model_id":"pinned-local-v6-voice-1",
            "speaker_id":OWNER,"candidate_only":False,
            "score":0.991,"runner_up_score":0.5,
        }
        self.profile={
            "voice_owner_auth_consent":True,
            "voice_owner_auth_min_score":0.980,
            "voice_owner_auth_min_margin":0.1,
            "owner_enrollment_id":OWNER,
            "model_id":"pinned-local-v6-voice-1",
            "memory_authorization":False,
            "anchor_embeddings":[[0],[1],[2]],
        }
        self.block_score=False
        self.score_started=threading.Event()
        self.score_release=threading.Event()
        def score(wav):
            if self.block_score and wav == self.records["item-3"]["wav"]:
                self.score_started.set()
                self.score_release.wait(timeout=2.0)
            return dict(self.score)
        self.issuer=VoiceOwnerIssuer(
            profile_loader=lambda:self.profile,
            capture_lookup=lambda sid,item:self.records[item],
            score_audio=score, grant_secret=G, turn_secret=T,
            clock=lambda:self.time)
        self.correlator=OwnerArchiveGatewayCorrelator(
            authenticated_s3_channel=self.channel,
            consent_check=lambda:self.consent,
            read_finalized_archive_row=lambda *args:None,
            receipt_secret=R,grant_secret=G,turn_secret=T,
            clock=lambda:self.time)
        async def send(event):
            self.events.append(dict(event))
        self.sender=send
        self.bridge=AsyncOwnerReceiptBridge(
            issuer=self.issuer,correlator=self.correlator,
            s3_channel=self.channel,
            provider_transcript=lambda item:self.words[item],
            send_to_s3=lambda event:self.sender(event),
            socket_active=lambda:self.live,
            clock=lambda:self.time,monotonic=lambda:self.mono)
        self.assertEqual(self.bridge.begin_call(
            gateway_session_id=SID,channel=self.channel),
            {"type":CAPABILITY_TYPE,"enabled":True})
        self.addAsyncCleanup(self.cleanup_bridge)

    async def cleanup_bridge(self):
        self.score_release.set()
        self.bridge.close()
        await asyncio.sleep(0)

    def add_turn(self,n,words=None,**changes):
        item=f"item-{n}"
        text=words or f"Please remember my private violet flower {n}."
        self.words[item]=text
        self.records[item]={
            "source":"gateway_observed_s3_microphone",
            "authenticated_s3_session":True,"final_transcript":True,
            "overlap":False,"playback_active":False,
            "session_id":SID,"item_id":item,"transcript":text,
            "wav":make_wav(n),"captured_at":self.time,
        }
        self.records[item].update(changes)
        self.assertTrue(self.bridge.on_provider_completed(item))
        return item

    def ack(self,item,words=None,answer="I remember the violet flower."):
        text=words if words is not None else self.words[item]
        row=f"{self.time}\t{text}\t{answer}\n".encode()
        event={
            "type":ACK_TYPE,"item_id":item,"stamp":self.time,
            "offset":0,"archive_sha256":hashlib.sha256(row).hexdigest(),
        }
        return event,row

    async def warm(self):
        self.add_turn(1)
        self.add_turn(2)
        await self.bridge.drain()
        self.assertEqual(self.events,[])

    async def test_archive_ack_first_while_voice_model_still_busy(self):
        await self.warm()
        self.block_score=True
        item=self.add_turn(3)
        self.assertTrue(await asyncio.to_thread(self.score_started.wait, 1.0))
        ack,row=self.ack(item)
        self.assertTrue(self.bridge.on_authenticated_s3_ack(
            channel=self.channel,event=ack))
        self.assertFalse(self.bridge.on_authenticated_s3_ack(
            channel=self.channel,event=ack))
        self.assertEqual(self.events,[])
        self.score_release.set()
        await self.bridge.drain()
        self.assertEqual(len(self.events),1)
        receipt=self.events[0]
        self.assertEqual(receipt["type"],RECEIPT_TYPE)
        self.assertNotIn(self.words[item],receipt["line"])
        self.assertIsNone(self.correlator.receipt_from_authenticated_ack(item))
        self.time+=3600
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"kitty"
            root.mkdir()
            (root/"owner_turn_receipts_v6.tsv").write_bytes(
                receipt["line"].encode("ascii"))
            (root/"conversations.tsv").write_bytes(row)
            self.assertEqual(
                read_verified_owner_receipts(d,R),
                {(NOW,0): hashlib.sha256(row).hexdigest()})

    async def test_owner_proof_first_ack_after_background_scoring(self):
        await self.warm()
        item=self.add_turn(3)
        await self.bridge.drain()
        self.assertEqual(self.events,[])
        ack,_=self.ack(item)
        self.assertTrue(self.bridge.on_authenticated_s3_ack(
            channel=self.channel,event=ack))
        await self.bridge.drain()
        self.assertEqual(len(self.events),1)
        self.assertFalse(self.bridge.on_authenticated_s3_ack(
            channel=self.channel,event=ack))

    async def test_provider_transcript_mismatch_never_authorizes_receipt(self):
        await self.warm()
        item=self.add_turn(3)
        self.words[item]="Different transcript from provider"
        ack,_=self.ack(item)
        self.assertTrue(self.bridge.on_authenticated_s3_ack(
            channel=self.channel,event=ack))
        await self.bridge.drain()
        self.assertEqual(self.events,[])

    async def test_guest_or_probable_name_cannot_mint_receipt(self):
        await self.warm()
        self.score["score"]=0.960
        item=self.add_turn(3,words="I am Shana")
        ack,_=self.ack(item)
        self.assertTrue(self.bridge.on_authenticated_s3_ack(
            channel=self.channel,event=ack))
        await self.bridge.drain()
        self.assertEqual(self.events,[])
        self.score["score"]=0.991
        self.score["speaker_id"]="person:guest"
        for n in (4,5,6):
            item=self.add_turn(n,words="I am Shana")
            await self.bridge.drain()
        self.assertEqual(self.events,[])

    async def test_device_socket_and_unknown_items_cannot_inject_ack(self):
        await self.warm()
        self.assertFalse(self.bridge.on_authenticated_s3_ack(
            channel=self.channel,event=self.ack("item-unknown",
                                                 "hello")[0]))
        item=self.add_turn(3)
        ack,_=self.ack(item)
        self.assertFalse(self.bridge.on_authenticated_s3_ack(
            channel=object(),event=ack))
        self.assertFalse(self.bridge.on_authenticated_s3_ack(
            channel="forged-device-id",event=ack))
        self.assertFalse(self.bridge.on_authenticated_s3_ack(
            channel=self.channel,event={**ack,"stamp":True}))
        await self.bridge.drain()
        self.assertEqual(self.events,[])
        self.assertTrue(self.bridge.on_authenticated_s3_ack(
            channel=self.channel,event=ack))
        await self.bridge.drain()
        self.assertEqual(len(self.events),1)

    async def test_cancel_guest_interrupts_pending_ack(self):
        await self.warm()
        self.block_score=True
        item=self.add_turn(3)
        self.assertTrue(await asyncio.to_thread(self.score_started.wait,1.0))
        ack,_=self.ack(item)
        self.assertTrue(self.bridge.on_authenticated_s3_ack(
            channel=self.channel,event=ack))
        self.bridge.interrupted()
        self.score_release.set()
        await self.bridge.drain()
        self.assertEqual(self.events,[])
        self.assertFalse(self.bridge.on_authenticated_s3_ack(
            channel=self.channel,event=ack))

    async def test_disconnection_and_revoke_prevent_sending(self):
        await self.warm()
        item=self.add_turn(3)
        await self.bridge.drain()
        self.live=False
        ack,_=self.ack(item)
        self.assertFalse(self.bridge.on_authenticated_s3_ack(
            channel=self.channel,event=ack))
        self.live=True
        self.consent=False
        self.assertFalse(self.bridge.on_authenticated_s3_ack(
            channel=self.channel,event=ack))
        await self.bridge.drain()
        self.assertEqual(self.events,[])
        self.consent=True
        self.assertFalse(self.bridge.on_authenticated_s3_ack(
            channel=self.channel,event=ack))

    async def test_cpu_timeout_closes_bridge_without_sending(self):
        await self.warm()
        self.block_score=True
        with patch("kitty_owner_receipt_async_bridge_v6.VOICE_TIMEOUT",0.02):
            item=self.add_turn(3)
            self.assertTrue(await asyncio.to_thread(self.score_started.wait,1.0))
            ack,_=self.ack(item)
            self.assertTrue(self.bridge.on_authenticated_s3_ack(
                channel=self.channel,event=ack))
            await self.bridge.drain()
        self.assertFalse(self.bridge.active)
        self.assertEqual(self.events,[])
        self.score_release.set()
        await asyncio.sleep(0.02)
        self.assertEqual(self.events,[])

    async def test_scoring_that_finishes_after_guest_interruption_stays_invalid(self):
        await self.warm()
        self.block_score=True
        item=self.add_turn(3)
        self.assertTrue(await asyncio.to_thread(self.score_started.wait,1.0))
        ack,_=self.ack(item)
        self.assertTrue(self.bridge.on_authenticated_s3_ack(
            channel=self.channel,event=ack))
        self.bridge.interrupted()
        self.block_score=False
        self.score_release.set()
        await self.bridge.drain()
        self.assertEqual(self.events,[])
        # Three NEW consecutive authenticated microphone turns are needed
        # after interruption, despite the old score returning high.
        self.add_turn(4)
        self.add_turn(5)
        await self.bridge.drain()
        for n in (4,5):
            late_ack,_=self.ack(f"item-{n}")
            self.assertTrue(self.bridge.on_authenticated_s3_ack(
                channel=self.channel,event=late_ack))
        await self.bridge.drain()
        self.assertEqual(self.events,[])
        item=self.add_turn(6)
        await self.bridge.drain()
        newest_ack,_=self.ack(item)
        self.assertTrue(self.bridge.on_authenticated_s3_ack(
            channel=self.channel,event=newest_ack))
        await self.bridge.drain()
        self.assertEqual(len(self.events),1)

    async def test_slow_send_is_time_bounded_and_does_not_retry(self):
        await self.warm()
        item=self.add_turn(3)
        await self.bridge.drain()
        async def hanging_send(event):
            await asyncio.sleep(1.0)
            self.events.append(event)
        self.sender=hanging_send
        ack,_=self.ack(item)
        with patch("kitty_owner_receipt_async_bridge_v6.SEND_TIMEOUT",0.02):
            self.assertTrue(self.bridge.on_authenticated_s3_ack(
                channel=self.channel,event=ack))
            await self.bridge.drain()
        self.assertEqual(self.events,[])
        self.assertFalse(self.bridge.on_authenticated_s3_ack(
            channel=self.channel,event=ack))
        self.assertTrue(self.bridge.active)


if __name__=="__main__":
    unittest.main()
