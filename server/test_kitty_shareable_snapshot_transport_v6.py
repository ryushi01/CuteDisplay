"""Compatibility tests for optional ninth frozen SD snapshot file."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from kitty_sd_snapshot_v6 import SnapshotReceiver, FILES
from kitty_shareable_memory_v6 import read_shareable


class ShareableSnapshotTransportTests(unittest.TestCase):
    def test_old_eight_file_snapshot_stays_supported(self):
        self.assertIn("facts.tsv", FILES)
        self.assertIn("speaker_claims_v6.tsv", FILES)
        self.assertIn("shareable_memories_v6.tsv", FILES)

    def test_explicit_shareable_file_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            receiver=SnapshotReceiver(Path(tmp) / "receiver")
            payload=b"cat\tshared\tKitty likes the sun\nprivate\tprivate\tHidden\n"
            snapshot="shareable_test_0001"
            name="shareable_memories_v6.tsv"
            self.assertEqual(receiver.chunk(snapshot,name,0,payload),len(payload))
            path=receiver.finalize(snapshot,{name:{
                "size":len(payload),"sha256":hashlib.sha256(payload).hexdigest()
            }})
            self.assertEqual(read_shareable(path),[("cat","Kitty likes the sun")])

    def test_unapproved_filename_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            receiver=SnapshotReceiver(Path(tmp) / "receiver")
            with self.assertRaises(ValueError):
                receiver.chunk("shareable_test_0002","secrets.txt",0,b"x")


if __name__ == "__main__":
    unittest.main()
