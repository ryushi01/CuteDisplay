#!/usr/bin/env python3
import unittest
from kitty_identity_attribution_v6 import (
    Attribution, OWNER, UNKNOWN, resolve_speaker, should_write_owner_fact,
    memory_record, correction_target,
)

class IdentityAttributionV6Tests(unittest.TestCase):
    def test_unverified_mic_is_not_owner(self):
        a=resolve_speaker()
        self.assertEqual(a.speaker_id,UNKNOWN)
        self.assertFalse(should_write_owner_fact(a))
    def test_spoken_kitty_role_is_not_authenticated(self):
        a=resolve_speaker(explicit_role="kitty")
        self.assertEqual(a.speaker_id,UNKNOWN)
        self.assertEqual(a.confidence,"unknown")

    def test_verified_owner_only(self):
        a=resolve_speaker(session_owner_verified=True)
        self.assertEqual(a.speaker_id,OWNER)
        self.assertTrue(should_write_owner_fact(a))
    def test_chatgpt_claim_is_distinct_from_shana(self):
        a=resolve_speaker(explicit_identity="ChatGPT",explicit_role="remote_ai")
        self.assertEqual(a.speaker_id,"remote_ai:chatgpt")
        self.assertNotEqual(a.speaker_id,OWNER)
        self.assertFalse(should_write_owner_fact(a))
        self.assertEqual(a.confidence,"claimed")
    def test_remote_ai_claim_takes_precedence(self):
        a=resolve_speaker(session_owner_verified=True,explicit_identity="ChatGPT",explicit_role="remote_ai")
        self.assertEqual(a.speaker_id,"remote_ai:chatgpt")
    def test_statement_subject_is_not_assumed_speaker(self):
        guest=resolve_speaker(explicit_identity="ChatGPT",explicit_role="remote_ai")
        record=memory_record("Shana created Kitty", guest,about_id=OWNER)
        self.assertEqual(record["about_id"],OWNER)
        self.assertEqual(record["attribution"]["speaker_id"],"remote_ai:chatgpt")
    def test_correction_never_overwrites_other_person(self):
        owner=resolve_speaker(session_owner_verified=True)
        guest=resolve_speaker(explicit_identity="ChatGPT",explicit_role="remote_ai")
        self.assertIsNone(correction_target(owner,guest))
        self.assertEqual(correction_target(guest,guest),"remote_ai:chatgpt")
    def test_unverified_claim_cannot_be_verified_owner(self):
        with self.assertRaises(ValueError):
            Attribution("person:owner","owner","explicit_introduction","claimed")
    def test_verified_cannot_come_from_speech_only(self):
        with self.assertRaises(ValueError):
            Attribution("remote_ai:chatgpt","remote_ai","explicit_introduction","verified")

if __name__=="__main__":
    unittest.main()
