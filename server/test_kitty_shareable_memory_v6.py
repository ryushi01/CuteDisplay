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

    def test_bounded_result(self):
        self.write("one\tshared\t" + "A" * 300 + "\n"
                   "two\tshared\t" + "B" * 300 + "\n")
        result = shareable_context(self.root, max_chars=350)
        self.assertIn("A" * 300, result)
        self.assertNotIn("B" * 300, result)


if __name__ == "__main__":
    unittest.main()
