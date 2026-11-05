#!/usr/bin/env python3
"""No live gateway, SD or network in these source-only integration tests."""
import asyncio
import unittest

from kitty_gateway_response_bound_patch_v6 import patch, Refusal


FIXTURE = '''
async def realtime_gateway(upstream, ws):
    async def client_events():
        command = {
            "type": "response.create",
            "response": {"instructions": "Keep Kitty's existing persona.",
                         "modalities": ["audio"]}
        }
        # KITTY_SHARED_CONTEXT_PERSIST_RESPONSE_V6
        if command.get("type") == "response.create":
            old = command["response"]["instructions"]
            command["response"]["instructions"] = old + "\\nApproved shared SD note."
        # KITTY_XVECTOR_CONVERSATION_HINT_V6
        await upstream.send_json(command)

    async def provider_events():
        # KITTY_V6_PROVIDER_DECODE_PASSIVE_HOOK
        _kitty_v6_passive = None
        async for msg in upstream:
            event = msg.json()
            if _kitty_v6_passive is not None and isinstance(event, dict):
                try:
                    _kitty_v6_passive.from_provider(event)
                except Exception:
                    _kitty_v6_passive = None
            await ws.send_json(event)

    await provider_events()
    await client_events()
'''


class Message:
    def __init__(self, event):
        self.event = event

    def json(self):
        return self.event


class FakeUpstream:
    def __init__(self, events):
        self.events = events
        self.sent = []

    async def send_json(self, cmd):
        self.sent.append(cmd)

    def __aiter__(self):
        self.remaining = iter(self.events)
        return self

    async def __anext__(self):
        try:
            return Message(next(self.remaining))
        except StopIteration:
            raise StopAsyncIteration


class FakeWS:
    def __init__(self):
        self.forwarded = []

    async def send_json(self, event):
        self.forwarded.append(event)


class GatewayResponsePatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_existing_response_no_extra_provider_command(self):
        amended = patch(FIXTURE)
        scope = {}
        exec(compile(amended, "<source-only-test>", "exec"), scope)
        events = [
            {"type": "conversation.item.input_audio_transcription.completed",
             "item_id": "a1", "transcript": "We're planning Crystal Moon."},
            {"type": "conversation.item.input_audio_transcription.completed",
             "item_id": "a2", "transcript": "Three suns and purple oceans."},
        ]
        upstream, ws = FakeUpstream(events), FakeWS()
        await scope["realtime_gateway"](upstream, ws)
        self.assertEqual(len(upstream.sent), 1)
        self.assertEqual(upstream.sent[0]["type"], "response.create")
        self.assertEqual(len(ws.forwarded), 2)
        self.assertEqual(ws.forwarded, events)
        sent = upstream.sent[0]["response"]["instructions"]
        self.assertIn("Keep Kitty's existing persona.", sent)
        self.assertIn("Approved shared SD note.", sent)
        self.assertIn("Crystal Moon", sent)
        self.assertIn("Three suns", sent)

    async def test_optional_hook_does_not_need_existing_provider_session(self):
        amended = patch(FIXTURE)
        scope = {}
        exec(compile(amended, "<source-only-test>", "exec"), scope)
        upstream, ws = FakeUpstream([{"type": "session.created", "session": {}}]), FakeWS()
        await scope["realtime_gateway"](upstream, ws)
        self.assertEqual(len(upstream.sent), 1)
        self.assertNotIn("KITTY_VOLATILE_CALL_REFERENCES_V6",
                         upstream.sent[0]["response"]["instructions"])

    async def test_fail_closed_on_unrecognized_structure_and_old_failed_hook(self):
        for altered in (
            FIXTURE.replace("KITTY_SHARED_CONTEXT_PERSIST_RESPONSE_V6", "OTHER_MARKER"),
            FIXTURE.replace("KITTY_XVECTOR_CONVERSATION_HINT_V6", "OTHER_MARKER"),
            FIXTURE.replace("_kitty_v6_passive.from_provider(event)", "unknown(event)"),
            FIXTURE.replace("await ws.send_json(event)", "await ws.send_json(rogue)"),
            FIXTURE.replace("await upstream.send_json(command)", "pass"),
            FIXTURE + "\n# KITTY_V6_CALL_RAM_ONLY_HOOK\n",
        ):
            with self.assertRaises(Refusal):
                patch(altered)

    async def test_cannot_patch_twice(self):
        with self.assertRaises(Refusal):
            patch(patch(FIXTURE))

    async def test_no_unauthorized_memory_grants_or_extra_websocket_sends(self):
        amended = patch(FIXTURE)
        self.assertEqual(amended.count("await upstream.send_json("),
                         FIXTURE.count("await upstream.send_json("))
        self.assertEqual(amended.count("await ws.send_json(event)"), 1)
        self.assertNotIn("await upstream.send_json(_kitty_", amended)
        self.assertNotIn("owner_grant", amended)
        self.assertNotIn("conversation.item.create", amended)
        self.assertNotIn('"type": "session.update"', amended)
        self.assertEqual(amended.count("KITTY_V6_RESPONSE_BOUND_CALL_CONTEXT_V6"), 1)


if __name__ == "__main__":
    unittest.main()
