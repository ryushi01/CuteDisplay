"""Regression checks for fail-closed gateway speaker guard patch."""
import unittest
from kitty_gateway_speaker_guard_v6 import patch, ANCHOR, OLD


class GatewayGuardTests(unittest.TestCase):
    def fixture(self):
        return (
            "async def gateway():\n"
            "        async def client_events():\n"
            "            while True:\n"
            + ANCHOR + "\n"
            "                    continue\n"
            + OLD + "\n"
        )

    def test_guard_is_default_off(self):
        source = patch(self.fixture())
        self.assertIn("kitty_server_verified_speaker_turn = False", source)
        self.assertIn("if not kitty_server_verified_speaker_turn:", source)
        self.assertLess(source.index("if not kitty_server_verified_speaker_turn:"),
                        source.index(OLD))

    def test_patch_idempotent(self):
        once = patch(self.fixture())
        self.assertEqual(patch(once), once)

    def test_unrecognized_layout_rejected(self):
        with self.assertRaises(ValueError):
            patch("async def gateway(): pass")


if __name__ == "__main__":
    unittest.main()
