"""Offline tests: semantic lookup must never stall voice or mix speakers."""
import asyncio
import unittest
from kitty_semantic_async_client_v6 import (
    semantic_context, shared_context, shared_context_for_query, owner_semantic_context,
    _local_memory_endpoint, _NoRedirect,
)


class AsyncSemanticTests(unittest.IsolatedAsyncioTestCase):
    async def test_known_speaker_uses_shared_endpoint(self):
        calls = []
        def lookup(url, token, query, sid, timeout):
            calls.append((query, sid))
            return "Camille likes cats"
        result = await semantic_context(
            "http://127.0.0.1:8766", "token", "好きな猫", "person:camille",
            request_fn=lookup)
        self.assertEqual(result, "Camille likes cats")
        self.assertEqual(calls, [("好きな猫", "person:camille")])

    async def test_unknown_speaker_never_queries(self):
        def forbidden(*args):
            raise AssertionError("must not run")
        for speaker in ("unknown", "", "person:\nother", "owner", "speaker-1", "person:日本", "person:" + "x" * 49):
            result = await semantic_context(
                "http://127.0.0.1:8766", "token", "name", speaker,
                request_fn=forbidden)
            self.assertEqual(result, "")

    async def test_timeout_does_not_fail_voice(self):
        def slow(*args):
            import time
            time.sleep(0.15)
            return "late result"
        result = await semantic_context(
            "http://127.0.0.1:8766", "token", "name", "person:camille",
            timeout=0.05, request_fn=slow)
        self.assertEqual(result, "")

    async def test_owner_recall_needs_signed_exact_turn_and_grant(self):
        calls = []
        def fake(url, token, query, speaker, timeout, session_id, grant,
                 item_id, transcript, ticket):
            calls.append((query, speaker, session_id, grant,
                          item_id, transcript, ticket))
            return "authorized owner context"
        payload = {"item_id": "item_1",
                   "transcript": "What did I decide?",
                   "turn_attestation": "independent-signed-ticket"}
        result = await owner_semantic_context(
            "http://127.0.0.1:8766", "device", "What did I decide?",
            "enrolled-session-1234", "signed-grant",
            request_fn=fake, **payload)
        self.assertEqual(result, "authorized owner context")
        self.assertEqual(calls, [(
            "What did I decide?", "person:owner", "enrolled-session-1234",
            "signed-grant", "item_1", "What did I decide?",
            "independent-signed-ticket")])

        def forbidden(*args):
            raise AssertionError("unproven owner request must not start")
        for session, grant, changes in (
            ("short", "signed-grant", {}),
            ("enrolled-session-1234", "", {}),
            ("enrolled-session-1234", None, {}),
            ("enrolled-session-1234", "signed-grant",
             {"turn_attestation": ""}),
            ("enrolled-session-1234", "signed-grant",
             {"transcript": "different question"}),
            ("enrolled-session-1234", "signed-grant",
             {"item_id": "bad item with spaces"}),
        ):
            result = await owner_semantic_context(
                "http://127.0.0.1:8766", "device", "What did I decide?",
                session, grant, request_fn=forbidden, **{**payload, **changes})
            self.assertEqual(result, "")

    async def test_crafted_authority_and_remote_redirects_are_rejected(self):
        def forbidden(*args):
            raise AssertionError("off-host query must not execute")
        unsafe=(
            "http://127.0.0.1:8766@evil.example",
            "http://127.0.0.1:8766/path",
            "http://127.0.0.1:8766?token=private",
            "http://127.0.0.1:8766#fragment",
            "http://127.0.0.1:bad",
            "http://127.0.0.1:8766@example.org",
            "https://127.0.0.1:8766",
            "unix:///run/kitty-semantic/../escape.sock",
            "unix:///run/kitty-semantic/%2e%2e/escape.sock",
            "unix:///tmp/kitty.sock",
        )
        for url in unsafe:
            self.assertFalse(_local_memory_endpoint(url),url)
            self.assertEqual(await semantic_context(
                url,"device","private","person:camille",request_fn=forbidden),"")
            self.assertEqual(await shared_context(
                url,"device",request_fn=forbidden),"")
            self.assertEqual(await owner_semantic_context(
                url,"device","private","enrolled-session-1234","signed",
                request_fn=forbidden),"")
        self.assertTrue(_local_memory_endpoint("http://127.0.0.1:8766"))
        self.assertTrue(_local_memory_endpoint(
            "unix:///run/kitty-semantic/kitty-memory.sock"))
        self.assertIsNone(_NoRedirect().redirect_request(
            None,None,302,"Found",{},"https://evil.example"))

    async def test_approved_query_uses_only_local_memory_service(self):
        requests = []
        def fake(url, token, timeout, query):
            requests.append((url, token, query))
            return "Mochi Planet has sugar trees"
        result = await shared_context_for_query(
            "http://127.0.0.1:8766", "device", "Mochi Planet",
            request_fn=fake)
        self.assertIn("Mochi Planet", result)
        self.assertEqual(requests, [
            ("http://127.0.0.1:8766", "device", "Mochi Planet")])

        def forbidden(*_):
            raise AssertionError("unsafe public query sent")
        for url, query in (
                ("https://external.example", "Mochi"),
                ("http://127.0.0.1:8766", ""),
                ("http://127.0.0.1:8766", "Mochi" * 100),
                ("http://127.0.0.1:8766", None)):
            self.assertEqual(
                await shared_context_for_query(
                    url, "device", query, request_fn=forbidden), "")

    async def test_public_query_timeout_fails_closed(self):
        def slow(*args):
            import time
            time.sleep(0.15)
            return "late public data"
        result = await shared_context_for_query(
            "http://127.0.0.1:8766", "device", "Mochi",
            timeout=0.05, request_fn=slow)
        self.assertEqual(result, "")

    async def test_not_sent_to_remote_memory_server(self):
        def forbidden(*args):
            raise AssertionError("must not run")
        result = await semantic_context(
            "https://example.org", "token", "private", "person:camille",
            request_fn=forbidden)
        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
