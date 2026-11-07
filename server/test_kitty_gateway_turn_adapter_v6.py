#!/usr/bin/env python3
"""Offline contract: gateway adapter never trusts user claims or probable voice."""
import asyncio
import unittest

from kitty_attested_live_call_v6 import (
    AttestedLiveCall, issue_external_attestation)
from kitty_gateway_turn_adapter_v6 import GatewayTurnAdapter
from kitty_owner_session_v6 import issue_grant

VOICE_KEY = b"independent-signer-test-key-32-bytes"
OWNER_KEY = b"enrolled-owner-test-key-32-bytes-xx"


class GatewayTurnAdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = 1900000000
        call=AttestedLiveCall(attestation_secret=VOICE_KEY,
            owner_grant_secret=OWNER_KEY, wall_clock=lambda: self.now)
        self.adapter=GatewayTurnAdapter(attested_call=call)

    def ticket(self, item, words, speaker="person:aki", role="guest"):
        return issue_external_attestation(
            VOICE_KEY,session_id=self.adapter.session_id,
            item_id=item,transcript=words,speaker_id=speaker,
            speaker_role=role,now=self.now)

    def complete_from_provider(self, item, words, *, explicit_vad=False):
        if explicit_vad:
            self.adapter.observe_upstream(
                {"type":"input_audio_buffer.speech_started"})
            self.adapter.observe_upstream(
                {"type":"input_audio_buffer.speech_stopped","item_id":item})
        return self.adapter.observe_upstream({
            "type":"conversation.item.input_audio_transcription.completed",
            "item_id":item,"transcript":words})

    async def test_no_vad_anchor_requires_independent_signature(self):
        item="provider_item_10"
        text="We decided Bluetooth stays on the C5."
        self.assertTrue(self.complete_from_provider(item,text))
        # An unauthenticated S3/client voice claim is ignored.
        self.adapter.observe_client({"type":"kitty.speaker.result",
            "item_id":item,"speaker_id":"person:owner",
            "confidence":"probable"})
        self.assertEqual(await self.adapter.context_for_item(item),"")
        self.assertFalse(self.adapter.verify_independent_turn(item,"person:aki"))
        self.assertEqual(await self.adapter.context_for_item(item),"")
        self.assertTrue(self.complete_from_provider("item11",text))
        self.assertTrue(self.adapter.verify_independent_turn("item11",
            self.ticket("item11",text)))
        self.assertIn("C5",await self.adapter.context_for_item("item11"))

    async def test_120_provider_items_retain_early_explicit_decision(self):
        early="I decided to preserve the S3 SD archive."
        self.assertTrue(self.complete_from_provider("item0",early))
        self.assertTrue(self.adapter.verify_independent_turn(
            "item0",self.ticket("item0",early)))
        for i in range(1,121):
            item="item"+str(i)
            text="Tell me another short story."
            self.assertTrue(self.complete_from_provider(item,text))
            self.assertTrue(self.adapter.verify_independent_turn(
                item,self.ticket(item,text)))
        self.assertIn("S3 SD archive",await self.adapter.context_for_item("item120"))
        self.assertFalse(self.complete_from_provider("item0","Duplicate turn"))
        self.assertEqual(await self.adapter.context_for_item("item120"),"")

    async def test_explicit_vad_item_mismatch_fails_closed(self):
        self.assertTrue(self.complete_from_provider(
            "item1","Please remember my garden.",explicit_vad=True))
        self.assertTrue(self.adapter.verify_independent_turn(
            "item1",self.ticket("item1","Please remember my garden.")))
        self.adapter.observe_upstream({"type":"input_audio_buffer.speech_stopped",
                                       "item_id":"item2"})
        self.assertFalse(self.complete_from_provider(
            "item3","What about my garden?"))
        self.assertEqual(await self.adapter.context_for_item("item1"),"")

    async def test_stop_without_item_disallows_transcript_fallback(self):
        self.adapter.observe_upstream({"type":"input_audio_buffer.speech_started"})
        self.adapter.observe_upstream({"type":"input_audio_buffer.speech_stopped"})
        self.assertFalse(self.complete_from_provider("item4","my secret"))
        self.assertEqual(await self.adapter.context_for_item("item4"),"")

    async def test_owner_cannot_use_client_identity_or_grant_alone(self):
        text="My future project is a robot."
        grant=issue_grant(OWNER_KEY,True,self.adapter.session_id,
                          now=self.now,ttl=120)
        self.assertTrue(self.complete_from_provider("item1",text))
        self.adapter.observe_client({"type":"kitty.memory.semantic",
            "owner_grant":grant,"speaker_id":"person:owner"})
        self.assertFalse(self.adapter.verify_independent_turn("item1",grant,
            owner_grant=grant))
        self.assertTrue(self.complete_from_provider("item2",text))
        ticket=self.ticket("item2",text,speaker="person:owner",role="owner")
        self.assertTrue(self.adapter.verify_independent_turn(
            "item2",ticket,owner_grant=grant))
        self.assertIn("robot",await self.adapter.context_for_item("item2"))
        self.adapter.observe_client({"type":"response.cancel"})
        self.assertEqual(await self.adapter.context_for_item("item2"),"")

    async def test_cancel_barge_in_error_and_close_revoke(self):
        for item, event in (
            ("item1",{"type":"response.cancel"}),
            ("item2",{"type":"input_audio_buffer.clear"}),
            ("item3",{"type":"conversation.item.delete"})):
            self.assertTrue(self.complete_from_provider(item,"Remember C5."))
            self.assertTrue(self.adapter.verify_independent_turn(
                item,self.ticket(item,"Remember C5.")))
            self.adapter.observe_client(event)
            self.assertEqual(await self.adapter.context_for_item(item),"")
        self.assertTrue(self.complete_from_provider("item4","Remember the USB pinout."))
        self.adapter.observe_upstream({"type":"error"})
        self.assertEqual(await self.adapter.context_for_item("item4"),"")
        self.adapter.close()
        self.assertFalse(self.complete_from_provider("item5","Last turn."))
        self.assertEqual(await self.adapter.context_for_item("item5"),"")

    async def test_audio_bound_owner_ticket_is_forwarded_and_rechecked(self):
        audio_hash="a"*64
        grant=issue_grant(OWNER_KEY,True,self.adapter.session_id,
                          now=self.now,ttl=120)
        words="Please recall my personal notes."
        self.assertTrue(self.complete_from_provider("mic1",words))
        ticket=issue_external_attestation(
            VOICE_KEY,session_id=self.adapter.session_id,
            item_id="mic1",transcript=words,
            speaker_id="person:owner",speaker_role="owner",
            audio_sha256=audio_hash,now=self.now)
        self.assertFalse(self.adapter.verify_independent_turn(
            "mic1",ticket,owner_grant=grant,audio_sha256="b"*64))
        self.assertEqual(await self.adapter.context_for_item("mic1"),"")
        self.assertTrue(self.complete_from_provider("mic2",words))
        ticket=issue_external_attestation(
            VOICE_KEY,session_id=self.adapter.session_id,
            item_id="mic2",transcript=words,
            speaker_id="person:owner",speaker_role="owner",
            audio_sha256=audio_hash,now=self.now)
        self.assertTrue(self.adapter.verify_independent_turn(
            "mic2",ticket,owner_grant=grant,audio_sha256=audio_hash))
        self.assertIn("personal notes",await self.adapter.context_for_item("mic2"))

    async def test_no_external_issuer_is_safe_default(self):
        default=GatewayTurnAdapter()
        item="provider_1"
        self.assertFalse(default.observe_upstream({
            "type":"conversation.item.input_audio_transcription.completed",
            "item_id":item,"transcript":"My private plan."}))
        self.assertEqual(await default.context_for_item(item),"")
        self.assertFalse(default.verify_independent_turn(item,"pretend"))
        default.close()


if __name__=="__main__":
    unittest.main()
