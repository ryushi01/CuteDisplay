"""Tests for bounded Ubuntu finalized snapshot retention (no S3 hardware needed)."""
import tempfile
import unittest
from pathlib import Path
from kitty_refresh_finalized_v6 import newest_finalized, prune_superseded

class RetentionTest(unittest.TestCase):
    def test_keep_latest_and_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "snapshot-first"
            second = root / "snapshot-second"
            staging = root / "staging-active"
            for p in (first, second, staging):
                (p / "kitty").mkdir(parents=True)
                (p / "kitty" / "facts.tsv").write_text("name\tShana\n")
            self.assertEqual(prune_superseded(root, second), 1)
            self.assertFalse(first.exists())
            self.assertTrue(second.is_dir())
            self.assertTrue(staging.is_dir())
    def test_refuse_symlinked_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            keep=root/"snapshot-keep"
            old=root/"snapshot-old"
            (keep/"kitty").mkdir(parents=True)
            (old/"kitty").mkdir(parents=True)
            (old/"kitty"/"external").symlink_to(keep/"kitty",target_is_directory=True)
            self.assertEqual(prune_superseded(root,keep),0)
            self.assertTrue(old.is_dir())

if __name__=="__main__":
    unittest.main()
