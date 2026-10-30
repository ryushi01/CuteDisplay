import hashlib
import hmac
import unittest
from kitty_s3_inventory_v6 import authorize, parse_inventory

class S3InventoryTests(unittest.TestCase):
    def test_hmac_challenge(self):
        key = "a1" * 32
        nonce = "ff" * 16
        expected = hmac.new(bytes.fromhex(key), nonce.encode(), hashlib.sha256).hexdigest()
        self.assertEqual(authorize("CHALLENGE " + nonce, key), "AUTH " + expected)
    def test_reject_malformed(self):
        for challenge in ("nope", "CHALLENGE bad", "CHALLENGE " + "zz" * 16):
            with self.assertRaises(ValueError):
                authorize(challenge, "aa" * 32)
    def test_capabilities(self):
        lines = ["OTA:FW:CallFace-v23-dev", "OTA:RUNNING_SIZE:6553600",
                 "OTA:NEXT_SIZE:6553600", "OTA:RUNNING_SUBTYPE:16",
                 "OTA:BUSY:0", "OTA:DEPLOY_SUPPORTED:0"]
        values = parse_inventory(lines)
        self.assertEqual(values["next_slot_bytes"], 6553600)
        self.assertFalse(values["deploy_supported"])
    def test_missing_field(self):
        with self.assertRaises(ValueError):
            parse_inventory(["OTA:FW:v1"])
if __name__ == "__main__":
    unittest.main()
