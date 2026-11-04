#!/usr/bin/env python3
"""Offline exact-patch and audio-forward preservation: zero live Docker writes."""
import asyncio
import json
import sys
import types
import unittest
from unittest import mock

from kitty_gateway_decode_hook_patch_v6 import patch, status, HookRefusal, MARK


GATEWAY = '''
import json
async def kitty_route(upstream, ws):
    async def client_events():
        pass
    async def provider_events():
        async for raw in upstream:
            try:
                event = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if event.get("type")=="response.output_audio.delta":
                await ws.send_json(event)
            else:
                await ws.send_json(event)
    await provider_events()
'''
# Above two forwarding paths are intentionally rejected. The live gateway
# read-only probe confirms ONE forwarding call inside provider_events.
GATEWAY = GATEWAY.replace(
    '''            if event.get("type")=="response.output_audio.delta":
                await ws.send_json(event)
            else:
                await ws.send_json(event)''',
    '            await ws.send_json(event)'
)
# Matches the actual diagnosed provider shape: an initial if/continue
# followed by event=upstream_message.json() and one browser forward.
WSMESSAGE_GATEWAY = '''
class WSMsgType:
    TEXT = "TEXT"
async def kitty_route(upstream, ws):
    async def client_events():
        pass
    async def provider_events():
        async for msg in upstream:
            if msg.type != WSMsgType.TEXT:
                continue
            event = msg.json()
            await ws.send_json(event)
    await provider_events()
'''

DIRECT = GATEWAY.replace(
    '''            try:
                event = json.loads(raw)
            except (TypeError, ValueError):
                continue''',
    '            event = json.loads(raw)'
)


class _Upstream:
    def __init__(self,events):
        self.messages=[json.dumps(ev) for ev in events]
    def __aiter__(self):
        self.items=iter(self.messages)
        return self
    async def __anext__(self):
        try:return next(self.items)
        except StopIteration:raise StopAsyncIteration


class _Socket:
    def __init__(self):self.events=[]
    async def send_json(self,event):
        self.events.append(event)


class _WSMessage:
    def __init__(self, obj, kind="TEXT"):
        self.type=kind
        self.obj=obj
    def json(self):
        return self.obj

class _WSUpstream:
    def __init__(self, messages):
        self.messages=messages
    def __aiter__(self):
        self.items=iter(self.messages)
        return self
    async def __anext__(self):
        try:
            return next(self.items)
        except StopIteration:
            raise StopAsyncIteration


