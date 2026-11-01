#!/usr/bin/env python3
"""Pure offline voice-ID tests; no model download or sample recordings."""
import unittest
import numpy as np
from kitty_voice_id_v6 import identify,enroll_profile,pcm16_from_wav

class VoiceIDV6Tests(unittest.TestCase):
    def test_unknown_without_enrollment(self):
        self.assertEqual(identify([1,0,0],{}).speaker_id,"unknown")
    def test_voice_match_requires_clear_margin(self):
        profiles={"person:shana":[[1,0,0]]*3,"person:guest":[[0,1,0]]*3}
        self.assertEqual(identify([1,0,0],profiles).speaker_id,"person:shana")
        self.assertEqual(identify([0.1,0.2,0.97],profiles).speaker_id,"unknown")
    def test_ambiguous_never_guesses(self):
        profiles={"person:shana":[[1,0,0]]*3,"person:other":[[0.995,0.1,0]]*3}
        self.assertEqual(identify([1,0,0],profiles).speaker_id,"unknown")
    def test_enrollment_needs_multiple_samples(self):
        with self.assertRaises(ValueError):
            enroll_profile([[1,0,0]])
        self.assertEqual(len(enroll_profile([[1,0,0]]*3)),3)
    def test_empty_bad_wav_rejected(self):
        with self.assertRaises((ValueError,EOFError)):
            pcm16_from_wav(b"not a wav")
if __name__=="__main__":
    unittest.main()
