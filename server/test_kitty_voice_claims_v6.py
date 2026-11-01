#!/usr/bin/env python3
"""Changed-voice identity fallback tests: claimed is not verified."""
import unittest
from kitty_voice_claims_v6 import claimed_speaker,reconcile_voice_and_claim
from kitty_realtime_voice_v6 import UtteranceCollector, recognize_turn

class ClaimTests(unittest.IsolatedAsyncioTestCase):
    async def test_english_french_japanese(self):
        for t in ("Hey, this is Shana", "I'm Shana", "Bonjour, c'est Shana",
                  "Je suis Shana", "私はシャナです", "シャナだよ"):
            with self.subTest(t=t):
                self.assertEqual(claimed_speaker(t),"person:shana")
    async def test_mentions_are_not_introductions(self):
        for t in ("Shana told me a story", "Are you Shana?", "Who is Shana?"):
            self.assertIsNone(claimed_speaker(t))
    async def test_claim_never_becomes_probable(self):
        x=reconcile_voice_and_claim({"speaker_id":"unknown","confidence":"unknown"},
                                    "Hey, this is Shana")
        self.assertEqual((x["speaker_id"],x["confidence"]),("person:shana","claimed"))
    async def test_voice_conflict_preserves_acoustic_identity(self):
        x=reconcile_voice_and_claim({"speaker_id":"person:guest","confidence":"probable"},
                                    "Hey, this is Shana")
        self.assertEqual(x["speaker_id"],"person:guest")
        self.assertTrue(x["claim_conflicts"])
    async def test_short_utterance_is_archived_as_unverified_claim(self):
        c=UtteranceCollector()
        got=[]
        async def emit(e):got.append(e)
        await recognize_turn(c,"turn_1",emit,transcript="Hey, this is Shana")
        self.assertEqual(got[0]["confidence"],"claimed")
        self.assertEqual(got[0]["item_id"],"turn_1")
if __name__=="__main__":unittest.main()
