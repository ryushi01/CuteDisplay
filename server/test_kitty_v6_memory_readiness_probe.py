#!/usr/bin/env python3
"""No-private-content tests for the read-only Ubuntu V6 memory readiness probe."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from kitty_v6_memory_readiness_probe import (
    report, snapshot_info, index_info, _safe_abs_dir,
)


class ReadinessProbeTests(unittest.TestCase):
    def test_environment_missing_fails_closed(self):
        self.assertEqual(report(None), {"service_environment": "unavailable"})

    def test_snapshot_only_finalized_metadata_and_no_content(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root / "staging-abc12345" / "kitty").mkdir(parents=True)
            (root / "staging-abc12345" / "kitty" / "summaries.tsv").write_text("PRIVATE STAGING")
            final = root / "snapshot-abc12345" / "kitty"
            final.mkdir(parents=True)
            (final / "summaries.tsv").write_text("PRIVATE SUMMARY")
            (final / "conversations.tsv").touch()
            result = snapshot_info(root)
            self.assertEqual(result["snapshot"], "present")
            self.assertEqual(result["summaries"], "nonempty")
            self.assertEqual(result["conversations"], "empty")
            self.assertNotIn("PRIVATE", repr(result))
            self.assertEqual(result["facts"], "missing")

    def test_sqlite_immutable_reader_cannot_create_or_change_index(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "index.sqlite"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE semantic_meta(key TEXT,value TEXT)")
                db.execute("INSERT INTO semantic_meta VALUES('active','4')")
                db.execute("CREATE TABLE semantic_v6(generation INTEGER)")
                db.execute("CREATE TABLE semantic_speakers(generation INTEGER)")
                db.executemany("INSERT INTO semantic_v6 VALUES(4)", [()] * 3)
                db.execute("INSERT INTO semantic_speakers VALUES(4)")
            before = path.read_bytes()
            result = index_info(str(path))
            self.assertEqual(result, {"index": "active", "indexed_rows": "3", "attributed_rows": "1"})
            self.assertEqual(before, path.read_bytes())
            self.assertEqual(sorted(p.name for p in Path(t).iterdir()), ["index.sqlite"])

    def test_missing_index_is_not_created(self):
        with tempfile.TemporaryDirectory() as t:
            missing = Path(t) / "missing.sqlite"
            self.assertEqual(index_info(str(missing)), {"index": "missing_or_unsafe"})
            self.assertFalse(missing.exists())

    def test_symlink_snapshot_and_index_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            actual = root / "target"
            actual.mkdir()
            (root / "snapshots").symlink_to(actual, target_is_directory=True)
            self.assertIsNone(_safe_abs_dir(str(root / "snapshots")))
            dbfile = root / "test.db"
            dbfile.touch()
            (root / "link.db").symlink_to(dbfile)
            self.assertEqual(index_info(str(root / "link.db"))["index"], "missing_or_unsafe")

    def test_exact_config_flags_no_secret_printing(self):
        result = report({"KITTY_SD_SNAPSHOT_ROOT": "", "KITTY_SEMANTIC_DB": "",
                         "KITTY_SEMANTIC_AUTO_REFRESH": "0", "KITTY_MEMORY_TOKEN": "SUPERSECRET"})
        self.assertNotIn("SUPERSECRET", repr(result))
        self.assertEqual(result["auto_refresh_enabled"], "false")
        self.assertEqual(result["index"], "not_configured")


if __name__ == "__main__":
    unittest.main()
