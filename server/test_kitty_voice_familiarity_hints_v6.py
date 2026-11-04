#!/usr/bin/env python3
"""Candidate familiarity is never identity proof, even after many utterances."""
import unittest

from kitty_voice_familiarity_hints_v6 import CandidateFamiliarity


class FamiliarityTests(unittest.TestCase):
    def setUp(self):
        self.now=1.
        self.tracker=CandidateFamiliarity(clock=lambda:self.now)
        self.tracker.begin_call()

    def observe(self, item, speaker="person:shana", score=0.970,
                source="trusted_gateway_cpu", overlap=False):
        return self.tracker.observe(
            provider_item_id=item,speaker_candidate=speaker,score=score,
            recognizer_source=source,echo_or_overlap=overlap)

    def test_repeated_genuine_candidate_becomes_stronger_hint_not_owner(self):
        for index in range(1,7):
            hint=self.observe("turn"+str(index))
            self.assertEqual(hint["familiarity"],
                             "strong_hint" if index>=3 else "growing_hint")
            self.assertFalse(hint["owner_authenticated"])
            self.assertFalse(hint["private_memory_authorized"])
            self.assertFalse(hint["profile_learning_authorized"])
            self.assertEqual(hint["candidate_provenance"],"voice_probable")
        self.assertFalse(self.tracker.owner_authenticated)
        self.assertFalse(self.tracker.private_memory_authorized)

    def test_guest_or_ambiguous_input_revokes_hint(self):
        self.observe("one")
        self.observe("two")
        self.assertIsNone(self.observe("guest","person:aki"))
        self.assertEqual(self.observe("three")["observed_consistent_turns"],1)
        self.assertIsNone(self.observe("four",score=0.94))
        self.assertEqual(self.observe("five")["observed_consistent_turns"],1)

    def test_client_claim_and_microphone_echo_dont_count(self):
        for source in ("client_json","s3_sidecar","transcript",
                       "chatgpt_playback"):
            self.assertIsNone(self.observe("item-"+source,source=source))
        self.assertIsNone(self.observe("playback",overlap=True))
        self.assertEqual(self.observe("fresh")["observed_consistent_turns"],1)

    def test_replay_item_not_accepted(self):
        self.observe("turn1")
        self.observe("turn2")
        self.assertIsNone(self.observe("turn1"))
        self.assertEqual(self.observe("turn3")["observed_consistent_turns"],1)

    def test_timeout_interrupt_and_next_call_clear_hint(self):
        self.observe("turn1")
        self.observe("turn2")
        self.now+=181
        self.assertEqual(self.observe("turn3")["observed_consistent_turns"],1)
        self.tracker.interrupted()
        self.assertEqual(self.observe("turn4")["observed_consistent_turns"],1)
        self.tracker.end_call()
        self.assertIsNone(self.observe("turn5"))
        self.tracker.begin_call()
        self.assertEqual(self.observe("turn6")["observed_consistent_turns"],1)

    def test_many_turns_never_enable_memory(self):
        for i in range(1,129):
            hint=self.observe("turn"+str(i))
            self.assertIsNotNone(hint)
            self.assertFalse(hint["owner_authenticated"])
            self.assertFalse(hint["private_memory_authorized"])
        self.assertIsNone(self.observe("turn129"))


if __name__=="__main__":
    unittest.main()
