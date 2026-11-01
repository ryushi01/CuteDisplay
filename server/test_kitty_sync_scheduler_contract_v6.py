"""Source checks for prompt SD synchronization without realtime audio interference."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNC = ROOT / "firmware/CuteDisplayBrain/KittyMemorySyncV6.h"
BRAIN = ROOT / "firmware/CuteDisplayBrain/CuteDisplayBrain.ino"

class SyncSchedulerContract(unittest.TestCase):
    def test_fast_idle_retry_not_ten_minute_poll(self):
        source = SYNC.read_text()
        self.assertIn("IDLE_QUIET_MS=500UL", source)
        self.assertIn("PERIODIC_REFRESH_MS=60000UL", source)
        self.assertIn("pauseForSpeech()", source)
        self.assertIn("callActive && callActive()?750:12", source)
        self.assertIn("FAILURE_RETRY_MS=15000UL", source)
        self.assertIn("pdMS_TO_TICKS(500)", source)
        self.assertNotIn("pdMS_TO_TICKS(600000)", source)
        self.assertIn("syncedSaved!=KittyMemory::saved", source)

    def test_call_audio_remains_prioritized(self):
        source = SYNC.read_text()
        brain = BRAIN.read_text()
        self.assertIn("if(!allowed())", source)
        self.assertIn("if(!allowed())return -1;", source)
        self.assertIn("!BrainRealtimeDirect::active()", brain)
        self.assertIn("!BrainRealtimeAudio::active()", brain)
        self.assertIn("!BrainAI::busy", brain)
        self.assertIn("!BrainVoiceSTT::running", brain)
        self.assertIn("!BrainTTS::running", brain)
        self.assertIn("KittyMemory::requestExport(", source)

if __name__ == "__main__":
    unittest.main()
