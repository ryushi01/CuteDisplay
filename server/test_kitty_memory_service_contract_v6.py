"""HTTP contract for shared Kitty text/realtime semantic context.

Runs in-process with a disposable test cache. No S3, Docker, or real listener.
"""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import kitty_memory_service as service


class FakeRequest:
    def __init__(self, path, payload, token="test-token"):
        self.path = path
        self.headers = {
            "Authorization": "Bearer " + token,
            "Content-Length": str(len(json.dumps(payload).encode())),
        }
        self.rfile = io.BytesIO(json.dumps(payload).encode())
        self.response = None

    def _reply(self, status, obj):
        self.response = (status, obj)


class ServiceContextContract(unittest.TestCase):
    def request(self, path, payload, *, token="test-token"):
        req = FakeRequest(path, payload, token)
        with patch.object(service, "TOKEN", "test-token"):
            service.Handler.do_POST(req)
        return req.response

    def test_unknown_speaker_refused_before_search(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp) / "derived.db"
            cache.touch()
            with patch.dict(os.environ, {"KITTY_SEMANTIC_DB": str(cache)}):
                status, body = self.request(
                    "/semantic/context", {"query": "hello", "speaker_id": "unknown"})
            self.assertEqual(status, 400)
            self.assertEqual(body["error"], "speaker_identity_required")

    def test_context_calls_shared_formatter(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp) / "derived.db"
            cache.touch()
            with patch.dict(os.environ, {"KITTY_SEMANTIC_DB": str(cache)}):
                with patch("kitty_memory_context_v6.recall_context",
                           return_value="attributed context") as recalled:
                    status, body = self.request("/semantic/context", {
                        "query": "Bonjour", "speaker_id": "person:camille"})
            self.assertEqual(status, 200)
            self.assertEqual(body, {"context": "attributed context"})
            recalled.assert_called_once_with(
                str(cache), "Bonjour", "person:camille")

    def test_legacy_personal_writes_disabled_by_default(self):
        with patch.dict(os.environ, {"KITTY_LEGACY_MEMORY_DB_ENABLED": "0"}):
            for route in ("/turn", "/remember", "/forget", "/recall"):
                status, body = self.request(route, {"query": "test"})
                self.assertEqual(status, 410)
                self.assertEqual(body["error"], "legacy_ubuntu_memory_disabled")

    def test_unauthorized_request_cannot_get_context(self):
        status, body = self.request("/semantic/context", {
            "query": "secret", "speaker_id": "person:camille"}, token="wrong")
        self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()
