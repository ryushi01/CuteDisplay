"""Static contracts for opt-in shared SD memory reaching AI delegation."""
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1] / "firmware" / "CuteDisplayBrain"


class ShareableAiIntegrationContract(unittest.TestCase):
    def test_sd_worker_owns_reads_and_writes(self):
        source=(ROOT/"KittyMemory.h").read_text()
        self.assertIn("refreshSharedContextOnSdWorker()",source)
        self.assertIn('SD_MMC.open("/kitty/shareable_memories_v6.tsv",FILE_READ)',source)
        self.assertIn('SD_MMC.open("/kitty/shareable_memories_v6.tsv",FILE_APPEND)',source)
        self.assertIn("static char sharedContextCache[641]",source)
        self.assertIn("queueApprovedSharedMemory",source)

    def test_delegation_has_approved_context_without_voice_identity(self):
        source=(ROOT/"BrainAI.h").read_text()
        self.assertIn("KittyMemory::shareableContext()",source)
        self.assertIn("Explicitly shared, non-secret Kitty SD notes",source)
        self.assertNotIn("queueApprovedSharedMemory(",source)

    def test_no_auto_approval_from_speech(self):
        source=(ROOT/"BrainRealtimeDirect.h").read_text()
        self.assertNotIn("queueApprovedSharedMemory(",source)


if __name__=="__main__":
    unittest.main()
