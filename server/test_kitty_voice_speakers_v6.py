import unittest
from kitty_voice_speakers_v6 import VoiceRegistry,owner_fact_permission

A=[1.,0.,0.,0.,0.,0.,0.,0.]
B=[0.,1.,0.,0.,0.,0.,0.,0.]

class SpeakerTests(unittest.TestCase):
    def setUp(self):
        self.registry=VoiceRegistry("speaker-model-v1",threshold=.7,margin=.1)
    def test_no_automatic_enrollment(self):
        with self.assertRaises(PermissionError):
            self.registry.enroll("voice:owner",[A,A,A])
        with self.assertRaises(ValueError):
            self.registry.enroll("voice:owner",[A,A],consented=True)
    def test_distinguishes_two_voices(self):
        self.registry.enroll("voice:a",[A,A,A],consented=True)
        self.registry.enroll("voice:b",[B,B,B],consented=True)
        match=self.registry.identify(A,"speaker-model-v1",quality_ok=True)
        self.assertEqual(match.speaker_id,"voice:a")
        self.assertFalse(owner_fact_permission(match))
        self.assertEqual(self.registry.identify(B,"speaker-model-v1",quality_ok=True).speaker_id,"voice:b")
    def test_unknown_on_low_quality_or_model_mismatch(self):
        self.registry.enroll("voice:a",[A,A,A],consented=True)
        self.assertFalse(self.registry.identify(A,"other-model",quality_ok=True).recognized)
        self.assertFalse(self.registry.identify(A,"speaker-model-v1",quality_ok=False).recognized)
        self.assertFalse(self.registry.identify(B,"speaker-model-v1",quality_ok=True).recognized)
    def test_deletion(self):
        self.registry.enroll("voice:a",[A,A,A],consented=True)
        self.registry.forget("voice:a")
        self.assertFalse(self.registry.identify(A,"speaker-model-v1",quality_ok=True).recognized)
    def test_inconsistent_enrollment_rejected(self):
        with self.assertRaises(ValueError):
            self.registry.enroll("voice:a",[A,A,B],consented=True)
if __name__=="__main__":
    unittest.main()
