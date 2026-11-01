"""No-model tests for offline speaker score methods and data separation."""
import unittest
import numpy as np
from evaluate_kitty_speaker_scores_v6 import normalize, score, evaluate

class OfflineScoresTests(unittest.TestCase):
    def test_methods(self):
        refs=[[1,0],[0.8,0.6],[0.6,0.8]]
        q=[1,0]
        self.assertAlmostEqual(score(q,refs,"median"),0.8)
        self.assertAlmostEqual(score(q,refs,"max"),1.0)
        self.assertGreater(score(q,refs,"centroid"),0.8)

    def test_holdout_is_not_training(self):
        vec={1:normalize([1,0]),4:normalize([0.8,0.6]),
             5:normalize([0.6,0.8]),6:normalize([0,1])}
        result=evaluate(vec,[1,4,5],[6])
        self.assertEqual(set(result["median"]["loo"]),{1,4,5})
        self.assertEqual(set(result["median"]["holdout"]),{6})
        self.assertLess(result["median"]["holdout"][6],1)

    def test_bad_vectors_rejected(self):
        with self.assertRaises(ValueError):
            normalize([0,0])

if __name__=="__main__":
    unittest.main()
