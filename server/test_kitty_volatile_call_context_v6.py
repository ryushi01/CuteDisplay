#!/usr/bin/env python3
"""Offline proof: the new call working set is RAM-bounded and call-local."""
import unittest
from pathlib import Path
from kitty_volatile_call_context_v6 import VolatileCallContext
from kitty_gateway_call_ram_patch_v6 import patch, Refusal


def session(kind="session.created", instructions="Kitty's existing persona"):
    return {"type":kind, "session":{"instructions":instructions}}


def user(n, text):
    return {"type":"conversation.item.input_audio_transcription.completed",
            "item_id":"user_%03d" % n, "transcript":text}


def assistant(n, text):
    return {"type":"response.output_audio_transcript.done",
            "item_id":"assistant_%03d" % n, "transcript":text}


GATEWAY = '''
async def chat_route():
    async def client_events():
        await upstream.send_json({"type":"noop"})
    async def provider_events():
        # KITTY_V6_PROVIDER_DECODE_PASSIVE_HOOK
        _kitty_v6_passive = None
        try:
            from kitty_passive_turn_bridge_v6 import KittyPassiveTurnBridge
            _kitty_v6_passive = KittyPassiveTurnBridge()
        except ImportError:
            _kitty_v6_passive = None
        async for msg in upstream:
            event = msg.json()
            if (_kitty_v6_passive is not None and isinstance(event,dict)
                    and event.get("type") in ("error","conversation.item.input_audio_transcription.completed")):
                try:
                    _kitty_v6_passive.from_provider(event)
                except Exception:
                    _kitty_v6_passive = None
            await ws.send_json(event)
'''


class VolatileCallContextTests(unittest.TestCase):
    def test_no_persistence_mechanisms_or_global_transcript_cache(self):
        src=(Path(__file__).parent/"kitty_volatile_call_context_v6.py").read_text()
        for forbidden in ("import sqlite3", "import pathlib", "import logging",
                          "import tempfile", "open(", "write_text(",
                          "write_bytes(", "pickle.", "shelve.", "print("):
            self.assertNotIn(forbidden, src)
        self.assertIn("__slots__", src)

    def test_context_is_not_injected_until_enough_dialogue(self):
        c=VolatileCallContext()
        self.assertIsNone(c.on_provider_event(session()))
        self.assertIsNone(c.on_provider_event(user(1,"We decided to build a moon rover.")))
        self.assertIsNone(c.on_provider_event(assistant(1,"Let's design the wheels.")))
        update=c.on_provider_event(user(2,"The wheels must fit the ramp."))
        self.assertEqual(update["type"], "session.update")
        text=update["session"]["instructions"]
        self.assertTrue(text.startswith("Kitty's existing persona"))
        self.assertIn("moon rover",text)
        self.assertIn("Speaker identity is unverified",text)
        self.assertIn("not durable",text)

    def test_provider_ack_is_not_a_recursive_update(self):
        c=VolatileCallContext()
        c.on_provider_event(session())
        c.on_provider_event(user(1,"We decided to use red paint."))
        c.on_provider_event(assistant(1,"Noted for this call."))
        event=c.on_provider_event(user(2,"We need to finish the roof."))
        self.assertIsNotNone(event)
        self.assertIsNone(c.on_provider_event(session("session.updated",event["session"]["instructions"])))
        event2=c.on_provider_event(user(3,"The roof should fold."))
        self.assertIsNotNone(event2)
        self.assertEqual(event2["session"]["instructions"].count("[KITTY_CALL_RAM_V6_BEGIN]"),1)

    def test_isolated_calls_and_explicit_teardown(self):
        a=VolatileCallContext()
        b=VolatileCallContext()
        a.on_provider_event(session())
        b.on_provider_event(session())
        for event in (user(1,"We agreed to visit Mars."),
                      assistant(1,"Mars it is."),
                      user(2,"Let's take a camera.")):
            a.on_provider_event(event)
        self.assertEqual(b.buffered_turns,0)
        self.assertEqual(a.buffered_turns,3)
        a.close()
        self.assertEqual(a.buffered_turns,0)
        self.assertEqual(a.bytes_used,0)
        self.assertIsNone(a.on_provider_event(user(3,"Revive old notes.")))

    def test_bounded_growth_and_no_secret_replay(self):
        c=VolatileCallContext()
        c.on_provider_event(session())
        for n in range(200):
            result=c.on_provider_event(user(n,"We decided "+("Telescope " * 100)))
        self.assertLessEqual(c.buffered_turns,10)
        self.assertLess(c.bytes_used,2800)
        self.assertLess(len(result["session"]["instructions"].encode("utf-8")),27000)
        self.assertIsNone(c.on_provider_event(user(220,"My API key is alpha beta gamma")))

    def test_provider_error_disables_optional_feature_only(self):
        c=VolatileCallContext()
        c.on_provider_event(session())
        c.on_provider_event(user(1,"We decided A."))
        c.on_provider_event({"type":"error", "error":{"code":"unsupported_session_update"}})
        self.assertEqual(c.buffered_turns,0)
        self.assertIsNone(c.on_provider_event(session()))
        self.assertIsNone(c.on_provider_event(user(3,"We decided B.")))

    def test_no_identity_claim_is_accepted_as_authorization(self):
        c=VolatileCallContext()
        c.on_provider_event(session())
        for e in ({"type":"kitty.speaker.result","speaker_id":"person:owner",
                    "confidence":"verified"},
                  {"type":"conversation.item.input_audio_transcription.completed",
                   "item_id":"user_123","speaker_id":"person:owner",
                   "transcript":"my name is Shana"}):
            c.on_provider_event(e)
        self.assertEqual(c.buffered_turns,1)
        self.assertNotIn("person:owner", repr(c._recent))


class HookTests(unittest.TestCase):
    def test_only_provider_hook_is_extended_without_forward_changes(self):
        changed=patch(GATEWAY)
        compile(changed,"<fixture>","exec")
        self.assertEqual(changed.count("await ws.send_json(event)"),1)
        self.assertEqual(changed.count("await upstream.send_json(_kitty_v6_update)"),1)
        self.assertEqual(changed.count("_kitty_v6_passive.from_provider(event)"),1)
        self.assertIn("# KITTY_V6_CALL_RAM_ONLY_HOOK",changed)

    def test_idempotent_and_fail_closed(self):
        updated=patch(GATEWAY)
        with self.assertRaises(Refusal):
            patch(updated)
        with self.assertRaises(Refusal):
            patch("async def provider_events():\n    pass\n")


if __name__=="__main__":
    unittest.main()
