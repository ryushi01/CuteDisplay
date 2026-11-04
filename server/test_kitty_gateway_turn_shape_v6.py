#!/usr/bin/env python3
"""No-source-leak tests for the read-only private gateway turn-shape probe."""
import io
from contextlib import redirect_stdout
import unittest
from unittest import mock
from kitty_gateway_turn_shape_v6 import MARKERS, shape, main


FAKE_SOURCE = '''
async def gateway():
    async def client_events():
        await upstream.send_json(event)
    async def upstream_events():
        await ws.send_json(event)
    async def kitty_speaker_sink(event):
        return None
    # KittySpeakerObserver
    # conversation.item.input_audio_transcription.completed
    # input_audio_buffer.speech_started
    # input_audio_buffer.speech_stopped
'''


class GatewayShapeTests(unittest.TestCase):
    def test_shape_has_only_allowlisted_fixed_outputs(self):
        result=shape(FAKE_SOURCE)
        self.assertEqual(result["source"],"readable")
        self.assertEqual(result["python_syntax"],"valid")
        self.assertEqual(result["function_client_events"],"once")
        self.assertEqual(result["function_upstream_events"],"once")
        self.assertEqual(result["provider_to_client_event_forward"],"once")
        self.assertEqual(result["trusted_turn_issuer"],"absent")
        self.assertEqual(result["safe_to_enable_owner_history"],"no")
        self.assertTrue(all(len(v)<=24 for v in result.values()))

    def test_missing_source_unknown_not_absent(self):
        result=shape(None)
        self.assertEqual(result["source"],"unavailable")
        self.assertEqual(result["python_syntax"],"unknown")
        self.assertTrue(all(result[k]=="unknown" for k in MARKERS))

    def test_private_source_and_credentials_never_print(self):
        fake=FAKE_SOURCE+"\n# private credential=SECRET_DO_NOT_PRINT\n"
        with mock.patch("kitty_gateway_turn_shape_v6.SOURCE") as path:
            path.read_text.return_value=fake
            buffer=io.StringIO()
            with redirect_stdout(buffer):
                main()
        self.assertNotIn("SECRET_DO_NOT_PRINT",buffer.getvalue())
        self.assertNotIn("private credential",buffer.getvalue())
        self.assertIn("KITTY_V6_GATEWAY_TURN_SHAPE_READ_ONLY",buffer.getvalue())


if __name__=="__main__":
    unittest.main()
