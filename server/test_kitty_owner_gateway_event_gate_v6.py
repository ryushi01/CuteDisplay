#!/usr/bin/env python3
"""Offline authentic provider-item vs S3-device ACK isolation contract."""
import asyncio
import hashlib
import io
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from kitty_owner_gateway_event_gate_v6 import (
    ProviderTranscriptEvidence, OwnerGatewayEventGate, PROVIDER_COMPLETE)
from kitty_owner_archive_gateway_v6 import (
    OwnerArchiveGatewayCorrelator, ACK_TYPE, RECEIPT_TYPE)
from kitty_owner_receipt_async_bridge_v6 import AsyncOwnerReceiptBridge
from kitty_owner_voice_auth_issuer_v6 import VoiceOwnerIssuer
from kitty_owner_sd_receipts_v6 import read_verified_owner_receipts

NOW=1900000000
SID="trusted_gateway_session_xxyy112233"
G,T,R=b"G"*32,b"T"*32,b"R"*32


def wav_sample(seed):
    buffer=io.BytesIO()
    with wave.open(buffer,"wb") as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000)
        wav.writeframes(b"".join(
            struct.pack("<h",2400 if (i+seed)%(97+seed)<48 else -2400)
            for i in range(32000)))
    return buffer.getvalue()


class GatewayProvenanceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now=NOW
        self.provider=object()
        self.s3=object()
        self.profile={
            "voice_owner_auth_consent":True,
            "voice_owner_auth_min_score":0.975,
            "voice_owner_auth_min_margin":0.1,
            "owner_enrollment_id":"person:shana",
            "model_id":"pinned-owner-voice-v6-01",
            "memory_authorization":False,
            "anchor_embeddings":[[1],[2],[3]],
        }
        self.score={
            "source":"issuer_local_model",
            "model_id":"pinned-owner-voice-v6-01",
            "speaker_id":"person:shana",
            "candidate_only":False,
            "score":0.991,
            "runner_up_score":0.55,
        }
        self.records={}
        self.sent=[]
        self.store=ProviderTranscriptEvidence(provider_socket=self.provider)
        issuer=VoiceOwnerIssuer(
            profile_loader=lambda:self.profile,
            capture_lookup=lambda sid,item:self.records[item],
            score_audio=lambda wav:dict(self.score),
            grant_secret=G,turn_secret=T,clock=lambda:self.now)
        correlator=OwnerArchiveGatewayCorrelator(
            authenticated_s3_channel=self.s3,
            consent_check=lambda:self.profile["voice_owner_auth_consent"],
            read_finalized_archive_row=lambda *_:None,
            receipt_secret=R,grant_secret=G,turn_secret=T,
            clock=lambda:self.now)
        async def send(event):
            self.sent.append(dict(event))
        self.bridge=AsyncOwnerReceiptBridge(
            issuer=issuer,correlator=correlator,s3_channel=self.s3,
            provider_transcript=self.store.lookup,
            send_to_s3=send, socket_active=lambda:True,
            clock=lambda:self.now)
        self.assertEqual(self.bridge.begin_call(
            gateway_session_id=SID,channel=self.s3)["enabled"],True)
        self.gate=OwnerGatewayEventGate(
            bridge=self.bridge,provider_store=self.store,
            provider_socket=self.provider,s3_socket=self.s3)
        self.addAsyncCleanup(self.shutdown)

    async def shutdown(self):
        self.gate.close()
        await asyncio.sleep(0)

    def provider_event(self,n,words=None):
        item="provider-item-"+str(n)
        text=words or f"My private secret is flower {n}."
        self.records[item]={
            "source":"gateway_observed_s3_microphone",
            "authenticated_s3_session":True,
            "final_transcript":True,
            "overlap":False,"playback_active":False,
            "session_id":SID,"item_id":item,"transcript":text,
            "wav":wav_sample(n),"captured_at":self.now,
        }
        return {"type":PROVIDER_COMPLETE,"item_id":item,"transcript":text}

    async def warm(self):
        for n in (1,2):
            self.assertTrue(self.gate.from_provider(
                channel=self.provider,event=self.provider_event(n)))
        await self.bridge.drain()
        self.assertEqual(self.sent,[])

    def ack_for(self,event):
        row=f"{self.now}\t{event['transcript']}\t[voice transcript]\n".encode()
        ack={"type":ACK_TYPE,"item_id":event["item_id"],
             "stamp":self.now,"offset":0,
             "archive_sha256":hashlib.sha256(row).hexdigest()}
        return ack,row

    async def test_provider_only_transcript_plus_s3_only_ack_mints_receipt(self):
        await self.warm()
        turn=self.provider_event(3)
        self.assertTrue(self.gate.from_provider(
            channel=self.provider,event=turn))
        ack,row=self.ack_for(turn)
        self.assertTrue(self.gate.from_s3(channel=self.s3,event=ack))
        await self.bridge.drain()
        self.assertEqual(len(self.sent),1)
        self.assertEqual(self.sent[0]["type"],RECEIPT_TYPE)
        self.assertNotIn(turn["transcript"],self.sent[0]["line"])
        self.assertFalse(self.gate.owner_history_enabled)
        # Only a LATER immutable S3 microSD export is authoritative.
        self.now+=3600
        with tempfile.TemporaryDirectory() as d:
            kitty=Path(d)/"kitty";kitty.mkdir()
            kitty.joinpath("conversations.tsv").write_bytes(row)
            kitty.joinpath("owner_turn_receipts_v6.tsv").write_bytes(
                self.sent[0]["line"].encode("ascii"))
            self.assertEqual(read_verified_owner_receipts(d,R),
                {(NOW,0):hashlib.sha256(row).hexdigest()})
            kitty.joinpath("conversations.tsv").write_bytes(
                row.replace(b"flower",b"garden"))
            self.assertEqual(read_verified_owner_receipts(d,R),{})

    async def test_spoofed_s3_provider_transcript_never_promotes_owner(self):
        await self.warm()
        turn=self.provider_event(3)
        self.assertFalse(self.gate.from_provider(
            channel=self.s3,event=turn))
        self.assertIsNone(self.store.lookup(turn["item_id"]))
        self.assertFalse(self.gate.from_s3(channel=self.s3,event={
            "type":"kitty.speaker.result",
            "item_id":turn["item_id"],"speaker_id":"person:owner",
            "confidence":"verified","owner_grant":"forged"}))
        ack,_=self.ack_for(turn)
        self.assertFalse(self.gate.from_s3(channel=self.s3,event=ack))
        self.assertTrue(self.gate.from_provider(
            channel=self.provider,event=turn))
        await self.bridge.drain()
        self.assertFalse(self.gate.from_s3(channel=self.provider,event=ack))
        self.assertTrue(self.gate.from_s3(channel=self.s3,event=ack))
        await self.bridge.drain()
        self.assertEqual(len(self.sent),1)

    async def test_modified_provider_transcript_replayed_item_revokes(self):
        await self.warm()
        turn=self.provider_event(3)
        self.assertTrue(self.gate.from_provider(
            channel=self.provider,event=turn))
        self.assertEqual(self.store.lookup(turn["item_id"]),turn["transcript"])
        self.assertFalse(self.gate.from_provider(
            channel=self.provider,event={**turn,"transcript":"Modified"}))
        self.assertIsNone(self.store.lookup(turn["item_id"]))
        ack,_=self.ack_for(turn)
        self.assertFalse(self.gate.from_s3(channel=self.s3,event=ack))
        await self.bridge.drain()
        self.assertEqual(self.sent,[])

    async def test_guest_cancel_clears_pending_and_rechecks_three_turns(self):
        await self.warm()
        third=self.provider_event(3)
        self.assertTrue(self.gate.from_provider(channel=self.provider,event=third))
        await self.bridge.drain()
        self.assertFalse(self.gate.from_s3(channel=self.s3,event={
            "type":"response.cancel"}))
        self.assertIsNone(self.store.lookup(third["item_id"]))
        self.assertFalse(self.gate.from_s3(
            channel=self.s3,event=self.ack_for(third)[0]))
        for n in (4,5):
            turn=self.provider_event(n)
            self.assertTrue(self.gate.from_provider(
                channel=self.provider,event=turn))
        await self.bridge.drain()
        self.assertEqual(self.sent,[])
        turn=self.provider_event(6)
        self.assertTrue(self.gate.from_provider(channel=self.provider,event=turn))
        await self.bridge.drain()
        self.assertTrue(self.gate.from_s3(
            channel=self.s3,event=self.ack_for(turn)[0]))
        await self.bridge.drain()
        self.assertEqual(len(self.sent),1)

    async def test_unverified_name_and_guest_match_denied(self):
        self.score["score"]=0.96
        for n in (1,2,3,4):
            turn=self.provider_event(n,"I am Shana")
            self.assertTrue(self.gate.from_provider(
                channel=self.provider,event=turn))
        await self.bridge.drain()
        # The authenticated ACK may be staged provisionally, but never
        # produces a signed owner receipt without verified microphone proof.
        self.assertTrue(self.gate.from_s3(
            channel=self.s3,event=self.ack_for(turn)[0]))
        await self.bridge.drain()
        self.assertEqual(self.sent,[])

    async def test_client_malformed_and_failure_event_only_invalidate(self):
        item=self.provider_event(1)
        bad={**item,"transcript":"A"*256}
        self.assertFalse(self.gate.from_provider(channel=self.provider,event=bad))
        self.assertFalse(self.gate.from_provider(
            channel=self.provider,event={**item,"transcript":"x\nhi"}))
        self.assertFalse(self.gate.from_provider(
            channel=object(),event=item))
        self.assertFalse(self.gate.from_provider(
            channel=self.provider,event={"type":"error"}))
        self.assertFalse(self.gate.from_s3(
            channel=self.s3,event={"type":"kitty.memory.semantic",
                                   "speaker_id":"person:owner",
                                   "owner_grant":"pretend"}))
        self.assertEqual(self.sent,[])

    async def test_invalid_provenance_configuration_and_close(self):
        with self.assertRaises(ValueError):
            OwnerGatewayEventGate(
                bridge=self.bridge,provider_store=self.store,
                provider_socket=self.provider,s3_socket=self.provider)
        with self.assertRaises(ValueError):
            ProviderTranscriptEvidence(provider_socket="device_id")
        self.gate.close()
        self.assertFalse(self.bridge.active)
        self.assertFalse(self.gate.from_provider(
            channel=self.provider,event=self.provider_event(1)))
        self.assertFalse(self.gate.from_s3(
            channel=self.s3,event={"type":ACK_TYPE}))


if __name__=="__main__":
    unittest.main()
