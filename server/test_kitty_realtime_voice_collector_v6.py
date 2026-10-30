#!/usr/bin/env python3
"""Offline gateway frame-to-speaker test; not a live Open WebUI integration test."""
import asyncio
import base64
import unittest
from unittest.mock import patch
from kitty_realtime_voice_v6 import UtteranceCollector, recognize_turn
from patch_openwebui_voice_v6 import patch as patch_gateway

SOURCE = """
async def handler(auth, ws, protocol):
    if True:
        kitty_expressions = auth.get('kitty_expressions') is True
        kitty_sd_memory = auth.get('kitty_sd_memory', '')
        async def client_events():
            while True:
                event = {}
                command = protocol.command(event)
                break
        async def upstream_events():
            event = {}
            await ws.send_json(event)
"""

class CollectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_speech_audio_bounded_and_matched_turn(self):
        c=UtteranceCollector()
        audio=b"\x01\x00"*(24000*2)
        c.add(base64.b64encode(audio).decode())
        c.speech_started()
        c.speech_stopped()
        got=[]
        async def emit(v):got.append(v)
        with patch("kitty_realtime_voice_v6.recognize_completed_utterance",
                   return_value={"speaker_id":"person:shana","confidence":"probable"}):
            await recognize_turn(c,"item-42",emit)
        self.assertEqual(got[0]["item_id"],"item-42")
        self.assertEqual(got[0]["speaker_id"],"person:shana")
        self.assertEqual(got[0]["confidence"],"probable")
        self.assertIsNone(c.pop_for_transcript())
    async def test_audio_unavailable_does_not_fake_identity(self):
        c=UtteranceCollector()
        got=[]
        async def emit(v):got.append(v)
        await recognize_turn(c,"item-42",emit)
        self.assertEqual(got[0]["speaker_id"],"unknown")
        self.assertEqual(got[0]["confidence"],"unknown")
    async def test_truncates_audio_ring(self):
        c=UtteranceCollector()
        c.add(base64.b64encode(b"\x01\x00"*20000).decode())
        c.add(base64.b64encode(b"\x01\x00"*20000).decode())
        self.assertTrue(c.size<=24000*2*12)

class GatewayPatchTests(unittest.TestCase):
    def test_explicit_opt_in_and_compile(self):
        result=patch_gateway(SOURCE)
        self.assertIn("kitty_voice_v6_enabled",result)
        self.assertEqual(patch_gateway(result),result)
        self.assertIn("kitty.speaker.result",open("server/kitty_realtime_voice_v6.py").read())
    def test_version_mismatch_fails_closed(self):
        with self.assertRaises(ValueError):
            patch_gateway("async def no_gateway(): pass")
if __name__=="__main__":
    unittest.main()
