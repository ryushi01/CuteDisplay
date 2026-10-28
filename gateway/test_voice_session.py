"""No-secret end-to-end simulated realtime provider test (loopback only)."""
import asyncio
import base64
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from websockets.asyncio.server import serve

sys.path.insert(0, str(Path(__file__).parent))
import cute_realtime_gateway as gateway


class SimulatedDevice:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.outgoing = asyncio.Queue()

    async def recv(self):
        return await self.incoming.get()

    async def send(self, message):
        await self.outgoing.put(message)


class TestVoiceSession(unittest.IsolatedAsyncioTestCase):
    async def test_mic_transcription_delegation_speaker(self):
        self.maxDiff = None
        captured = []
        pcm_in = b"\x01\x02" * 2400
        pcm_out = b"\x10\x20" * 2400
        expected_question = "Quel est le modèle de chat ?"

        async def realtime_provider(ws):
            await ws.send(json.dumps({"type": "session.created", "session": {"id": "x"}}))
            update = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            self.assertEqual(update["type"], "session.update")
            self.assertEqual(update["session"]["audio"]["input"]["format"]["rate"], 24000)
            self.assertEqual(update["session"]["tools"][0]["name"], "generate_chat_completion")
            await ws.send(json.dumps({"type": "session.updated"}))
            audio = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            self.assertEqual(audio["type"], "input_audio_buffer.append")
            self.assertEqual(base64.b64decode(audio["audio"]), pcm_in)
            await ws.send(json.dumps({"type": "input_audio_buffer.speech_started", "item_id": "u1"}))
            await ws.send(json.dumps({"type": "conversation.item.input_audio_transcription.completed",
                                       "item_id": "u1", "transcript": expected_question}))
            ask = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            self.assertEqual(ask["type"], "response.create")
            self.assertEqual(ask["response"]["metadata"]["input_item_id"], "u1")
            await ws.send(json.dumps({
                "type": "response.output_item.done", "response_id": "r1",
                "item": {"type": "function_call", "name": "generate_chat_completion",
                         "call_id": "tool1", "arguments": json.dumps({"request": expected_question})}
            }))
            await ws.send(json.dumps({"type": "response.done", "response": {"id": "r1", "status": "completed"}}))
            result = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            self.assertEqual(result["type"], "conversation.item.create")
            output = json.loads(result["item"]["output"])
            self.assertEqual(output["status"], "completed")
            self.assertEqual(output["answer"], "La réponse de Kitty.")
            response = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            self.assertEqual(response["type"], "response.create")
            await ws.send(json.dumps({
                "type": "response.output_audio.delta", "delta": base64.b64encode(pcm_out).decode(),
                "response_id": "r2", "item_id": "a1",
            }))
            await ws.send(json.dumps({"type": "response.done", "response": {"id": "r2", "status": "completed"}}))
            await asyncio.sleep(.1)

        async def fake_chat_model(settings, query, history):
            captured.append(query)
            return "La réponse de Kitty."

        async with serve(realtime_provider, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            settings = gateway.Settings({
                "device_id": "kitty-s3", "device_key": "a" * 64,
                "webui_url": "https://ai.example.net",
                "webui_api_key": "sk-" + "b" * 32,
                "webui_model": "cutedisplay-ai",
                "upstream_url": f"ws://127.0.0.1:{port}/v1/realtime?model=local",
                "voice": "kitty", "transcription_model": "whisper-1",
                "tls_cert": "/cert", "tls_key": "/key",
            })
            device = SimulatedDevice()
            async def launch():
                with patch.object(gateway, "chat_model", new=fake_chat_model):
                    return await gateway.voice_session(device, settings)
            task = asyncio.create_task(launch())
            try:
                ready = json.loads(await asyncio.wait_for(device.outgoing.get(), timeout=5))
                self.assertEqual(ready["type"], "session.ready")
                self.assertEqual(ready["sample_rate"], 24000)
                await device.incoming.put(pcm_in)
                received = bytearray()
                deadline = asyncio.get_running_loop().time() + 5
                while asyncio.get_running_loop().time() < deadline:
                    msg = await asyncio.wait_for(device.outgoing.get(), timeout=5)
                    if isinstance(msg, bytes):
                        received.extend(msg)
                        break
                self.assertEqual(bytes(received), pcm_out)
                self.assertEqual(captured, [expected_question])
            finally:
                await device.incoming.put(json.dumps({"type": "call.stop"}))
                await asyncio.wait_for(task, timeout=5)


if __name__ == "__main__":
    unittest.main()
