#!/usr/bin/env python3
"""Candidate-only adaptive recognition scoring, no voice model or external data."""
import math
import unittest
from kitty_voice_adaptive_scoring_v6 import candidate_score
from test_kitty_voice_learning_v6 import vector


def unit(values):
    norm=math.sqrt(sum(float(v)*float(v) for v in values))
    return [float(v)/norm for v in values]


def mix(dim, a, b):
    arr=[0.0]*dim
    arr[0]=a
    arr[2]=b
    return unit(arr)


class FamiliarityScoringTests(unittest.TestCase):
    def setUp(self):
        self.now="2026-11-04T11:00:00+00:00"
        self.anchors=[mix(512,1.0,0.0),
                      mix(512,1.0,0.03),
                      mix(512,1.0,0.01)]
        self.query=mix(512,0.93,0.37)
        self.adaptive=[{
            "timestamp":"2026-11-01T11:00:00+00:00",
            "embedding":mix(512,0.93,0.34)},
            {"timestamp":"2026-11-02T11:00:00+00:00",
             "embedding":mix(512,0.93,0.38)},
            {"timestamp":"2026-11-03T11:00:00+00:00",
             "embedding":mix(512,0.93,0.36)}]

    def test_three_genuine_sessions_improve_candidate_without_lowering_threshold(self):
        anchor,source=candidate_score(self.query,self.anchors,self.adaptive,
                                      now=self.now,adaptive_enabled=False)
        result,label=candidate_score(self.query,self.anchors,self.adaptive,
                                     now=self.now,adaptive_enabled=True)
        self.assertLess(anchor,0.965)
        self.assertGreater(result,0.965)
        self.assertEqual(source,"anchors")
        self.assertEqual(label,"adaptive")

    def test_one_or_two_new_samples_never_take_over(self):
        baseline,_=candidate_score(self.query,self.anchors,now=self.now)
        for count in (0,1,2):
            value,source=candidate_score(
                self.query,self.anchors,self.adaptive[:count],
                now=self.now,adaptive_enabled=True)
            self.assertAlmostEqual(value,baseline)
            self.assertEqual(source,"anchors")

    def test_old_voice_remains_unknown_despite_an_adaptive_cluster(self):
        stranger=mix(512,0.1,0.995)
        score,label=candidate_score(stranger,self.anchors,self.adaptive,
                                    now=self.now,adaptive_enabled=True)
        self.assertLess(score,0.90)
        self.assertEqual(label,"anchors")

    def test_expired_and_mixed_model_samples_dont_learn(self):
        stale=[{**entry,"timestamp":"2026-01-01T00:00:00+00:00"}
               for entry in self.adaptive]
        _,source=candidate_score(self.query,self.anchors,stale,
                                 now=self.now,adaptive_enabled=True)
        self.assertEqual(source,"anchors")
        mixed=[{**item,"embedding":vector(0)} for item in self.adaptive]
        _,source=candidate_score(self.query,self.anchors,mixed,
                                 now=self.now,adaptive_enabled=True)
        self.assertEqual(source,"anchors")

    def test_192d_ecapa_and_512d_xvector_never_mix(self):
        first=[vector(0,0.02),vector(0,0.04),vector(0,0.06)]
        val,source=candidate_score(vector(0,0.08),first,
                                   now=self.now,adaptive_enabled=False)
        self.assertGreater(val,0.9)
        self.assertEqual(source,"anchors")
        with self.assertRaises(ValueError):
            candidate_score(self.query,first,now=self.now)


if __name__=="__main__":
    unittest.main()
