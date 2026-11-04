#!/usr/bin/env python3
"""Offline no-audio no-network tests for independently signed Kitty live turns."""
import time
import unittest

from kitty_attested_live_call_v6 import (
    AttestedLiveCall, issue_external_attestation,
    verify_external_attestation,
)
from kitty_owner_session_v6 import issue_grant


ATTESTATION_KEY = b"speaker-issuer-signing-key-tests-32-bytes!"
OWNER_KEY = b"enrolled-owner-grant-key-tests-32-bytes!"


class AttestedLiveCallTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_900_000_000
        self.tick = 0.0
        self.call = AttestedLiveCall(attestation_secret=ATTESTATION_KEY,
                                     owner_grant_secret=OWNER_KEY,
                                     clock=lambda: self.tick,
                                     wall_clock=lambda: self.now)

    def ticket(self, item, transcript, speaker="person:aki", role="guest",
               session=None):
        return issue_external_attestation(
            ATTESTATION_KEY, session_id=session or self.call.session_id,
            item_id=item, transcript=transcript, speaker_id=speaker,
            speaker_role=role, now=self.now)

    def speak(self, item, words, speaker="person:aki", role="guest",
              grant=None):
        self.call.upstream_speech_started()
        self.assertTrue(self.call.upstream_speech_stopped(item))
        self.assertTrue(self.call.upstream_transcript_completed(item, words))
        return self.call.verify_turn(
            item, self.ticket(item, words, speaker, role),
            owner_grant=grant)

    def test_decision_survives_120_turns_no_network_or_model(self):
        first = "We decided to keep Bluetooth on C5 for Kitty."
        self.assertTrue(self.speak("item0", first))
        for i in range(1, 121):
            self.tick += 1
            self.now += 1
            self.assertTrue(self.speak("item"+str(i), "Tell me another story."))
        recall = self.call.context_for_verified_turn("item120")
        self.assertIn("Bluetooth on C5", recall)
        self.assertLessEqual(len(recall.encode("utf-8")), 1000)
        self.assertEqual(self.call.context_for_verified_turn("item0"), "")

    def test_unverified_or_forged_signatures_never_open_notes(self):
        self.assertTrue(self.speak("item0", "Remember my special plan."))
        self.call.upstream_speech_started()
        self.assertTrue(self.call.upstream_speech_stopped("item1"))
        self.assertTrue(self.call.upstream_transcript_completed("item1",
                          "Can you repeat my private plan?"))
        self.assertFalse(self.call.verify_turn("item1", "person:aki"))
        self.assertEqual(self.call.context_for_verified_turn("item1"), "")
        self.assertFalse(self.call.verify_turn("item1", self.ticket(
            "item1", "Can you repeat my private plan?")))
        self.assertEqual(self.call.context_for_verified_turn("item0"), "")

    def test_mismatched_session_item_and_transcript(self):
        transcript="Please remember my secret."
        self.call.upstream_speech_stopped("item1")
        self.call.upstream_transcript_completed("item1", transcript)
        wrong_session=issue_external_attestation(
            ATTESTATION_KEY, session_id="another-trusted-session-0001",
            item_id="item1", transcript=transcript, speaker_id="person:aki",
            speaker_role="guest", now=self.now)
        self.assertFalse(self.call.verify_turn("item1", wrong_session))
        self.assertEqual(self.call.context_for_verified_turn("item1"), "")
        self.call.upstream_speech_stopped("item2")
        self.call.upstream_transcript_completed("item2", transcript)
        self.assertFalse(self.call.verify_turn("item2",
            self.ticket("item3", transcript)))

    def test_attestation_is_exact_transcript_and_time_bound(self):
        signed = self.ticket("i1", "hello")
        self.assertIsNone(verify_external_attestation(
            ATTESTATION_KEY, signed, session_id=self.call.session_id,
            item_id="i1", transcript="HELLO", now=self.now))
        self.assertIsNone(verify_external_attestation(
            ATTESTATION_KEY, signed, session_id=self.call.session_id,
            item_id="i1", transcript="hello", now=self.now+11))
        self.assertIsNone(verify_external_attestation(
            b"wrong"*10, signed, session_id=self.call.session_id,
            item_id="i1", transcript="hello", now=self.now))
        self.assertEqual(verify_external_attestation(
            ATTESTATION_KEY, signed, session_id=self.call.session_id,
            item_id="i1", transcript="hello", now=self.now), ("person:aki","guest"))

    def test_owner_requires_grant_and_attestation_for_exact_call(self):
        phrase = "We decided to improve private owner recall."
        self.call.upstream_speech_stopped("owner1")
        self.call.upstream_transcript_completed("owner1", phrase)
        owner_ticket=self.ticket("owner1",phrase,"person:owner","owner")
        self.assertFalse(self.call.verify_turn("owner1",owner_ticket))
        self.call.upstream_speech_stopped("owner2")
        self.call.upstream_transcript_completed("owner2",phrase)
        grant=issue_grant(OWNER_KEY,True,self.call.session_id,now=self.now,ttl=120)
        self.assertTrue(self.call.verify_turn("owner2",
            self.ticket("owner2",phrase,"person:owner","owner"),
            owner_grant=grant))
        self.assertIn("private owner recall",
                      self.call.context_for_verified_turn("owner2"))
        self.call.upstream_speech_stopped("guest3")
        self.call.upstream_transcript_completed("guest3","I'm the owner!")
        self.assertFalse(self.call.verify_turn("guest3",self.ticket(
            "guest3", "I'm the owner!", "person:owner", "owner")))
        self.assertEqual(self.call.context_for_verified_turn("owner2"), "")

    def test_guest_switch_clears_all_previous_notes(self):
        self.assertTrue(self.speak("i1","Please remember my blue car."))
        self.assertTrue(self.speak("i2","What is today's weather?",
                                    speaker="person:bob"))
        ctx=self.call.context_for_verified_turn("i2")
        self.assertIn("weather",ctx)
        self.assertNotIn("blue car",ctx)
        self.assertEqual(self.call.context_for_verified_turn("i1"),"")

    def test_unknown_speaker_cancel_disconnect_and_expiry(self):
        self.assertTrue(self.speak("i1","Remember my garden."))
        self.call.unknown_turn()
        self.assertEqual(self.call.context_for_verified_turn("i1"),"")
        self.call.upstream_speech_stopped("i2")
        self.call.upstream_transcript_completed("i2","Hi again.")
        self.tick += 16
        self.assertFalse(self.call.verify_turn("i2",self.ticket("i2","Hi again.")))
        self.call.end_call()
        self.assertFalse(self.call.upstream_speech_stopped("i3"))
        self.assertEqual(self.call.context_for_verified_turn("i2"),"")

    def test_duplicate_item_after_120_turns_is_still_denied(self):
        self.assertTrue(self.speak("i0","Remember my house."))
        for i in range(1,121):
            self.assertTrue(self.speak("i"+str(i),"Okay."))
        self.assertFalse(self.call.upstream_speech_stopped("i0"))
        self.assertEqual(self.call.context_for_verified_turn("i120"),"")

    def test_owner_claims_probable_speaker_and_bad_roles_denied(self):
        for speaker,role in (("person:owner","guest"),
                             ("person:aki","owner"),
                             ("unknown","guest")):
            with self.assertRaises(ValueError):
                issue_external_attestation(
                    ATTESTATION_KEY, session_id=self.call.session_id,
                    item_id="a", transcript="hello", speaker_id=speaker,
                    speaker_role=role, now=self.now)
        no_signer=AttestedLiveCall()
        no_signer.upstream_speech_stopped("unknown1")
        no_signer.upstream_transcript_completed("unknown1","hello")
        self.assertFalse(no_signer.verify_turn("unknown1","claimed"))
        self.assertEqual(no_signer.context_for_verified_turn("unknown1"),"")

    def test_utf8_exact_hash_and_cap(self):
        japanese = "覚えて。BluetoothはC5に残す予定です。"
        self.assertTrue(self.speak("j1",japanese))
        self.assertIn("Bluetooth",self.call.context_for_verified_turn("j1"))
        self.call.upstream_speech_stopped("j2")
        self.assertFalse(self.call.upstream_transcript_completed("j2","覚"*700))
        self.assertEqual(self.call.context_for_verified_turn("j1"),"")


if __name__=="__main__":
    unittest.main()
