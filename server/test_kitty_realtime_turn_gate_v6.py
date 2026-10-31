"""Safety regression tests for disposable Kitty turn authorization."""
import unittest
from kitty_realtime_turn_gate_v6 import MemoryTurnGate


class GateTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.g = MemoryTurnGate(clock=lambda: self.now, ttl=3.0)

    def test_unknown_refused(self):
        token = self.g.begin("item-1")
        self.assertFalse(self.g.accept_speaker(token, "item-1", "unknown", "unknown"))
        self.assertFalse(self.g.allow_recall(token, "item-1", "person:alice"))

    def test_exact_item_required_and_single_use(self):
        token = self.g.begin("item-1")
        self.assertFalse(self.g.accept_speaker(token, "item-2", "person:alice", "probable"))
        self.assertTrue(self.g.accept_speaker(token, "item-1", "person:alice", "probable"))
        self.assertEqual(self.g.consume_context(token, "item-1", "person:bob", "private"), "")
        self.assertEqual(self.g.consume_context(token, "item-1", "person:alice", "memory"), "memory")
        self.assertEqual(self.g.consume_context(token, "item-1", "person:alice", "replay"), "")

    def test_barge_in_invalidates_old_epoch(self):
        token = self.g.begin("item-1")
        self.g.accept_speaker(token, "item-1", "person:alice", "probable")
        next_token = self.g.begin("item-2")
        self.assertNotEqual(token, next_token)
        self.assertEqual(self.g.consume_context(token, "item-1", "person:alice", "private"), "")

    def test_expiry(self):
        token = self.g.begin("item-1")
        self.g.accept_speaker(token, "item-1", "person:alice", "probable")
        self.now += 3.1
        self.assertEqual(self.g.consume_context(token, "item-1", "person:alice", "private"), "")

    def test_conflicting_speaker_invalidates(self):
        token = self.g.begin("item-1")
        self.g.accept_speaker(token, "item-1", "person:alice", "probable")
        self.assertFalse(self.g.accept_speaker(token, "item-1", "person:bob", "probable"))
        self.assertFalse(self.g.allow_recall(token, "item-1", "person:alice"))


if __name__ == "__main__":
    unittest.main()
