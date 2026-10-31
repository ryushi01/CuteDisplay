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
