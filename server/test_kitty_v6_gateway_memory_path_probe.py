#!/usr/bin/env python3
"""No-source-leak tests for live gateway memory path diagnostic."""
from contextlib import redirect_stdout
from io import StringIO
from unittest import TestCase, main, mock
from kitty_v6_gateway_memory_path_probe import MARKERS, main as probe_main, probe

SOURCE = '''
async def route():
    # KITTY_APPROVED_SHARED_INITIAL_CONTEXT_V6
    # KITTY_SHARED_CONTEXT_PERSIST_SESSION_V6
    # KITTY_SHARED_CONTEXT_PERSIST_RESPONSE_V6
    # KITTY_V6_PROVIDER_DECODE_PASSIVE_HOOK
    # KittySpeakerObserver
    # kitty.memory.refresh
    # kitty.memory.semantic
    # PRIVATE_SENTINEL do not print
    async def client_events():
        if event.get("type") == "session.update":
            await upstream.send_json(event)
        if event.get("type") == "response.create":
            await upstream.send_json(event)
    async def provider_events():
        if event.get("type") == "conversation.item.input_audio_transcription.completed":
            await ws.send_json(event)
'''


class TestMemoryPathProbe(TestCase):
    def test_fixed_allowlisted_outputs(self):
        result = probe(SOURCE)
        self.assertEqual(result["syntax"], "valid")
        self.assertEqual(result["client_handler"], "one")
        self.assertEqual(result["provider_handler"], "one")
        self.assertEqual(result["client_session_update_branch"], "present")
        self.assertEqual(result["client_response_create_branch"], "present")
        self.assertEqual(result["client_upstream_sends"], "multiple")
        self.assertEqual(result["upstream_final_transcription"], "present")
        self.assertEqual(result["unsafe_experimental_ram_hook"], "absent")
        self.assertEqual(result["safe_to_enable_private_history"], "no")
        self.assertTrue(all(len(v) < 30 for v in result.values()))
        self.assertFalse(any("SENTINEL" in str(v) for v in result.values()))

    def test_absent_source_no_unsafe_assumption(self):
        self.assertEqual(probe(None)["source"], "unavailable")
        self.assertEqual(probe(None)["syntax"], "unknown")
        self.assertTrue(all(probe(None)[k] == "unknown" for k in MARKERS))

    def test_unrecognized_source_fails_closed(self):
        result = probe("async def f():\n    pass\n")
        self.assertEqual(result["client_handler"], "none")
        self.assertEqual(result["client_session_update_branch"], "not_verified")
        self.assertEqual(result["safe_to_enable_private_history"], "no")

    def test_private_source_not_printed(self):
        sink = StringIO()
        with mock.patch("kitty_v6_gateway_memory_path_probe.SOURCE") as path:
            path.read_text.return_value = SOURCE
            with redirect_stdout(sink):
                probe_main()
        self.assertNotIn("PRIVATE_SENTINEL", sink.getvalue())
        self.assertNotIn("async def", sink.getvalue())
        self.assertIn("changes=none", sink.getvalue())


if __name__ == "__main__":
    main()
