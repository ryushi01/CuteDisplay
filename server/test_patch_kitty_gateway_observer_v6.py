"""Fail-closed staging patch checks; no realtime calls or services used."""
import unittest
from patch_kitty_gateway_observer_v6 import patch, MARKER


def sample():
    return (
        "import asyncio\nimport os\n"
        "async def realtime_call():\n"
        "        async def client_events():\n"
        "            nonlocal kitty_memory_last_revision, kitty_memory_context_item, kitty_semantic_task\n"
        "            while True:\n"
        "                event = JSONCodec.loads(raw)\n"
        "                command = protocol.command(event)\n"
        "        async def provider_events():\n"
        "            while True:\n"
        "                event = await upstream.receive_json()\n"
        "                await ws.send_json(event)\n"
    )


class StagingPatchTests(unittest.TestCase):
    def test_patch_compiles_is_idempotent_and_retains_forward(self):
        result = patch(sample())
        self.assertIn(MARKER, result)
        self.assertEqual(result.count("await ws.send_json(event)"), 1)
        self.assertEqual(result.count("observe_upstream(event)"), 1)
        self.assertEqual(result.count("observe_client(event)"), 1)
        self.assertEqual(patch(result), result)
        compile(result, "realtime.py", "exec")

    def test_unexpected_layout_fails_closed(self):
        with self.assertRaises(ValueError):
            patch("async def realtime_call(): pass")


if __name__ == "__main__":
    unittest.main()
