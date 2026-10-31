"""Offline speaker isolation and multilingual query regression tests."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from kitty_sd_semantic_index import _connect, search


class FakeModel:
    def encode(self, texts, normalize_embeddings=True, **kwargs):
        # Deterministic EN/FR/JP shared semantic direction for test only.
        return np.asarray([[1.0, 0.0] for _ in texts], dtype=np.float32)


class SpeakerSemanticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.temp.name) / "derived.sqlite")
        with _connect(self.db) as conn:
            conn.execute("CREATE TABLE semantic_meta (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO semantic_meta VALUES ('active','1')")
            for key, text, speaker in (
                ("intro-owner", "Je m'appelle Camille", "voice-camille"),
                ("intro-guest", "私の名前はアキです", "voice-aki"),
            ):
                conn.execute(
                    "INSERT INTO semantic_v6 VALUES (?,?,?,?,?,?)",
                    (key, text, "digest", np.array([1, 0], dtype="<f4").tobytes(),
                     "fake-model", 1))
                conn.execute(
                    "INSERT INTO semantic_speakers VALUES (?,?,?,?,?)",
                    (key, 1, speaker, "guest", "explicit_introduction"))
            conn.execute(
                "INSERT INTO semantic_v6 VALUES (?,?,?,?,?,?)",
                ("unattributed", "My name is secret", "digest",
                 np.array([1, 0], dtype="<f4").tobytes(), "fake-model", 1))
            conn.commit()

    def tearDown(self):
        self.temp.cleanup()

    def lookup(self, query, speaker=None):
        with patch("kitty_sd_semantic_index.get_model", return_value=FakeModel()):
            return search(self.db, query, model_name="fake-model", speaker_id=speaker)

    def test_missing_or_unknown_speaker_never_returns_other_memories(self):
        self.assertEqual(self.lookup("what is my name?"), [])
        self.assertEqual(self.lookup("what is my name?", "unknown"), [])

    def test_speaker_context_is_separate_across_languages(self):
        for query in ("What is my name?", "Comment je m'appelle ?", "私の名前は？"):
            camille = self.lookup(query, "voice-camille")
            aki = self.lookup(query, "voice-aki")
            self.assertEqual([r["id"] for r in camille], ["intro-owner"])
            self.assertEqual([r["id"] for r in aki], ["intro-guest"])
            self.assertEqual(camille[0]["speaker_id"], "voice-camille")
            self.assertEqual(aki[0]["speaker_id"], "voice-aki")

    def test_unattributed_archive_is_not_treated_as_owner(self):
        self.assertFalse(any(r["id"] == "unattributed"
                             for r in self.lookup("name", "voice-camille")))


if __name__ == "__main__":
    unittest.main()
