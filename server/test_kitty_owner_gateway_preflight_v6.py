#!/usr/bin/env python3
"""No-leak, no-deploy private realtime gateway AST readiness probe tests."""
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import kitty_owner_gateway_preflight_v6 as pre


SAMPLE = """
import json
async def route(ws, upstream):
    async def client_events():
        event = await ws.receive_json()
        await upstream.send_json(event)
    async def provider_events():
        async for msg in upstream:
            event = json.loads(msg)
            await ws.send_json(event)
"""


class OwnerReadinessTests(unittest.TestCase):
    def test_identifies_provenance_candidates_but_never_enables_private_recall(self):
        result=pre.analyze(SAMPLE)
        self.assertEqual(result["source"],"readable")
        self.assertEqual(result["syntax"],"valid")
        self.assertEqual(result["client_handler"],"one")
        self.assertEqual(result["provider_handler"],"one")
        self.assertEqual(result["common_route_scope"],"candidate")
        self.assertEqual(result["provider_decode_scope"],"candidate")
        self.assertEqual(result["s3_device_receive_scope"],"candidate")
        for key in ("authenticated_s3_device",
                    "provider_to_s3_item_binding",
                    "trusted_s3_microphone_capture",
                    "owner_model_calibrated",
                    "receipt_sd_write_confirmed"):
            self.assertEqual(result[key],"not_verified")
        self.assertEqual(result["live_owner_private_recall"],"no")
        self.assertEqual(result["deployment_ready"],"no")

    def test_refuses_client_origin_upstream_alias_and_duplicate_provider(self):
        spoof=SAMPLE.replace("async for msg in upstream:",
                              "async for msg in ws:")
        self.assertEqual(
            pre.analyze(spoof)["provider_decode_scope"],"not_verified")
        spoof=SAMPLE.replace("event = json.loads(msg)",
                             "event = json.loads(browser_message)")
        self.assertEqual(
            pre.analyze(spoof)["provider_decode_scope"],"not_verified")
        dup=SAMPLE+"\nasync def provider_events():\n    pass\n"
        self.assertEqual(pre.analyze(dup)["provider_handler"],"multiple")
        self.assertEqual(pre.analyze(dup)["deployment_ready"],"no")
        wrong=SAMPLE.replace("await ws.receive_json()",
                             "await upstream.receive_json()")
        self.assertEqual(pre.analyze(wrong)["s3_device_receive_scope"],
                         "not_verified")

    def test_unrelated_handlers_not_same_socket_scope_are_rejected(self):
        source=SAMPLE.replace(
            "    async def provider_events():",
            "    async def other():\n        async def provider_events():")
        self.assertEqual(pre.analyze(source)["common_route_scope"],
                         "not_verified")
        self.assertEqual(pre.analyze(None)["source"],"unavailable")
        self.assertEqual(pre.analyze("broken!")["syntax"],"invalid")

    def test_no_private_source_credential_or_source_path_is_printed(self):
        secret="NEVER_SHOW_PRIVATE_PASSWORD_CONTENT_ABC"
        with patch.object(pre,"LIVE") as reader:
            reader.read_text.return_value=SAMPLE+"\n# "+secret
            output=io.StringIO()
            with redirect_stdout(output):
                pre.main()
        text=output.getvalue()
        self.assertNotIn(secret,text)
        self.assertNotIn("async def",text)
        self.assertNotIn("realtime.py",text)
        self.assertNotIn("ws.receive_json",text)
        self.assertIn("KITTY_V6_OWNER_GATEWAY_READ_ONLY",text)
        self.assertIn("deployment_ready=no",text)


if __name__=="__main__":
    unittest.main()