class DecodeHookTests(unittest.IsolatedAsyncioTestCase):
    def test_live_wsmessage_if_guard_and_later_json_method_can_be_patched(self):
        self.assertEqual(status(WSMESSAGE_GATEWAY),"compatible")
        revised=patch(WSMESSAGE_GATEWAY)
        self.assertIn(MARK,revised)
        self.assertEqual(revised.count("await ws.send_json(event)"),1)
        self.assertEqual(revised.count("event = msg.json()"),1)
        self.assertEqual(revised.count("_kitty_v6_passive.from_provider(event)"),1)
        compile(revised,"<guarded-live-shape>","exec")

    async def test_realistic_wsmessage_audio_forwarding_identical(self):
        seen=[]
        class Passive:
            def from_provider(self,ev):
                seen.append(ev.copy())
        fake=types.ModuleType("kitty_passive_turn_bridge_v6")
        fake.KittyPassiveTurnBridge=Passive
        messages=[
            _WSMessage({"type":"response.output_audio.delta","delta":"a"}),
            _WSMessage({"type":"conversation.item.input_audio_transcription.completed",
                        "item_id":"voice-1","transcript":"Mochi Planet"}),
            _WSMessage({"type":"error","message":"closed"},"BINARY"),
            _WSMessage({"type":"response.output_audio.delta","delta":"b"}),
        ]
        expected=[m.obj for m in messages if m.type=="TEXT"]
        for source in (WSMESSAGE_GATEWAY,patch(WSMESSAGE_GATEWAY)):
            scope={}
            exec(compile(source,"<live-shape>","exec"),scope)
            socket=_Socket()
            with mock.patch.dict(sys.modules,
                                  {"kitty_passive_turn_bridge_v6":fake}):
                await scope["kitty_route"](_WSUpstream(messages),socket)
            self.assertEqual(socket.events,expected)
        self.assertEqual(seen,[expected[1]])

    def test_client_borne_json_and_nested_decode_remain_denied(self):
        for mutated in (
            WSMESSAGE_GATEWAY.replace("event = msg.json()",
                                      "event = browser_message.json()"),
            WSMESSAGE_GATEWAY.replace("event = msg.json()",
                                      "event = ws.json()"),
            WSMESSAGE_GATEWAY.replace("event = msg.json()",
                                      "event = msg.json()\\n            event = msg.json()"),
            WSMESSAGE_GATEWAY.replace("if msg.type != WSMsgType.TEXT:",
                                      "if (msg.type != WSMsgType.TEXT):\\n                event = msg.json()"),
            WSMESSAGE_GATEWAY.replace("await ws.send_json(event)",
                                      "await ws.send_json(event)\\n            await ws.send_json(event)"),
        ):
            with self.subTest(mutated=mutated[:80]):
                with self.assertRaises((HookRefusal,SyntaxError)):
                    patch(mutated)

    def test_patches_direct_or_try_decode_once(self):
        for source in (DIRECT,GATEWAY):
            self.assertEqual(status(source),"compatible")
            patched=patch(source)
            self.assertIn(MARK,patched)
            self.assertIn("await ws.send_json(event)",patched)
            self.assertIn("await ws.send_json(event)",source)
            self.assertEqual(patched.count("await ws.send_json(event)"),
                             source.count("await ws.send_json(event)"))
            compile(patched,"<gateway>","exec")
            with self.assertRaises(HookRefusal):
                patch(patched)

    async def test_audio_and_caption_events_remain_unmodified(self):
        sent=[]
        class Dummy:
            def __init__(self):self.calls=[]
            def from_provider(self,event):self.calls.append(event.copy())
        def ctor():
            inst=Dummy()
            sent.append(inst)
            return inst
        module=types.ModuleType("kitty_passive_turn_bridge_v6")
        module.KittyPassiveTurnBridge=ctor
        events=[
            {"type":"response.output_audio.delta","delta":"base64..."},
            {"type":"conversation.item.input_audio_transcription.completed",
             "item_id":"voice-1","transcript":"Kitty is listening."},
            {"type":"response.output_audio.delta","delta":"more..."},
            {"type":"response.done","response":{"status":"completed"}},
        ]
        for src in (GATEWAY,patch(GATEWAY)):
            socket=_Socket()
            scope={}
            exec(compile(src,"<gateway>","exec"),scope)
            with mock.patch.dict(sys.modules,
                    {"kitty_passive_turn_bridge_v6":module}):
                await scope["kitty_route"](_Upstream(events),socket)
            self.assertEqual(socket.events,events)
        self.assertEqual(len(sent),1)
        self.assertEqual(len(sent[0].calls),1)
        self.assertEqual(sent[0].calls[0],events[1])

    async def test_bridge_exception_does_not_change_audio(self):
        module=types.ModuleType("kitty_passive_turn_bridge_v6")
        class Broken:
            def from_provider(self,event):
                raise RuntimeError("offline expected")
        module.KittyPassiveTurnBridge=Broken
        scope={}
        exec(compile(patch(GATEWAY),"<gateway>","exec"),scope)
        events=[{"type":"conversation.item.input_audio_transcription.completed",
                  "item_id":"i1","transcript":"hello"},
                {"type":"response.output_audio.delta","delta":"pcm"}]
        socket=_Socket()
        with mock.patch.dict(sys.modules,{"kitty_passive_turn_bridge_v6":module}):
            await scope["kitty_route"](_Upstream(events),socket)
        self.assertEqual(socket.events,events)

    def test_refuses_ambiguous_or_client_borne_decodes(self):
        for source in (
            GATEWAY.replace("async for raw in upstream:",
                            "async for raw in client_socket:"),
            GATEWAY.replace("await ws.send_json(event)",
                            "await ws.send_json(event)\n"
                            "            await ws.send_json(event)"),
            GATEWAY.replace("event = json.loads(raw)",
                            "event = json.loads(browser_message)"),
            GATEWAY.replace("    async def client_events():\n        pass",
                            "    async def unrelated():\n        pass"),
            GATEWAY.replace("event = json.loads(raw)",
                            "event = json.loads(raw)\n"
                            "                event = json.loads(raw)"),
        ):
            with self.subTest(source=source[:32]):
                with self.assertRaises(HookRefusal):
                    patch(source)

    def test_no_private_context_or_auth_or_system_injection(self):
        patched=patch(GATEWAY)
        for risky in ("memory.semantic", "owner_grant","session.update",
                      "response.create","conversation.item.create",
                      "KITTY_MEMORY_TOKEN", "print(event)", "write_text("):
            self.assertNotIn(risky,patched)
        self.assertIn("from_provider(event)",patched)


if __name__=="__main__":
    unittest.main()
