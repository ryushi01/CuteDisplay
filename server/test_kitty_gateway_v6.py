#!/usr/bin/env python3
"""Offline tests for guarded Open WebUI realtime V6 patch."""
import unittest
from patch_openwebui_semantic_v6 import patch, MARKER

SOURCE = """
async def socket(auth):
    kitty_expressions = auth.get('kitty_expressions') is True
    kitty_sd_memory = auth.get('kitty_sd_memory', '')
    if not isinstance(kitty_sd_memory, str) or len(kitty_sd_memory.encode('utf-8')) > 850:
        kitty_sd_memory = ''
    return kitty_sd_memory
"""

class V6GatewayTests(unittest.TestCase):
    def test_patch_is_compilable_and_idempotent(self):
        patched=patch(SOURCE)
        self.assertIn(MARKER,patched)
        self.assertIn("bounded_semantic_context(",patched)
        self.assertEqual(patch(patched),patched)
    def test_rejects_incompatible_version(self):
        with self.assertRaises(ValueError):
            patch("async def socket(auth): return None")
    def test_disabled_for_browser_sessions(self):
        self.assertIn("auth.get('kitty_semantic_v6') is True and kitty_expressions",patch(SOURCE))
if __name__=="__main__":
    unittest.main()
