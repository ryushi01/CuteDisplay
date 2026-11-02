#!/usr/bin/env python3
"""Offline, no-model tests for the optional single-call continuity buffer."""
import unittest
from kitty_live_rolling_context_v6 import LiveCallContinuity


def trusted(speaker="person:aki",item="turn-1",session="live-session-123"):
    return {"speaker_id":speaker,"speaker_role":"guest",
            "provenance":"session_verified","item_id":item,"session_id":session}


class LiveContinuityTests(unittest.TestCase):
    def setUp(self):
        self.memory=LiveCallContinuity(max_context_bytes=950,recent_turns=4,
                                      pinned_turns=10)
        self.memory.begin_call("live-session-123")

    def test_old_explicit_decision_survives_hundred_filler_turns(self):
        self.assertTrue(self.memory.observe(
            "We decided the Kitty project will keep Bluetooth on C5.",
            trusted(item="turn-0"),trusted_item_id="turn-0"))
        for i in range(1,121):
            self.assertTrue(self.memory.observe(
                "Can you tell me another interesting story?",
                trusted(item=f"turn-{i}"),trusted_item_id=f"turn-{i}"))
        context=self.memory.context_for_turn(
            trusted(item="turn-120"),trusted_item_id="turn-120")
        self.assertIn("Bluetooth on C5",context)
        self.assertLessEqual(len(context.encode("utf-8")),950)

    def test_unverified_or_probable_voice_clears_previous_speaker(self):
        self.memory.observe("Please remember I like coffee.",
                            trusted(item="a"),trusted_item_id="a")
        for source in ("voice_probable","explicit_introduction","unverified"):
            self.memory.observe("Remember my secret.",
                                {**trusted(item="b"),"provenance":source},
                                trusted_item_id="b")
            self.assertEqual(self.memory.context_for_turn(
                trusted(item="a"),trusted_item_id="a"),"")
            self.memory.observe("Please remember I like coffee.",
                                trusted(item="a"),trusted_item_id="a")

    def test_speaker_switch_never_shares_history(self):
        self.memory.observe("We agreed on a private meeting.",
                            trusted(item="a"),trusted_item_id="a")
        self.memory.observe("Today is sunny.",
                            trusted(speaker="person:bob",item="b"),
                            trusted_item_id="b")
        bob=self.memory.context_for_turn(
            trusted(speaker="person:bob",item="b"),trusted_item_id="b")
        self.assertNotIn("meeting",bob)
        self.assertIn("sunny",bob)
        self.assertEqual(self.memory.context_for_turn(
            trusted(item="a"),trusted_item_id="a"),"")

    def test_session_boundary_flushes_data(self):
        self.memory.observe("We decided to use PSRAM buffers.",
                            trusted(item="a"),trusted_item_id="a")
        self.memory.end_call()
        self.memory.begin_call("new-session-5678")
        self.assertEqual(self.memory.context_for_turn(
            trusted(session="new-session-5678"),trusted_item_id="turn-1"),"")

    def test_wrong_item_and_claimed_owner_fail_closed(self):
        self.memory.observe("Remember my plan for tomorrow.",
                            trusted(item="a"),trusted_item_id="a")
        self.assertEqual(self.memory.context_for_turn(
            trusted(item="b"),trusted_item_id="a"),"")
        self.assertFalse(self.memory.observe("My name is Aki",
            {**trusted(item="b"),"speaker_role":"owner"},
            trusted_item_id="b"))
        self.assertEqual(self.memory.context_for_turn(
            trusted(item="a"),trusted_item_id="a"),"")

    def test_duplicate_item_not_replayed(self):
        a=trusted(item="a")
        self.assertTrue(self.memory.observe("My goal is to draw Kitty.",a,trusted_item_id="a"))
        self.assertFalse(self.memory.observe("My goal is to steal Kitty.",a,trusted_item_id="a"))
        context=self.memory.context_for_turn(a,trusted_item_id="a")
        self.assertIn("draw Kitty",context)
        self.assertNotIn("steal Kitty",context)

    def test_japanese_utf8_budget_and_no_empty_injection(self):
        t="覚えてください。今度の設定では "+("安全なメモリーを検証する。"*60)
        self.assertTrue(self.memory.observe(t,trusted(),trusted_item_id="turn-1"))
        context=self.memory.context_for_turn(trusted(),trusted_item_id="turn-1")
        self.assertTrue(context)
        self.assertLessEqual(len(context.encode("utf-8")),950)
        self.assertIn("覚えて",context)
        self.assertEqual(self.memory.context_for_turn(
            {"speaker_id":"unknown"},trusted_item_id="turn-1"),"")


if __name__=="__main__":
    unittest.main()
