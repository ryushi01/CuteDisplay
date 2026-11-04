#!/usr/bin/env python3
"""Preflight prints only closed labels, and identifies actual guard assumptions."""
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
import kitty_gateway_decode_preflight_v6 as pre

BASE = '''
import json
async def gateway(upstream,ws):
    async def client_events():
        pass
    async def provider_events():
        async for msg in upstream:
            try:
                event = json.loads(msg)
            except ValueError:
                continue
            await ws.send_json(event)
'''

class GuardDiagnosticTests(unittest.TestCase):
    def test_supported_first_try_decode_diagnostic(self):
        result=pre.analyze(BASE)
        self.assertEqual(result["source_python"],"valid")
        self.assertEqual(result["provider_loop"],"one")
        self.assertEqual(result["event_decoder"],"loads")
        self.assertEqual(result["event_decoder_input"],"upstream_loop_item")
        self.assertEqual(result["event_decoder_position"],"first_try")
        self.assertEqual(result["exact_patch_refusal"],
                         "post_decode_layout_or_compilation")

    def test_common_websocket_data_attribute_detected_safely(self):
        source=BASE.replace("json.loads(msg)", "json.loads(msg.data)")
        result=pre.analyze(source)
        self.assertEqual(result["event_decoder_input"],"upstream_item_attribute")
        self.assertEqual(result["exact_patch_refusal"],"provider_decode_unrecognized")

    def test_if_gate_before_decode_detected_without_source_leak(self):
        source=BASE.replace(
            "            try:",
            "            if msg.type == 1:\n                try:"
        ).replace(
            "                event = json.loads(msg)",
            "                    event = json.loads(msg)"
        ).replace(
            "            except ValueError:\n                continue",
            "                except ValueError:\n                    continue"
        )
        result=pre.analyze(source)
        self.assertEqual(result["event_decoder_input"],"upstream_loop_item")
        self.assertEqual(result["event_decoder_position"],"nested_control")
        self.assertEqual(result["exact_patch_refusal"],"provider_decode_unrecognized")

    def test_unrelated_name_or_missing_client_is_rejected(self):
        s=BASE.replace("json.loads(msg)","json.loads(inbound_browser)")
        self.assertEqual(pre.analyze(s)["event_decoder_input"],"other_name")
        s=BASE.replace("    async def client_events():","    async def unrelated():")
        self.assertEqual(pre.analyze(s)["exact_patch_refusal"],
                         "provider_scope_unrecognized")

    def test_no_private_source_or_secrets_in_printed_output(self):
        secret="SUPER_PRIVATE_SEMANTIC_TOKEN_NEVER_LOG"
        source=BASE+"\n# "+secret+"\n"
        with patch.object(pre,"GATEWAY") as path:
            path.read_text.return_value=source
            output=io.StringIO()
            with redirect_stdout(output):
                pre.main()
        self.assertIn("KITTY_V6_PROVIDER_DECODE_PREFLIGHT_READ_ONLY",
                      output.getvalue())
        self.assertNotIn(secret,output.getvalue())
        self.assertNotIn("async def",output.getvalue())
        self.assertNotIn("realtime.py",output.getvalue())


if __name__=="__main__":
    unittest.main()
