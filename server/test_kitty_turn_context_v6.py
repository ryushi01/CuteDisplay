"""Offline trust-boundary tests: unverified voice never recalls private history."""
import unittest
from kitty_turn_context_v6 import text_turn_context, voice_turn_context
from kitty_live_rolling_context_v6 import LiveCallContinuity


class TurnContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_candidate_and_introduction_do_not_query_private_history(self):
        async def forbidden(*args):
            raise AssertionError("private lookup must not run")
        for source in ("voice_probable", "explicit_introduction",
                       "explicit_correction", "unverified"):
            attr={"speaker_id":"person:aki", "speaker_role":"guest",
                  "provenance":source, "item_id":"turn-123",
                  "session_id":"trusted-live-session-123"}
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
              "provenance":"session_verified", "item_id":"turn-123",
              "session_id":"trusted-live-session-123"}
        a=await text_turn_context("local","token","珈琲",attr,
                                  trusted_item_id="turn-123",
                                  trusted_session_id="trusted-live-session-123",lookup=lookup)
        b=await voice_turn_context("local","token","cafe",attr,
                                   trusted_item_id="turn-123",
                                  trusted_session_id="trusted-live-session-123",lookup=lookup)
        self.assertIn("Aki likes coffee",a)
        self.assertIn("Aki likes coffee",b)
        self.assertEqual(seen,[("珈琲","person:aki"),("cafe","person:aki")])

    async def test_missing_or_mismatched_trust_fails_closed(self):
        async def forbidden(*args):
            raise AssertionError("untrusted lookup")
        attr={"speaker_id":"person:aki","speaker_role":"guest",
              "provenance":"session_verified","item_id":"turn-123",
              "session_id":"trusted-live-session-123"}
        for bound in (None,"","turn-122"):
            self.assertEqual(await voice_turn_context(
                "local","token","private",attr,
                trusted_item_id=bound,
                trusted_session_id="trusted-live-session-123",lookup=forbidden),"")

    async def test_trusted_session_is_required_independently_of_item(self):
        async def forbidden(*args):
            raise AssertionError("missing trusted session cannot query memory")
        attr={"speaker_id":"person:aki","speaker_role":"guest",
              "provenance":"session_verified","item_id":"turn-123",
              "session_id":"trusted-live-session-123"}
        for trusted in (None,"","different-session"):
            self.assertEqual(await voice_turn_context(
                "local","token","private",attr,
                trusted_item_id="turn-123",trusted_session_id=trusted,
                lookup=forbidden),"")
        forged={**attr,"session_id":"another-session"}
        self.assertEqual(await voice_turn_context(
            "local","token","private",forged,
            trusted_item_id="turn-123",
            trusted_session_id="trusted-live-session-123",
            lookup=forbidden),"")

    async def test_malformed_speakers_and_oversize_inputs_denied(self):
        async def forbidden(*args):
            raise AssertionError("malformed speaker or item cannot query")
        for speaker in ("person:日本", "person:bad name", "person:"+"x"*49):
            attr={"speaker_id":speaker,"speaker_role":"guest",
                  "provenance":"session_verified","item_id":"turn-123",
              "session_id":"trusted-live-session-123"}
            self.assertEqual(await voice_turn_context(
                "local","token","private",attr,
                trusted_item_id="turn-123",
                                  trusted_session_id="trusted-live-session-123",lookup=forbidden),"")
        attr={"speaker_id":"person:aki","speaker_role":"guest",
              "provenance":"session_verified","item_id":"turn-123",
              "session_id":"trusted-live-session-123"}
        for text in ("", "x"*301):
            self.assertEqual(await voice_turn_context(
                "local","token",text,attr,
                trusted_item_id="turn-123",
                                  trusted_session_id="trusted-live-session-123",lookup=forbidden),"")

    async def test_verified_live_context_avoids_remote_semantic_request(self):
        rolling=LiveCallContinuity()
        rolling.begin_call("trusted-live-session-123")
        early={"speaker_id":"person:aki","speaker_role":"guest",
               "provenance":"session_verified","item_id":"early",
               "session_id":"trusted-live-session-123"}
        later={**early,"item_id":"later"}
        self.assertTrue(rolling.observe("We agreed to keep the C5 Bluetooth.",
                                        early,trusted_item_id="early"))
        self.assertTrue(rolling.observe("Tell me a story.",later,trusted_item_id="later"))
        async def forbidden(*args):
            raise AssertionError("live context should not cause HTTP lookup")
        result=await voice_turn_context(
            "local","token","What did we decide?",later,
            trusted_item_id="later",
            trusted_session_id="trusted-live-session-123",
            rolling=rolling,lookup=forbidden)
        self.assertIn("C5 Bluetooth",result)

    async def test_live_context_never_opens_on_unverified_item(self):
        rolling=LiveCallContinuity()
        rolling.begin_call("trusted-live-session-123")
        good={"speaker_id":"person:aki","speaker_role":"guest",
              "provenance":"session_verified","item_id":"early",
              "session_id":"trusted-live-session-123"}
        rolling.observe("Remember the hidden plan",good,trusted_item_id="early")
        async def forbidden(*args):
            raise AssertionError("wrong item must never reach semantic lookup")
        for bad in (
            {**good,"item_id":"later","provenance":"voice_probable"},
            {**good,"item_id":"later","session_id":"another-session"},
            {**good,"item_id":"later","speaker_role":"owner"},
        ):
            self.assertEqual(await voice_turn_context(
                "local","token","private",bad,trusted_item_id="later",
                trusted_session_id="trusted-live-session-123",
                rolling=rolling,lookup=forbidden),"")

    async def test_unknown_and_owner_claims_fail_closed(self):
        async def forbidden(*args):
            raise AssertionError("owner claim is not authentication")
        attrs=(None, {}, {"speaker_id":"unknown","provenance":"session_verified"},
               {"speaker_id":"person:owner","speaker_role":"owner",
                "provenance":"session_verified","item_id":"turn-123",
              "session_id":"trusted-live-session-123"})
        for attr in attrs:
            self.assertEqual(await text_turn_context(
                "local","token","private",attr,
                trusted_item_id="turn-123",
                                  trusted_session_id="trusted-live-session-123",lookup=forbidden),"")


if __name__=="__main__":
    unittest.main()
