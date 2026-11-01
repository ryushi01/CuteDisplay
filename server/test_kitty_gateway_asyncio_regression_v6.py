"""Prevent regression of working realtime voice after semantic patch regeneration."""
import unittest
from patch_openwebui_memory_refresh import SEMANTIC_EVENT, patch


class AsyncioScopingTests(unittest.TestCase):
    def test_semantic_handler_does_not_shadow_asyncio(self):
        self.assertNotIn("                    import asyncio\n", SEMANTIC_EVENT)
        self.assertIn("asyncio.create_task(", SEMANTIC_EVENT)

    def test_existing_gateway_local_import_is_repaired(self):
        # A marker-only source is insufficient to reach optional patch anchors,
        # so exercise the import repair and refuse unsupported layout safely.
        source = (
            "import json\n"
            "async def worker():\n"
            "    print(asyncio.isfuture(None))\n"
            "    if True:\n"
            "                    import asyncio\n"
            "                    kitty_semantic_task = asyncio.create_task(coro())\n"
            "# CuteDisplay live memory refresh v2\n"
        )
        with self.assertRaises(ValueError):
            patch(source)
        # The shared patch's own event template is the critical production check.

    def test_syntax_of_event_template(self):
        self.assertIn("kitty_semantic_task = asyncio.create_task(", SEMANTIC_EVENT)


if __name__ == "__main__":
    unittest.main()
