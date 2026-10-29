"""Credential/transport boundary regression tests (no network, mic or tokens)."""
import asyncio
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from cute_realtime_gateway import (
    GatewayError, Settings, authenticate_device, device_proof, validate_url,
)


class DummyWS:
    def __init__(self, key, *, bad=False):
        self.key = key
        self.bad = bad
        self.sent = []

    async def send(self, message):
        self.sent.append(json.loads(message))

    async def recv(self):
        challenge = self.sent[-1]
        proof = device_proof(self.key, "kitty-s3", challenge["nonce"])
        if self.bad:
            proof = "0" * 64
        return json.dumps({"type": "auth", "device_id": "kitty-s3", "proof": proof})


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.base = {
            "device_id": "kitty-s3",
            "device_key": "a" * 64,
            "webui_url": "https://ai.example.org",
            "webui_api_key": "sk-" + "b" * 32,
            "webui_model": "cutedisplay-ai",
            "upstream_url": "ws://127.0.0.1:8765/v1/realtime?model=local",
            "upstream_key": "local",
            "voice": "kitty",
            "transcription_model": "whisper-1",
            "tls_cert": "/private/cert.pem",
            "tls_key": "/private/key.pem",
        }

    def test_valid_config_and_loopback_provider(self):
        self.assertEqual(Settings(self.base).webui_model, "cutedisplay-ai")

    def test_plaintext_remote_provider_rejected(self):
        self.base["upstream_url"] = "ws://other-machine.example:8765/v1/realtime?model=local"
        with self.assertRaises(GatewayError):
            Settings(self.base)

    def test_http_webui_rejected(self):
        self.base["webui_url"] = "http://ai.example.org"
        with self.assertRaises(GatewayError):
            Settings(self.base)

    def test_short_device_key_rejected(self):
        self.base["device_key"] = "1234"
        with self.assertRaises(GatewayError):
            Settings(self.base)

    def test_password_is_not_a_service_key(self):
        self.base["webui_api_key"] = "mypassword"
        with self.assertRaises(GatewayError):
            Settings(self.base)

    def test_valid_proof_is_bound_to_nonce_and_device(self):
        a = device_proof(self.base["device_key"], "kitty-s3", "a" * 48)
        b = device_proof(self.base["device_key"], "kitty-s3", "b" * 48)
        self.assertNotEqual(a, b)
        self.assertEqual(len(a), 64)


class HandshakeTests(unittest.IsolatedAsyncioTestCase):
    async def test_device_proof(self):
        settings = ConfigTests().base if False else {
            "device_id": "kitty-s3", "device_key": "a" * 64,
            "webui_url": "https://ai.example.org",
            "webui_api_key": "sk-" + "b" * 32,
            "webui_model": "cutedisplay-ai",
            "upstream_url": "ws://localhost:8765/v1/realtime?model=local",
            "voice": "kitty", "transcription_model": "whisper-1",
            "tls_cert": "/cert", "tls_key": "/key",
        }
        ws = DummyWS(settings["device_key"])
        await authenticate_device(ws, Settings(settings))
        self.assertEqual(ws.sent[-1]["type"], "auth.ok")
        self.assertEqual(ws.sent[-1]["sample_rate"], 24000)

    async def test_bad_proof_rejected(self):
        params = {
            "device_id": "kitty-s3", "device_key": "a" * 64,
            "webui_url": "https://ai.example.org",
            "webui_api_key": "sk-" + "b" * 32,
            "upstream_url": "ws://localhost:8765/v1/realtime?model=local",
            "voice": "kitty", "transcription_model": "whisper-1",
            "tls_cert": "/cert", "tls_key": "/key",
        }
        ws = DummyWS(params["device_key"], bad=True)
        with self.assertRaises(GatewayError):
            await authenticate_device(ws, Settings(params))
        self.assertEqual(len(ws.sent), 1)


if __name__ == "__main__":
    unittest.main()
