"""Offline trust-boundary tests: unverified voice never recalls private history."""
import unittest
from kitty_turn_context_v6 import text_turn_context, voice_turn_context


class TurnContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_candidate_and_introduction_do_not_query_private_history(self):
        async def forbidden(*args):
            raise AssertionError("private lookup must not run")
        for source in ("voice_probable", "explicit_introduction",
                       "explicit_correction", "unverified"):
            attr={"speaker_id":"person:aki", "speaker_role":"guest",
                  "provenance":source, "item_id":"turn-123"}
            for callback in (text_turn_context, voice_turn_context):
                self.assertEqual(await callback(
                    "local", "token", "my old memories", attr,
                    trusted_item_id="turn-123", lookup=forbidden), "")

    async def test_trusted_item_bound_guest_can_query_only_that_item(self):
        seen=[]
        async def lookup(url, token, query, speaker):
            seen.append((query,speaker))
            return "- [speaker=person:aki; unverified_identity] Aki likes coffee"
        attr={"speaker_id":"person:aki", "speaker_role":"guest",
              "provenance":"session_verified", "item_id":"turn-123"}
        a=await text_turn_context("local","token","珈琲",attr,
                                  trusted_item_id="turn-123",lookup=lookup)
        b=await voice_turn_context("local","token","cafe",attr,
                                   trusted_item_id="turn-123",lookup=lookup)
        self.assertIn("Aki likes coffee",a)
        self.assertIn("Aki likes coffee",b)
        self.assertEqual(seen,[("珈琲","person:aki"),("cafe","person:aki")])

    async def test_missing_or_mismatched_trust_fails_closed(self):
        async def forbidden(*args):
            raise AssertionError("untrusted lookup")
        attr={"speaker_id":"person:aki","speaker_role":"guest",
              "provenance":"session_verified","item_id":"turn-123"}
        for bound in (None,"","turn-122"):
            self.assertEqual(await voice_turn_context(
                "local","token","private",attr,
                trusted_item_id=bound,lookup=forbidden),"")

    async def test_unknown_and_owner_claims_fail_closed(self):
        async def forbidden(*args):
            raise AssertionError("owner claim is not authentication")
        attrs=(None, {}, {"speaker_id":"unknown","provenance":"session_verified"},
               {"speaker_id":"person:owner","speaker_role":"owner",
                "provenance":"session_verified","item_id":"turn-123"})
        for attr in attrs:
            self.assertEqual(await text_turn_context(
                "local","token","private",attr,
                trusted_item_id="turn-123",lookup=forbidden),"")


if __name__=="__main__":
    unittest.main()
