#!/usr/bin/env python3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from kitty_refresh_finalized_v6 import newest_finalized, refresh

class RefreshFinalizedTests(unittest.TestCase):
    def test_only_finalized_used(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/"staging-new"/"kitty").mkdir(parents=True)
            with self.assertRaises(ValueError):
                newest_finalized(root)
            (root/"snapshot-ok"/"kitty").mkdir(parents=True)
            self.assertEqual(newest_finalized(root).name,"snapshot-ok")
            self.assertEqual(refresh(root,root/"index.sqlite",dry_run=True)["mode"],"dry-run")
    def test_refresh_passes_snapshot_to_existing_indexer(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/"snapshot-final"/"kitty").mkdir(parents=True)
            with patch("kitty_refresh_finalized_v6.build",return_value={"indexed":2}) as build:
                result=refresh(root,root/"index.sqlite")
                build.assert_called_once_with(str(root/"snapshot-final"),str(root/"index.sqlite"))
                self.assertEqual(result["indexed"],2)
    def test_skips_symlinked_snapshots(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/"snapshot-good"/"kitty").mkdir(parents=True)
            (root/"snapshot-bad").symlink_to(root/"snapshot-good",target_is_directory=True)
            self.assertEqual(newest_finalized(root).name,"snapshot-good")

if __name__=="__main__":
    unittest.main()
