"""Tests for bounded Ubuntu finalized snapshot retention (no S3 hardware needed)."""
import tempfile
import os
import time
import sqlite3
import unittest
from pathlib import Path
from kitty_refresh_finalized_v6 import newest_finalized, prune_superseded, prune_expired_staging, compact_derived_index

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

    def test_expired_staging_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            old=root/"staging-abandoned"
            active=root/"staging-active"
            finalized=root/"snapshot-preserve"
            for p in (old,active,finalized):
                (p/"kitty").mkdir(parents=True)
            now=time.time()
            os.utime(old,(now-9*86400,now-9*86400))
            self.assertEqual(prune_expired_staging(root,now=now),1)
            self.assertFalse(old.exists())
            self.assertTrue(active.exists())
            self.assertTrue(finalized.exists())

    def test_staging_symlink_refused_and_grace_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            outside=root/"preserve"
            outside.mkdir()
            old=root/"staging-old"
            old.mkdir()
            (old/"link").symlink_to(outside,target_is_directory=True)
            now=time.time()
            os.utime(old,(now-10*86400,now-10*86400))
            self.assertEqual(prune_expired_staging(root,now=now),0)
            self.assertTrue(old.exists())
            self.assertTrue(outside.exists())
            with self.assertRaises(ValueError):
                prune_expired_staging(root,max_age_seconds=1,now=now)

    def test_sqlite_compaction_keeps_active_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/"cache.sqlite"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE semantic_meta (key TEXT PRIMARY KEY, value TEXT)")
                conn.execute("INSERT INTO semantic_meta VALUES ('active','4')")
            compact_derived_index(db)
            with sqlite3.connect(db) as conn:
                self.assertEqual(conn.execute("SELECT value FROM semantic_meta WHERE key='active'").fetchone()[0],"4")

if __name__=="__main__":
    unittest.main()
