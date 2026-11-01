"""Read-only recall contracts for SD-derived semantic memory.

No device writes, no live HTTP access, no personal memory printed.
"""
import unittest
from pathlib import Path
from kitty_memory_context_v6 import recall_context
from kitty_realtime_turn_gate_v6 import MemoryTurnGate


class CrossCallRecallContract(unittest.TestCase):
    def test_unknown_identity_returns_no_context(self):
        called=[]
        def fake_search(*args, **kwargs):
            called.append(True)
            return []
        self.assertEqual(recall_context("unused", "past conversation", "unknown",
                                        search_fn=fake_search), "")
        self.assertFalse(called)

    def test_context_is_strictly_speaker_scoped_and_provenance_labeled(self):
        def fake_search(*args, **kwargs):
            return [
                {"speaker_id":"person:other","text":"unrelated private material",
                 "provenance":"voice_probable"},
                {"speaker_id":"person:shana","text":"harmless fixture",
                 "provenance":"explicit_introduction"}
            ]
        context=recall_context("unused", "test", "person:shana",
                               search_fn=fake_search)
        self.assertIn("harmless fixture", context)
        self.assertIn("unverified_identity", context)
        self.assertNotIn("unrelated private material", context)

    def test_probable_voice_cannot_unlock_other_turn(self):
        gate=MemoryTurnGate()
        epoch=gate.begin("turn_one")
        self.assertTrue(gate.accept_speaker(epoch,"turn_one","person:shana","probable"))
        self.assertFalse(gate.allow_recall(epoch,"turn_two","person:shana"))
        self.assertFalse(gate.allow_recall(epoch,"turn_one","person:other"))
        gate.invalidate()
        self.assertFalse(gate.allow_recall(epoch,"turn_one","person:shana"))

    def test_sd_remains_permanent_memory_authority(self):
        code=(Path(__file__).resolve().parents[1] /
              "server/kitty_memory_context_v6.py").read_text()
        self.assertIn("S3 SD card is the sole permanent authority",code)


if __name__=="__main__":
    unittest.main()
