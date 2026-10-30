import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from kitty_deploy_plan_v6 import create_plan

class DeployPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        image = b"\xe9" + b"x" * 1024
        (self.root / "combined.bin").write_bytes(image)
        (self.root / "metadata.json").write_text(json.dumps({
            "id": "test", "kind": "bundle", "filename": "combined.bin",
            "size": len(image), "sha256": hashlib.sha256(image).hexdigest(),
            "state": "quarantined"}))
    def tearDown(self):
        self.tmp.cleanup()
    def test_unknown_device_blocked(self):
        result = create_plan(self.root,{})
        self.assertFalse(result["deploy_allowed"])
        self.assertTrue(result["blockers"])
    def test_sufficient_slots_still_blocked_without_receiver(self):
        inventory = {"firmware": "dev", "next_slot_bytes": 6553600,
                     "running_slot_bytes": 6553600, "busy": False,
                     "authenticated": True, "deploy_supported": False,
                     "rollback_verified": False}
        result = create_plan(self.root, inventory)
        self.assertTrue(result["release"]["installed_slot_fit"])
        self.assertFalse(result["deploy_allowed"])
    def test_untrusted_or_busy_device_blocked(self):
        inventory = {"firmware": "dev", "next_slot_bytes": 6553600,
                     "authenticated": False, "busy": True,
                     "deploy_supported": True, "rollback_verified": True}
        blockers = create_plan(self.root, inventory)["blockers"]
        self.assertTrue(any("authenticated" in b for b in blockers))
        self.assertTrue(any("idle" in b for b in blockers))
if __name__ == "__main__":
    unittest.main()
