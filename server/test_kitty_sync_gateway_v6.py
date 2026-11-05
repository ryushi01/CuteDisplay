#!/usr/bin/env python3
"""Offline boundaries for the device-facing sync proxy (no sockets opened)."""
import io
import json
import unittest
from unittest.mock import patch
import kitty_sync_gateway_v6 as gateway


class FakeHeaders(dict):
    def get(self, key, default=""):
        return super().get(key, default)


def call(path, body, auth="Bearer device-" + "a" * 40, method="POST", content_type="application/json"):
    handler = gateway.Handler.__new__(gateway.Handler)
    handler.path = path
    handler.headers = FakeHeaders({
        "Authorization": auth,
        "Content-Length": str(len(body)),
        "Content-Type": content_type,
    })
    handler.rfile = io.BytesIO(body)
    handler.close_connection = False
    recorded = []
    handler.reply = lambda code, obj: recorded.append((code, obj))
    if method == "POST":
        handler.do_POST()
    else:
        handler.do_GET()
    return recorded


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.config = patch.multiple(gateway, DEVICE_TOKEN="device-" + "a" * 40,
                                     MEMORY_TOKEN="memory-" + "b" * 40)
        self.config.start()
        self.addCleanup(self.config.stop)

    def test_only_snapshot_routes_allowed(self):
        for path in ("/identify", "/remember", "/owner/verify", "/snapshot/finalize/extra"):
            self.assertEqual(call(path, b"{}")[0][0], 404)

    def test_authentication_required(self):
        self.assertEqual(call("/snapshot/chunk", b"{}", auth="")[0][0], 401)

    def test_json_required(self):
        self.assertEqual(call("/snapshot/chunk", b"not-json")[0][0], 400)
        self.assertEqual(call("/snapshot/chunk", b"{}", content_type="text/plain")[0][0], 415)

    def test_body_limit(self):
        self.assertEqual(call("/snapshot/chunk", b"x" * 16385)[0][0], 413)

    def test_healthy_without_exposing_data(self):
        self.assertEqual(call("/health", b"", method="GET")[0], (200, {"ok": True}))
        self.assertEqual(call("/secret", b"", method="GET")[0][0], 404)

    def test_durable_ack_timeout_budget(self):
        self.assertEqual(gateway.UPSTREAM_TIMEOUT_SECONDS, 9)
        self.assertGreater(gateway.UPSTREAM_TIMEOUT_SECONDS, 8)
        self.assertLess(gateway.UPSTREAM_TIMEOUT_SECONDS, 12)
        from pathlib import Path
        source = Path(gateway.__file__).read_text()
        self.assertIn("timeout=UPSTREAM_TIMEOUT_SECONDS", source)
        firmware = Path(__file__).resolve().parents[1] / "firmware/CuteDisplayBrain/KittyMemorySyncV6.h"
        self.assertIn("http.setTimeout(12000)", firmware.read_text())

    def test_fails_closed_on_same_token(self):
        with patch.object(gateway, "MEMORY_TOKEN", gateway.DEVICE_TOKEN):
            self.assertEqual(call("/snapshot/chunk", b"{}")[0][0], 401)


if __name__ == "__main__":
    unittest.main()
