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
