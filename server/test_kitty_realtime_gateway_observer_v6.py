"""Offline gateway observer tests; does not open sockets or change live audio."""
import asyncio
import base64
import unittest
from kitty_realtime_gateway_observer_v6 import KittySpeakerObserver
from kitty_realtime_speaker_session_v6 import SpeakerSession

class ObserverTests(unittest.IsolatedAsyncioTestCase):
    async def test_matching_event_can_emit(self):
        emitted=[]
        async def identify(url, token, item, pcm, timeout):
            return {"type":"kitty.speaker.result","item_id":item,
                    "speaker_id":"person:tester","confidence":"probable"}
        async def send(ev):
            emitted.append(ev)
        obj=KittySpeakerObserver(send,session=SpeakerSession(identify=identify),
                                  enabled=True,url="unix:///run/kitty-semantic/memory.sock",token="test")
        obj.observe_client({"type":"input_audio_buffer.append",
                            "audio":base64.b64encode(b"\x01\x00"*5000).decode()})
        obj.observe_upstream({"type":"input_audio_buffer.speech_started"})
        obj.observe_upstream({"type":"input_audio_buffer.speech_stopped","item_id":"a1"})
        obj.observe_upstream({"type":"conversation.item.input_audio_transcription.completed","item_id":"a1"})
        await asyncio.sleep(0.02)
        self.assertEqual(len(emitted),1)
        self.assertEqual(emitted[0]["speaker_id"],"person:tester")
        obj.close()

    async def test_wrong_turn_never_emits(self):
        emitted=[]
        async def send(ev): emitted.append(ev)
        obj=KittySpeakerObserver(send,enabled=True,token="test")
        obj.observe_upstream({"type":"input_audio_buffer.speech_started"})
        obj.observe_upstream({"type":"input_audio_buffer.speech_stopped","item_id":"a1"})
        obj.observe_upstream({"type":"conversation.item.input_audio_transcription.completed","item_id":"a2"})
        await asyncio.sleep(0)
        self.assertEqual(emitted,[])
        obj.close()

    async def test_cancel_preserves_injected_recognizer(self):
        calls = []
        emitted = []
        async def fake(url, token, item, pcm, timeout):
            calls.append(item)
            return {"type":"kitty.speaker.result", "item_id":item,
                    "speaker_id":"person:tester", "confidence":"probable"}
        async def send(event):
            emitted.append(event)
        obj = KittySpeakerObserver(send, session=SpeakerSession(identify=fake),
                                   enabled=True, url="unix:///run/kitty-semantic/memory.sock",
                                   token="test")
        obj.observe_client({"type":"response.cancel"})
        obj.observe_upstream({"type":"input_audio_buffer.speech_started"})
        obj.observe_upstream({"type":"input_audio_buffer.speech_stopped", "item_id":"a2"})
        obj.observe_upstream({"type":"conversation.item.input_audio_transcription.completed", "item_id":"a2"})
        await asyncio.sleep(0.02)
        self.assertEqual(calls, ["a2"])
        self.assertEqual(len(emitted), 1)
        obj.close()

    async def test_server_observed_turn_only_and_one_shot_recall(self):
        async def send(event):
            return None
        obj = KittySpeakerObserver(send, enabled=True, token="test")
        epoch = obj.gate.begin("item_123")
        obj.epoch = epoch
        obj.gate.accept_speaker(epoch, "item_123", "person:camille", "probable")
        self.assertIsNone(obj.authorized_recall("item_123", "person:camille", "explicit_introduction"))
        self.assertIsNone(obj.authorized_recall("other", "person:camille", "voice_probable"))
        self.assertIsNone(obj.authorized_recall("item_123", "person:aki", "voice_probable"))
        token = obj.authorized_recall("item_123", "person:camille", "voice_probable")
        self.assertEqual(token, epoch)
        self.assertEqual(obj.complete_recall(token, "item_123", "person:camille", "private context"), "private context")
        self.assertEqual(obj.complete_recall(token, "item_123", "person:camille", "duplicate"), "")
        obj.gate.invalidate()
        self.assertIsNone(obj.authorized_recall("item_123", "person:camille", "voice_probable"))
        obj.close()

    async def test_cancelled_turn_rejects_late_recall_result(self):
        async def send(event):
            return None
        observer = KittySpeakerObserver(send, enabled=True, token="test")
        epoch = observer.gate.begin("turn_one")
        observer.epoch = epoch
        self.assertTrue(observer.gate.accept_speaker(
            epoch, "turn_one", "person:camille", "probable"))
        self.assertEqual(observer.authorized_recall(
            "turn_one", "person:camille", "voice_probable"), epoch)
        # A new utterance begins while the CPU HTTP request is outstanding.
        observer.observe_upstream({"type": "input_audio_buffer.speech_started"})
        self.assertEqual(observer.complete_recall(
            epoch, "turn_one", "person:camille", "late private data"), "")
        observer.close()

    async def test_disabled_by_default(self):
        emitted=[]
        async def send(ev): emitted.append(ev)
        obj=KittySpeakerObserver(send)
        obj.observe_upstream({"type":"input_audio_buffer.speech_started"})
        obj.observe_upstream({"type":"input_audio_buffer.speech_stopped","item_id":"a1"})
        self.assertEqual(obj.pending_stopped_item,None)
        obj.close()

if __name__=="__main__":
    unittest.main()
