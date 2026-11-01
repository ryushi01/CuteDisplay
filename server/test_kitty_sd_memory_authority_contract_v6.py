"""Kitty V6 memory authority guardrails; static regression contracts.

These checks protect the SD-first architecture. They do not prove physical
microSD durability or offline semantic recall.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SdMemoryAuthorityContract(unittest.TestCase):
    def test_s3_export_is_read_only_to_sd(self):
        sync = (ROOT / "firmware/CuteDisplayBrain/KittyMemorySyncV6.h").read_text()
        self.assertIn("KittyMemory::requestExport", sync)
        self.assertIn("KittyMemory::takeExport", sync)
        for dangerous in ("SD_MMC.remove(", "SD_MMC.format(", "SD_MMC.rename("):
            self.assertNotIn(dangerous, sync)

    def test_server_indexes_copies_not_device_storage(self):
        refresh = (ROOT / "server/kitty_refresh_finalized_v6.py").read_text()
        index = (ROOT / "server/kitty_sd_semantic_index.py").read_text()
        receiver = (ROOT / "server/kitty_sd_snapshot_v6.py").read_text()
        self.assertIn("newest_finalized(root)", refresh)
        self.assertIn("The S3 microSD remains authoritative", index)
        self.assertIn("staging-", receiver)
        self.assertIn("snapshot-", receiver)
        self.assertIn("expired = 0", refresh)
        self.assertIn("removed = 0", refresh)

    def test_unknown_speaker_never_becomes_owner_by_default(self):
        attribution = (ROOT / "server/kitty_semantic_attribution_v6.py").read_text()
        context = (ROOT / "server/kitty_memory_context_v6.py").read_text()
        self.assertIn('if role=="owner":', attribution)
        self.assertIn("unverified_identity", context)


if __name__ == "__main__":
    unittest.main()
