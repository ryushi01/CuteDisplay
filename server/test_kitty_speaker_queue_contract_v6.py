"""Source-level regressions for bounded, turn-keyed speaker attribution.

These checks do not replace Arduino compilation or hardware/audio validation.
"""
import re
import unittest
from pathlib import Path

SOURCE=(Path(__file__).resolve().parents[1] /
        "firmware/CuteDisplayBrain/BrainRealtimeDirect.h").read_text()

class SpeakerAttributionContract(unittest.TestCase):
    def test_bounded_multi_turn_queue_and_expiry(self):
        self.assertIn("SPEAKER_PENDING_MAX=6",SOURCE)
        self.assertIn("SPEAKER_WAIT_MS=5000UL",SOURCE)
        self.assertIn("findSpeakerTurn(String(id->valuestring))",SOURCE)
        self.assertIn("flushSpeakerTurns(false);",SOURCE)
        self.assertIn("speakerOverflow++;archiveSpeakerTurn",SOURCE)
        self.assertNotIn("pendingSpeakerItem",SOURCE)
        self.assertNotIn("flushPendingSpeaker(true)",SOURCE)

    def test_archive_unmatched_without_owner_elevation(self):
        self.assertIn('String("unknown"):t.intro',SOURCE)
        self.assertIn('String("unverified"):String("explicit_introduction")',SOURCE)
        self.assertIn('source="voice_probable"',SOURCE)
        self.assertIn('candidate_provenance',SOURCE)
        self.assertNotIn('authorization="owner"',SOURCE)

    def test_turn_matched_and_reset_paths(self):
        self.assertIn("const String introduction=speakerTurns[slot].intro;",SOURCE)
        self.assertIn("queueAttributed(transcript",SOURCE)
        self.assertIn("clearSpeakerTurn((uint8_t)slot);",SOURCE)
        self.assertGreaterEqual(SOURCE.count("flushSpeakerTurns(true);"),3)
        self.assertIn("speakerUnmatched",SOURCE)
        self.assertIn("speakerExpired",SOURCE)
        self.assertIn("speakerMatched",SOURCE)

if __name__=="__main__":
    unittest.main()
