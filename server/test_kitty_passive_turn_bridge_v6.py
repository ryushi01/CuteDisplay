#!/usr/bin/env python3
"""Passive gateway integration never elevates candidate voice, leaks or forwards."""
import asyncio
import unittest
from kitty_passive_turn_bridge_v6 import KittyPassiveTurnBridge
from kitty_attested_live_call_v6 import issue_external_attestation
from kitty_owner_session_v6 import issue_grant

ISSUER=b"independent-turn-issuer-test-secret-32bytes"
OWNER=b"independent-owner-grant-test-secret-32bytes"


class PassiveTurnBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_can_observe_but_never_recall_or_authorize(self):
        bridge=KittyPassiveTurnBridge(enable_familiarity=True)
        self.assertFalse(bridge.from_provider({
            "type":"conversation.item.input_audio_transcription.completed",
            "item_id":"t1","transcript":"We decided to leave BLE on C5."}))
        bridge.from_client({"type":"kitty.speaker.result",
                            "item_id":"t1","speaker_id":"person:owner",
                            "confidence":"certain"})
        self.assertFalse(bridge.independently_verified("t1","voice_probable"))
        self.assertEqual(await bridge.context_for_verified_item("t1"),"")
        self.assertIsNone(bridge.candidate_from_trusted_cpu(
            provider_item_id="t1",speaker_candidate="person:owner",
            score=1.0))
        bridge.close()
        self.assertEqual(await bridge.context_for_verified_item("t1"),"")

    async def test_signed_exact_provider_turn_preserves_early_decision(self):
        now=1900000000
        import kitty_attested_live_call_v6 as module
        original=module.time.time
        module.time.time=lambda:now
        try:
            bridge=KittyPassiveTurnBridge(issuer_secret=ISSUER,
                                          owner_grant_secret=OWNER)
            def signed(item,transcript):
                ticket=issue_external_attestation(
                    ISSUER,session_id=bridge.session_id,item_id=item,
                    transcript=transcript,speaker_id="person:aki",
                    speaker_role="guest",now=now)
                self.assertTrue(bridge.from_provider({
                    "type":"conversation.item.input_audio_transcription.completed",
                    "item_id":item,"transcript":transcript}))
                self.assertTrue(bridge.independently_verified(item,ticket))
            signed("t0","We decided to preserve the microSD authority.")
            for i in range(1,121):
                signed("t"+str(i),"Please tell me a story.")
            context=await bridge.context_for_verified_item("t120")
            self.assertIn("microSD authority",context)
            self.assertEqual(await bridge.context_for_verified_item("t0"),"")
            bridge.close()
        finally:
            module.time.time=original

    async def test_cancel_and_new_speaker_dismiss_queued_context(self):
        bridge=KittyPassiveTurnBridge(issuer_secret=ISSUER,
                                      owner_grant_secret=OWNER)
        # A client speaker claim is never the independent issuer.
        bridge.from_client({"type":"kitty.speaker.result",
                            "speaker_id":"person:owner","item_id":"i1"})
        self.assertEqual(await bridge.context_for_verified_item("i1"),"")
        bridge.from_provider({"type":"conversation.item.input_audio_transcription.completed",
                              "item_id":"i1","transcript":"My private plan."})
        bridge.from_client({"type":"response.cancel"})
        self.assertEqual(await bridge.context_for_verified_item("i1"),"")
        bridge.close()

    async def test_repeated_probable_voice_is_never_owner_history_authorization(self):
        bridge=KittyPassiveTurnBridge(enable_familiarity=True)
        for i in range(1,5):
            hint=bridge.candidate_from_trusted_cpu(
                provider_item_id="voice"+str(i),
                speaker_candidate="person:shana",score=0.973)
            self.assertIsNotNone(hint)
            self.assertFalse(hint["owner_authenticated"])
            self.assertFalse(hint["private_memory_authorized"])
            self.assertFalse(hint["profile_learning_authorized"])
            self.assertEqual(await bridge.context_for_verified_item(
                "voice"+str(i),include_owner_history=True),"")
        bridge.close()

    async def test_late_messages_and_disconnection_fail_closed(self):
        bridge=KittyPassiveTurnBridge()
        bridge.from_provider({"type":"error"})
        bridge.from_client({"type":"input_audio_buffer.clear"})
        bridge.close()
        self.assertFalse(bridge.from_provider({
            "type":"conversation.item.input_audio_transcription.completed",
            "item_id":"i2","transcript":"Ignore old context."}))
        self.assertFalse(bridge.independently_verified("i2","fake"))
        self.assertEqual(await bridge.context_for_verified_item("i2"),"")


if __name__=="__main__":
    unittest.main()
