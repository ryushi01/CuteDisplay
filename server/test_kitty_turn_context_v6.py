"""Speaker-scoped context integration contract for text and voice."""
import unittest
from kitty_turn_context_v6 import text_turn_context, voice_turn_context


class TurnContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_paths_use_same_attribution(self):
        seen = []
        async def lookup(url, token, query, speaker):
            seen.append((query, speaker))
            return "- [speaker=person:aki; unverified_identity] Aki likes coffee"
        attr={"speaker_id":"person:aki","speaker_role":"guest",
              "provenance":"voice_probable"}
        a=await text_turn_context("local", "token", "珈琲", attr, lookup=lookup)
        b=await voice_turn_context("local", "token", "cafe", attr, lookup=lookup)
        self.assertIn("Aki likes coffee", a)
        self.assertIn("Aki likes coffee", b)
        self.assertEqual(seen, [("珈琲","person:aki"),("cafe","person:aki")])

    async def test_unknown_turn_never_inherits_prior_speaker(self):
        async def forbidden(*args):
            raise AssertionError("lookup should not run")
        for attr in (None, {}, {"speaker_id":"unknown","provenance":"voice_probable"},
                     {"speaker_id":"person:aki","provenance":"unverified"}):
            self.assertEqual(await voice_turn_context(
                "local", "token", "hello", attr, lookup=forbidden), "")

    async def test_untrusted_owner_role_never_accepted(self):
        async def forbidden(*args):
            raise AssertionError("owner claim not authenticated")
        attr={"speaker_id":"person:owner","speaker_role":"owner",
              "provenance":"session_verified"}
        self.assertEqual(await text_turn_context(
            "local", "token", "private", attr, lookup=forbidden), "")


if __name__ == "__main__":
    unittest.main()
