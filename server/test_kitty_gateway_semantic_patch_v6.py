"""Offline gateway-patch regression; no Open WebUI service touched."""
import unittest
from patch_openwebui_memory_refresh import patch

BASE = '''async def gateway(ws, upstream, protocol, auth, voice_model, voice):
        kitty_expressions = True
        kitty_sd_memory = auth.get('kitty_sd_memory', '')
        await ws.send_json({'type': 'bridge.ready', 'model': voice_model, 'voice': voice, 'sample_rate': 24000})
        async def client_events():
            while True:
                event = await ws.receive_json()
                command = protocol.command(event)
                await upstream.send_json(command)
'''


class GatewaySemanticPatchTests(unittest.TestCase):
    def test_patch_is_syntax_valid_and_idempotent(self):
        once = patch(BASE)
        self.assertEqual(patch(once), once)
        compile(once, "realtime.py", "exec")
        self.assertIn("kitty.memory.semantic.result", once)
        self.assertIn("kitty_semantic_async_client_v6", once)
        self.assertIn("speaker_id == 'unknown'", once)

    def test_semantic_lookup_does_not_await_in_event_consumer(self):
        result = patch(BASE)
        self.assertIn("asyncio.create_task(", result)
        self.assertIn("async def kitty_semantic_reply(", result)
        self.assertNotIn("derived = await semantic_context(", result)

    def test_upgrade_from_old_refresh_source(self):
        # A previously deployed refresh-only gateway must still patch safely.
        old = patch(BASE)
        old = old.replace("kitty_semantic_task = None", "")
        prefix = old.index("        # Optional per-session background semantic lookup.")
        suffix = old.index("        async def client_events():", prefix)
        old = old[:prefix] + old[suffix:]
        start = old.index("                if isinstance(event, dict) and event.get('type') == 'kitty.memory.semantic':")
        end = old.index("                if isinstance(event, dict) and event.get('type') == 'kitty.memory.refresh':", start)
        old = old[:start] + old[end:]
        old = old.replace(", kitty_semantic_task", "")
        upgraded = patch(old)
        self.assertIn("asyncio.create_task(", upgraded)
        compile(upgraded, "realtime.py", "exec")
        self.assertEqual(patch(upgraded), upgraded)

    def test_missing_expected_anchor_fails_closed(self):
        with self.assertRaises(ValueError):
            patch(BASE.replace("command = protocol.command(event)",
                               "command = protocol.other(event)"))


if __name__ == "__main__":
    unittest.main()
