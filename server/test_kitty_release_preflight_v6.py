import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from kitty_release_preflight_v6 import inspect_release

class ReleasePreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        data = b"\\xe9" + b"A" * 500
        (self.dir / "firmware.bin").write_bytes(data)
        self.meta = dict(id="test-1", filename="firmware.bin", kind="bundle",
                         size=len(data), sha256=hashlib.sha256(data).hexdigest(),
                         state="quarantined")
        self.save()
    def tearDown(self):
        self.temp.cleanup()
    def save(self):
        (self.dir / "metadata.json").write_text(json.dumps(self.meta))
    def test_valid_but_not_deployable(self):
        r = inspect_release(self.dir)
        self.assertTrue(r["checksum_valid"])
        self.assertTrue(r["release_slot_fit"])
        self.assertFalse(r["deploy_allowed"])
        self.assertIn("installed S3 OTA partition size unknown", r["blockers"])
    def test_invalid_checksum(self):
        self.meta["sha256"] = "0" * 64
        self.save()
        self.assertFalse(inspect_release(self.dir)["checksum_valid"])
    def test_installed_slot_too_small(self):
        r = inspect_release(self.dir, 400)
        self.assertFalse(r["installed_slot_fit"])
    def test_invalid_image(self):
        (self.dir / "firmware.bin").write_bytes(b"BAD")
        self.assertFalse(inspect_release(self.dir)["image_header_valid"])
    def test_path_rejected(self):
        self.meta["filename"] = "../out.bin"
        self.save()
        with self.assertRaises(ValueError):
            inspect_release(self.dir)
if __name__ == "__main__":
    unittest.main()
