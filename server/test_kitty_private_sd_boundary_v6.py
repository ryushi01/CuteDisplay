#!/usr/bin/env python3
"""Offline boundary: SD speaker claims cannot be promoted into owner history.

Only disposable S3 snapshot fixtures and a fake CPU embedding model.
Never starts Open WebUI, flashes a board or downloads a model.
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kitty_semantic_attribution_v6 import read_sidecar, iter_archive_with_speakers
from kitty_memory_context_v6 import recall_context
from kitty_sd_semantic_index import build, search


class FakeModel:
    def encode(self, texts, **kw):
        import numpy as np
        return np.ones((len(texts), 4), dtype="float32")


class OwnerNamespaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.sd = Path(self.temp.name) / "snapshot-verified"
        (self.sd / "kitty").mkdir(parents=True)
        self.db = str(Path(self.temp.name) / "derived.sqlite3")

    def test_sd_guest_sidecar_cannot_impersonate_owner(self):
        (self.sd / "kitty/conversations.tsv").write_text(
            "100\tMy hidden color is purple\tOkay\n", encoding="utf-8")
        (self.sd / "kitty/turn_sources.tsv").write_text(
            "100\t0\tperson:owner\tguest\tsession_verified\n"
            "100\t0\tperson:owner\towner\tsession_verified\n",
            encoding="utf-8")
        self.assertEqual(read_sidecar(self.sd), {})
        rows = list(iter_archive_with_speakers(self.sd))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["speaker_id"], "unknown")

    def test_candidate_owner_claim_is_never_owner_private_memory(self):
        (self.sd / "kitty/conversations.tsv").write_text(
            "100\tMy hidden color is purple\tOkay\n", encoding="utf-8")
        (self.sd / "kitty/turn_sources.tsv").write_text(
            "100\t0\tperson:owner\tguest\tvoice_probable\n",
            encoding="utf-8")
        (self.sd / "kitty/speaker_claims_v6.tsv").write_text(
            "100\tperson:owner\tfavorite\tpurple\tvoice_probable\n",
            encoding="utf-8")
        with patch("kitty_sd_semantic_index.get_model", return_value=FakeModel()):
            build(self.sd, self.db)
            self.assertEqual(search(
                self.db,"hidden color",speaker_id="person:owner"), [])
            # Defense-in-depth: a guest role in a stale derived index
            # cannot be read under the reserved owner namespace.
            with sqlite3.connect(self.db) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO semantic_speakers
                    (id,generation,speaker_id,speaker_role,provenance)
                    SELECT id,generation,'person:owner','guest',
                    'session_verified' FROM semantic_v6
                    WHERE id LIKE 'conversations.tsv:%'
                """)
                self.assertGreater(conn.execute(
                    "SELECT count(*) FROM semantic_speakers "
                    "WHERE speaker_id='person:owner'").fetchone()[0], 0)
            self.assertEqual(search(
                self.db,"hidden color",speaker_id="person:owner"), [])

    def test_formatter_also_rejects_guest_or_probable_owner_rows(self):
        def fake(*args, **kwargs):
            return [
                {"speaker_id":"person:owner", "speaker_role":"guest",
                 "provenance":"session_verified", "text":"guest's private data"},
                {"speaker_id":"person:owner", "speaker_role":"owner",
                 "provenance":"voice_probable", "text":"probable private data"},
            ]
        self.assertEqual(recall_context(
            self.db,"my plans","person:owner",search_fn=fake), "")
        self.assertEqual(recall_context(
            self.db,"my plans","person:guest",search_fn=fake), "")


if __name__ == "__main__":
    unittest.main()
