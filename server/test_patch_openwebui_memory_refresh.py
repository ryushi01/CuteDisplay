#!/usr/bin/env python3
"""Offline tests for the guarded, opt-in realtime memory patch."""
from pathlib import Path
import importlib.util

path = Path(__file__).with_name("patch_openwebui_memory_refresh.py")
spec = importlib.util.spec_from_file_location("kitty_memory_refresh", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

SOURCE = """
async def realtime_call(ws):
    auth = {'kitty_sd_memory': '', 'kitty_memory_refresh': True}
    kitty_expressions = True
    kitty_sd_memory = auth.get('kitty_sd_memory', '')
    await ws.send_json({'type': 'bridge.ready', 'model': voice_model, 'voice': voice, 'sample_rate': 24000})
    async def client_events():
        while True:
            raw = await ws.receive_text()
            event = loads(raw)
            command = protocol.command(event)
            await upstream.send_json(command)
"""
patched = module.patch(SOURCE)
assert "kitty_memory_refresh_enabled" in patched
assert "kitty.memory.capabilities" in patched
assert "kitty.memory.refreshed" in patched
assert "conversation.item.delete" in patched
assert "conversation.item.create" in patched
assert "len(memory.encode('utf-8')) > 850" in patched
assert patched == module.patch(patched), "Patch must be idempotent"
try:
    module.patch(SOURCE.replace("command = protocol.command(event)", "pass"))
except ValueError:
    pass
else:
    raise AssertionError("Unexpected source must fail closed")
print("PASS: memory refresh patch validation, opt-in, idempotence and guards")
