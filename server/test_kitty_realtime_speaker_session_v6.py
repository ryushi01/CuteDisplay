"""No-network checks for item-bound Kitty V6 speaker recognition."""
import asyncio
import base64
import unittest
from kitty_realtime_speaker_session_v6 import SpeakerSession


class SpeakerSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_matching_upstream_turn_emits(self):
        sent = []
        async def fake(url, token, item, pcm, timeout):
            self.assertEqual(len(pcm), 16000)
            return {"type":"kitty.speaker.result", "item_id":item,
                    "speaker_id":"person:test", "confidence":"probable"}
        async def emit(value):
            sent.append(value)
        session = SpeakerSession(identify=fake)
        session.speech_started()
        session.microphone_chunk(base64.b64encode(b"\x01\x00"*8000).decode())
        session.speech_stopped(item_id="item-1")
        self.assertTrue(session.schedule("item-1", "unix:///run/kitty-semantic/memory.sock",
                                         "token", emit))
        await asyncio.sleep(0.02)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["item_id"], "item-1")

    async def test_preroll_is_retained_and_bounded(self):
        session = SpeakerSession()
        # Feed 400ms microphone audio before upstream VAD speech_started.
        pre = base64.b64encode(b"\x01\x00" * 9600).decode()
        session.microphone_chunk(pre)
        session.speech_started()
        session.speech_stopped(item_id="item-1")
        captured = session.transcription("item-1")
        self.assertIsNotNone(captured)
        self.assertEqual(len(captured[2]), 19200)
        session.close()

    async def test_mismatch_rejected(self):
        session = SpeakerSession()
        session.speech_started()
        session.speech_stopped(item_id="item-1")
        self.assertIsNone(session.transcription("item-2"))

    async def test_new_speech_cancels_late_response(self):
        sent = []
        async def slow(url, token, item, pcm, timeout):
            await asyncio.sleep(0.03)
            return {"item_id":item, "speaker_id":"person:test"}
        async def emit(v):
            sent.append(v)
        session = SpeakerSession(identify=slow)
        session.speech_started()
        session.speech_stopped(item_id="item-1")
        self.assertTrue(session.schedule("item-1", "url", "token", emit))
        session.speech_started()
        await asyncio.sleep(0.05)
        self.assertEqual(sent, [])

    async def test_closed_session_never_emits(self):
        session = SpeakerSession()
        session.speech_started()
        session.speech_stopped(item_id="item-1")
        session.close()
        self.assertIsNone(session.transcription("item-1"))


if __name__ == "__main__":
    unittest.main()
