#!/usr/bin/env python3
"""Status-only private gateway scope probe never prints gateway source."""
import io
from contextlib import redirect_stdout
from unittest import TestCase, main
from unittest.mock import patch

from kitty_gateway_provider_scope_v6 import analyze, main as cli

SUPPORTED = """
async def route():
    async def client_events():
        event = await ws.receive_json()
        await upstream.send_json(event)
    async def provider_pipe():
        event = await upstream.recv()
        if event.get("type") == "conversation.item.input_audio_transcription.completed":
            pass
        await ws.send_json(event)
"""

# The live gateway may legitimately separate its transcription handlers
# from the upstream receive/forward loop. This remains observable by AST.
SPLIT_PROVIDER = """
async def route():
    async def client_events():
        event = await ws.receive_json()
        await upstream.send_json(event)
    async def provider_events():
        async for raw in upstream:
            event = JSONCodec.loads(raw)
            if event.get("type") == "response.output_audio.delta":
                await ws.send_json(event)
            await ws.send_json(event)
    async def emit_transcript():
        if event.get("type") == "conversation.item.input_audio_transcription.completed":
            pass
"""

AMBIGUOUS = SUPPORTED.replace(
    "        await ws.send_json(event)\n",
    "        await ws.send_json(event)\n        await ws.send_json(event)\n",
)


class ScopeTests(TestCase):
    def test_unique_provider_scope_with_upstream_origin(self):
        result=analyze(SUPPORTED)
        self.assertEqual(result["passive_hook_safe"],"yes")
        self.assertEqual(result["provider_transcript_scope"],"one")
        self.assertEqual(result["live_owner_history_enable"],"no")
        self.assertEqual(result["all_ws_event_forwards"],"one")

    def test_missing_origin_or_multiple_forwards_are_not_safe(self):
        self.assertEqual(analyze(AMBIGUOUS)["passive_hook_safe"],"no")
        self.assertEqual(analyze(SUPPORTED.replace("await upstream.recv()",
                "event_from_browser"))["passive_hook_safe"],"no")
        self.assertEqual(analyze("broken !")["syntax"],"invalid")
        self.assertEqual(analyze(None)["source"],"unavailable")

    def test_split_provider_decode_hook_is_diagnostic_only(self):
        result=analyze(SPLIT_PROVIDER)
        self.assertEqual(result["named_provider_handler"],"one")
        self.assertEqual(result["provider_receive_shape"],"async_for_upstream")
        self.assertEqual(result["provider_receive_modes"],"one")
        self.assertEqual(result["provider_json_event_decodes"],"one")
        self.assertEqual(result["provider_ws_event_forwards"],"multiple")
        self.assertEqual(result["provider_transcript_literal"],"absent")
        self.assertEqual(result["event_decode_hook_candidate"],"yes")
        # The old broad 'send' hook remains unsafe.
        self.assertEqual(result["passive_hook_safe"],"no")
        self.assertEqual(result["live_owner_history_enable"],"no")

    def test_unknown_event_decode_source_does_not_make_candidate(self):
        bad=SPLIT_PROVIDER.replace("async for raw in upstream:",
                                    "async for raw in websocket:")
        result=analyze(bad)
        self.assertEqual(result["provider_receive_shape"],"unrecognized")
        self.assertEqual(result["event_decode_hook_candidate"],"no")

    def test_no_private_source_or_secret_in_output(self):
        secret="MY_LONG_PRIVATE_SECRET_NEVER_PRINT"
        source=SUPPORTED+"\n# "+secret+"\n"
        with patch("kitty_gateway_provider_scope_v6.REALTIME") as p:
            p.read_text.return_value=source
            sink=io.StringIO()
            with redirect_stdout(sink):
                cli()
        output=sink.getvalue()
        self.assertNotIn(secret,output)
        self.assertNotIn("async def",output)
        self.assertIn("KITTY_V6_PROVIDER_SCOPE_READ_ONLY",output)
        self.assertIn("live_owner_history_enable=no",output)


if __name__=="__main__":
    main()
