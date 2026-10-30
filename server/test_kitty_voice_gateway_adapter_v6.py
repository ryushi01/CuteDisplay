#!/usr/bin/env python3
import asyncio
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import numpy as np
from kitty_voice_gateway_adapter_v6 import wav16k_from_pcm24k,recognize_completed_utterance
from kitty_voice_profiles_sd_v6 import validate_profiles, export_enrollment

class GatewayAudioTests(unittest.IsolatedAsyncioTestCase):
    async def test_completed_utterance_resample(self):
        src=(np.sin(2*np.pi*440*np.arange(48000)/24000)*8000).astype("<i2").tobytes()
        import wave,io
        wav=wav16k_from_pcm24k(src)
        with wave.open(io.BytesIO(wav),"rb") as w:
            self.assertEqual(w.getframerate(),16000)
            self.assertEqual(w.getnframes(),32000)
    async def test_unknown_fallback(self):
        self.assertEqual((await recognize_completed_utterance(b"hello",url="",token=""))["speaker_id"],"unknown")
    async def test_voice_result_is_not_verified_owner(self):
        with patch("kitty_voice_gateway_adapter_v6._post",return_value={"speaker_id":"person:shana","confidence":"probable","score":0.99}):
            pcm=b"\x00\x08"*(24000*2)
            result=await recognize_completed_utterance(pcm,url="http://127.0.0.1:8772",token="test")
        self.assertEqual(result["speaker_id"],"person:shana")
        self.assertEqual(result["confidence"],"probable")
        self.assertNotIn("ownerVerified",result)

class VoiceProfilesTests(unittest.TestCase):
    def test_enrollment_export(self):
        doc=export_enrollment("person:shana",[[1,0,0]]*3)
        self.assertEqual(len(validate_profiles(doc)["person:shana"]),3)
    def test_consent_required(self):
        with self.assertRaises(ValueError):
            validate_profiles({"version":1,"speakers":{"person:test":{"consent":False,"vectors":[[1.0]]*3}}})
if __name__=="__main__":
    unittest.main()
