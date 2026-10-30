import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import kitty_update_center_v6 as update


class ReleaseTests(unittest.TestCase):
    def test_filename_restrictions(self):
        for value in ("../evil.bin", ".secret", "foo/bar.bin", "a\\b.bin", ""):
            self.assertFalse(update.validate_name(value))
        self.assertTrue(update.validate_name("s3-v6.bin"))

    def test_quarantine_and_checksum(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(update, "ROOT", Path(directory)):
            result = update.store_release("s3", "firmware.bin", b"test firmware")
            self.assertEqual(result["state"], "quarantined")
            self.assertEqual(result["size"], 13)
            self.assertEqual(len(result["sha256"]), 64)
            self.assertEqual(len(update.list_releases()), 1)

    def test_reject_unsupported(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(update, "ROOT", Path(directory)):
            for kind, name in (("other", "firmware.bin"), ("s3", "script.sh"),
                               ("s3", "../firmware.bin")):
                with self.assertRaises(ValueError):
                    update.store_release(kind, name, b"test")


if __name__ == "__main__":
    unittest.main()
