import unittest
from kitty_voice_adaptation_policy_v6 import propose, effective_embeddings, prune_adaptive

def vector(i):
    v = [0.0] * 192
    v[i] = 1.0
    return v

class AdaptationTests(unittest.TestCase):
    def setUp(self):
        self.profile = {"anchor_embeddings": [vector(0), vector(1), vector(2)],
                        "adaptive_embeddings": [], "consent": "local_explicit_enrollment"}
        self.now = "2026-11-01T02:00:00+00:00"

    def test_refuse_unverified(self):
        for verified, approved in [(False, True), (True, False)]:
            with self.assertRaises(PermissionError):
                propose(self.profile, vector(3), now=self.now, score=0.95,
                        verified=verified, explicit_approval=approved)
        self.assertEqual(self.profile["adaptive_embeddings"], [])

    def test_protected_anchors(self):
        result = propose(self.profile, vector(3), now=self.now, score=0.85,
                         verified=True, explicit_approval=True)
        self.assertEqual(result["anchor_embeddings"], self.profile["anchor_embeddings"])
        self.assertEqual(len(effective_embeddings(result, now=self.now)), 4)
        self.assertEqual(self.profile["adaptive_embeddings"], [])

    def test_reject_low_score(self):
        with self.assertRaises(ValueError):
            propose(self.profile, vector(3), now=self.now, score=0.71,
                    verified=True, explicit_approval=True)

    def test_reject_immediate_repeat(self):
        result = propose(self.profile, vector(3), now=self.now, score=0.9,
                         verified=True, explicit_approval=True)
        with self.assertRaises(ValueError):
            propose(result, vector(4), now=self.now, score=0.9,
                    verified=True, explicit_approval=True)

    def test_expiration(self):
        old = {"timestamp": "2026-01-01T00:00:00+00:00", "embedding": vector(3)}
        self.assertEqual(prune_adaptive([old], now=self.now), [])

if __name__ == "__main__":
    unittest.main()
