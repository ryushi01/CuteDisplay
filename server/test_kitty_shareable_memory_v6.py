"""Privacy contracts for explicit SD shareable-memory reader."""
import tempfile
import unittest
from pathlib import Path
from kitty_shareable_memory_v6 import read_shareable, shareable_context


class ShareableMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "kitty").mkdir()

    def write(self, data):
        (self.root / "kitty/shareable_memories_v6.tsv").write_text(data, encoding="utf-8")

    def test_no_explicit_file_means_no_shared_memory(self):
        self.assertEqual(read_shareable(self.root), [])
        self.assertEqual(shareable_context(self.root), "")

    def test_only_exact_shared_flag_enters_context(self):
        self.write("one\tprivate\tSecret\n"
                   "two\tshared\tLikes orange cats\n"
                   "three\tvoice_probable\tVoice claim\n"
                   "four\tShared\tWrong flag\n")
        self.assertEqual(read_shareable(self.root), [("two", "Likes orange cats")])
        self.assertIn("Likes orange cats", shareable_context(self.root))
        self.assertNotIn("Secret", shareable_context(self.root))
        self.assertNotIn("Voice claim", shareable_context(self.root))

    def test_bad_records_never_trigger_archive_fallback(self):
        self.write("bad id\tshared\tNot valid\n"
                   "other\tshared\tbad\tcolumn\n"
                   "ctrl\tshared\tInjected\x01text\n")
        self.assertEqual(read_shareable(self.root), [])
        self.assertEqual(shareable_context(self.root), "")

    def test_no_symlink_access(self):
        target = self.root / "private.tsv"
        target.write_text("x\tshared\tDo not follow\n")
        (self.root / "kitty/shareable_memories_v6.tsv").symlink_to(target)
        self.assertEqual(read_shareable(self.root), [])

    def test_large_approved_note_does_not_hide_later_shorter_note(self):
        self.write("first\tshared\t" + "A" * 300 + "\n"
                   "oversized\tshared\t" + "B" * 300 + "\n"
                   "small\tshared\tRemember the orange kite\n")
        context = shareable_context(self.root, max_chars=350)
        self.assertIn("A" * 300, context)
        self.assertNotIn("B" * 300, context)
        self.assertIn("Remember the orange kite", context)

    def test_question_finds_later_approved_memory_not_in_startup_budget(self):
        self.write("first\tshared\t" + "A" * 300 + "\n"
                   "second\tshared\t" + "B" * 300 + "\n"
                   "third\tshared\tCrystal Moon has purple oceans\n")
        initial = shareable_context(self.root, max_chars=350)
        self.assertNotIn("Crystal Moon", initial)
        targeted = shareable_context(self.root, max_chars=350,
                                     query="What color were Crystal Moon's oceans?")
        self.assertIn("Crystal Moon has purple oceans", targeted)
        self.assertNotIn("A" * 300, targeted)
        self.assertNotIn("B" * 300, targeted)

    def test_question_cannot_recall_archive_claims_facts_or_private_rows(self):
        self.write("a\tprivate\tMy phone PIN is 0000\n"
                   "b\tvoice_probable\tNever approved for sharing\n"
                   "c\tshared\tKitty's favorite planet is Mochi Planet\n")
        (self.root / "kitty/conversations.tsv").write_text(
            "111\tMy secret planet is Pluto\tOkay\n")
        (self.root / "kitty/speaker_claims_v6.tsv").write_text(
            "111\tperson:owner\tplanet\tJupiter\tvoice_probable\n")
        (self.root / "kitty/facts.tsv").write_text(
            "private_plan\tSaturn\n")
        for term in ("Pluto", "Jupiter", "Saturn", "phone PIN"):
            self.assertEqual(
                shareable_context(self.root, query=term), "")
        approved = shareable_context(self.root, query="Mochi Planet")
        self.assertIn("Mochi Planet", approved)
        self.assertNotIn("Never approved", approved)

    def test_query_must_match_and_not_fall_back_to_unrelated_shared_items(self):
        self.write("one\tshared\tMochi Planet is imaginary\n")
        self.assertEqual(shareable_context(self.root, query="please remember"),
                         "")
        self.assertEqual(shareable_context(self.root, query="Blue ocean"),
                         "")
        self.assertEqual(shareable_context(self.root, query="Mochi" * 100),
                         "")
        self.assertIn("Mochi", shareable_context(self.root, query="Mochi"))

    def test_bounded_result(self):
        self.write("one\tshared\t" + "A" * 300 + "\n"
                   "two\tshared\t" + "B" * 300 + "\n")
        result = shareable_context(self.root, max_chars=350)
        self.assertIn("A" * 300, result)
        self.assertNotIn("B" * 300, result)


if __name__ == "__main__":
    unittest.main()
