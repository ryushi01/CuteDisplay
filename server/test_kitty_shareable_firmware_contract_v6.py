"""Static firmware contracts for staged shareable SD-memory export.

These tests do NOT substitute for ESP32 compilation or hardware validation.
"""
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "firmware" / "CuteDisplayBrain"


class ShareableFirmwareContract(unittest.TestCase):
    def test_nine_files_have_matching_boundary_array(self):
        memory=(BASE / "KittyMemory.h").read_text()
        self.assertIn("uint32_t boundaries[9]",memory)
        self.assertIn('"shareable_memories_v6.tsv"',memory)
        self.assertIn("static constexpr uint8_t EXPORT_COUNT=",memory)

    def test_explicit_approval_and_sd_worker_write(self):
        memory=(BASE / "KittyMemory.h").read_text()
        self.assertIn("queueApprovedSharedMemory",memory)
        self.assertIn("if(!approved",memory)
        self.assertIn('SD_MMC.open("/kitty/shareable_memories_v6.tsv",FILE_APPEND)',memory)
        self.assertIn("xQueueReceive(sharedMemoryWrites",memory)
        self.assertIn("sharedRevision++",memory)

    def test_sync_invalidated_by_shared_revision(self):
        sync=(BASE / "KittyMemorySyncV6.h").read_text()
        self.assertIn("sharedBefore!=KittyMemory::sharedRevision",sync)
        self.assertIn("syncedShared!=KittyMemory::sharedRevision",sync)
        self.assertIn("seenShared=KittyMemory::sharedRevision",sync)

    def test_no_auto_public_promotion(self):
        memory=(BASE / "KittyMemory.h").read_text()
        self.assertNotIn("queueApprovedSharedMemory(transcript",memory)
        self.assertNotIn("queueApprovedSharedMemory(utterance",memory)


if __name__=="__main__":
    unittest.main()
