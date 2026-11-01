"""Privacy regression for per-turn semantic recall handoff."""
import unittest
from kitty_turn_lease_v6 import TurnContextGate

class TurnLeaseTests(unittest.TestCase):
    def test_exact_speaker_and_turn_only_once(self):
        gate = TurnContextGate(clock=lambda: 10)
        self.assertTrue(gate.stage("turn-a", "person:camille", "Camille's detail"))
        self.assertEqual(gate.consume("turn-a", "person:camille"), "Camille's detail")
        self.assertEqual(gate.consume("turn-a", "person:camille"), "")

    def test_different_speaker_destroys_pending_context(self):
        gate = TurnContextGate(clock=lambda: 10)
        gate.stage("turn-a", "person:camille", "private")
        self.assertEqual(gate.consume("turn-a", "person:aki"), "")
        self.assertEqual(gate.consume("turn-a", "person:camille"), "")

    def test_different_turn_destroys_pending_context(self):
        gate = TurnContextGate(clock=lambda: 10)
        gate.stage("turn-a", "person:camille", "private")
        self.assertEqual(gate.consume("turn-b", "person:camille"), "")
        self.assertEqual(gate.consume("turn-a", "person:camille"), "")

    def test_expired_context_never_reused(self):
        now = [0.]
        gate = TurnContextGate(clock=lambda: now[0], ttl=1.)
        gate.stage("turn-a", "person:camille", "private")
        now[0] = 1.
        self.assertEqual(gate.consume("turn-a", "person:camille"), "")

    def test_unknown_speaker_rejected(self):
        gate = TurnContextGate()
        self.assertFalse(gate.stage("turn-a", "unknown", "private"))
        self.assertFalse(gate.stage("turn-a", "person:\nother", "private"))

    def test_replacement_invalidates_previous_turn(self):
        gate = TurnContextGate(clock=lambda: 10)
        gate.stage("turn-a", "person:camille", "A")
        gate.stage("turn-b", "person:aki", "B")
        self.assertEqual(gate.consume("turn-a", "person:camille"), "")
        # Wrong consume clears the new lease too.
        self.assertEqual(gate.consume("turn-b", "person:aki"), "")

if __name__ == "__main__":
    unittest.main()
