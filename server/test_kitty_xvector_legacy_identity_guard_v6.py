#!/usr/bin/env python3
"""Offline proof old experimental X-vector mode never authorizes identity."""
import base64
import os
import sys
import types
import unittest
from unittest.mock import patch
import kitty_speaker_cpu_v6 as cpu


class CandidateOnlyIdentityTests(unittest.TestCase):
    def setUp(self):
        self.audio=base64.b64encode(b"not-model-audio").decode("ascii")
        self.fake=types.ModuleType("kitty_xvector_shadow_worker_v6")
        self.fake.recognize_candidate=lambda *args,**kwargs:{
            "speaker_id":"person:shana","confidence":"probable","score":0.98}

    def test_legacy_experimental_identity_stays_non_authorizing(self):
        with patch.dict(os.environ,{
             "KITTY_XVECTOR_EXPERIMENTAL_IDENTITY":"1",
             "KITTY_XVECTOR_CANDIDATE_ONLY":"0"
             }),patch.dict(sys.modules,{"kitty_xvector_shadow_worker_v6":self.fake}):
            result=cpu.identify(self.audio)
        self.assertEqual(result["speaker_id"],"unknown")
        self.assertEqual(result["confidence"],"unknown")
        self.assertIsNone(result["score"])
        self.assertIs(result["candidate_only"],True)
        self.assertEqual(result["candidate_speaker_id"],"person:shana")

    def test_normal_candidate_only_stays_non_authorizing(self):
        with patch.dict(os.environ,{"KITTY_XVECTOR_CANDIDATE_ONLY":"1"}),patch.dict(
                sys.modules,{"kitty_xvector_shadow_worker_v6":self.fake}):
            result=cpu.identify(self.audio)
        self.assertEqual(result["speaker_id"],"unknown")
        self.assertTrue(result["candidate_only"])
        self.assertEqual(result["candidate_speaker_id"],"person:shana")
        self.assertIsNone(result["score"])

    def test_out_of_range_experimental_score_refused(self):
        self.fake.recognize_candidate=lambda *args,**kwargs:{
            "speaker_id":"person:shana","score":0.1}
        with patch.dict(os.environ,{
             "KITTY_XVECTOR_EXPERIMENTAL_IDENTITY":"1",
             "KITTY_XVECTOR_CANDIDATE_ONLY":"0"}),patch.dict(
             sys.modules,{"kitty_xvector_shadow_worker_v6":self.fake}):
            result=cpu.identify(self.audio)
        self.assertEqual(result["speaker_id"],"unknown")
        self.assertEqual(result["candidate_speaker_id"],"unknown")
        self.assertIsNone(result["candidate_score"])


if __name__=="__main__":
    unittest.main()
