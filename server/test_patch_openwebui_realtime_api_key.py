"""Offline, version-guard and security check for optional Open WebUI source patch."""
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).with_name("patch_openwebui_realtime_api_key.py")
spec = importlib.util.spec_from_file_location("realtime_patch", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class PatchTests(unittest.TestCase):
    def mock_source(self):
        return (
            "from fastapi import APIRouter, WebSocket, WebSocketDisconnect\n"
            "from open_webui.utils.auth import get_verified_user_by_token\n"
            "import logging\n"
            "router = APIRouter()\n"
            "log = logging.getLogger(__name__)\n"
            "async def f(ws, token, redis):\n"
            "    user = await get_verified_user_by_token(token, redis)\n"
            "    current = await get_verified_user_by_token(token, redis)\n"
            "    return user, current\n"
        )

    def test_api_key_path_uses_existing_permissions(self):
        code = mod.patch_authentication(self.mock_source())
        self.assertIn("get_current_user_by_api_key(ws, token)", code)
        self.assertIn("user.role in", code)
        self.assertIn('{"user", "admin"}', code)
        self.assertIn("return await get_verified_user_by_token(token, redis)", code)
        self.assertIn("current = await _cutedisplay_verified_realtime_user(ws, token, redis)", code)
        compile(code, "<version-guard-test>", "exec")

    def test_second_application_is_idempotent(self):
        once=mod.patch_authentication(self.mock_source())
        twice=mod.patch_authentication(once)
        self.assertEqual(once,twice)

    def test_unknown_source_rejected_without_changes(self):
        with self.assertRaises(ValueError):
            mod.patch_authentication("async def existing():\n    return None\n")


if __name__ == "__main__":
    unittest.main()
