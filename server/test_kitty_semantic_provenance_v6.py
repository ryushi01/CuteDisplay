"""Regression: S3 speaker provenance survives Ubuntu snapshot indexing."""
import tempfile
import unittest
from pathlib import Path

from kitty_semantic_attribution_v6 import iter_archive_with_speakers


class SpeakerProvenanceTests(unittest.TestCase):
    def test_voice_probable_is_guest_not_owner(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "kitty"
            root.mkdir()
            raw = b"123\tBonjour, je suis Camille\t[voice transcript]\n"
            (root / "conversations.tsv").write_bytes(raw)
            (root / "turn_sources.tsv").write_text(
                "123\t0\tperson:camille\tguest\tvoice_probable\n", encoding="utf-8")
            rows = list(iter_archive_with_speakers(temp))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["speaker_id"], "person:camille")
            self.assertEqual(rows[0]["speaker_role"], "guest")
            self.assertEqual(rows[0]["provenance"], "voice_probable")

    def test_owner_role_from_untrusted_sidecar_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "kitty"
            root.mkdir()
            (root / "conversations.tsv").write_bytes(b"123\tHello\t[voice transcript]\n")
            (root / "turn_sources.tsv").write_text(
                "123\t0\tperson:camille\towner\tsession_verified\n", encoding="utf-8")
            rows = list(iter_archive_with_speakers(temp))
            self.assertEqual(rows[0]["speaker_id"], "unknown")


if __name__ == "__main__":
    unittest.main()
