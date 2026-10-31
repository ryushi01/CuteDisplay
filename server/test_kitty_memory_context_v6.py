"""Focused tests for shared text/call speaker-scoped context."""
import unittest
from kitty_memory_context_v6 import recall_context


class ContextTests(unittest.TestCase):
    @staticmethod
    def fake(db, query, *, k, speaker_id):
        return [
            {"speaker_id": "other", "text": "secret", "provenance": "unverified"},
            {"speaker_id": speaker_id, "text": "Je m'appelle Camille", "provenance": "explicit_introduction"},
        ]

    def test_only_matching_speaker(self):
        result = recall_context("cache.db", "私の名前は？", "speaker-1", search_fn=self.fake)
        self.assertIn("Camille", result)
        self.assertNotIn("secret", result)
        self.assertIn("unverified_identity", result)

    def test_unknown_identity_fails_closed_without_search(self):
        def forbidden(*args, **kwargs):
            raise AssertionError("Must not query for unknown speaker")
        self.assertEqual(recall_context("cache.db", "name", "unknown", search_fn=forbidden), "")

    def test_cache_failure_does_not_break_calls(self):
        def missing(*args, **kwargs):
            raise OSError("cache unavailable")
        self.assertEqual(recall_context("missing.db", "name", "speaker-1", search_fn=missing), "")


if __name__ == "__main__":
    unittest.main()
