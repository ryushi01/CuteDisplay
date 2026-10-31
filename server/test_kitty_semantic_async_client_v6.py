"""Offline tests: semantic lookup must never stall voice or mix speakers."""
import asyncio
import unittest
from kitty_semantic_async_client_v6 import semantic_context


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
        for speaker in ("unknown", "", "person:\nother"):
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

    async def test_not_sent_to_remote_memory_server(self):
        def forbidden(*args):
            raise AssertionError("must not run")
        result = await semantic_context(
            "https://example.org", "token", "private", "person:camille",
            request_fn=forbidden)
        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
