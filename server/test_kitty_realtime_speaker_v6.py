"""Offline, no-model safety tests for Kitty realtime speaker worker."""
import asyncio
import base64
import io
import unittest
import wave
from kitty_realtime_speaker_v6 import SpeakerTurn, identify_turn, to_16k_wav


class SpeakerWorkerTests(unittest.TestCase):
    def test_pcm_resampling_duration(self):
        raw = b"\x00\x00" * (24000 * 2)
        result = to_16k_wav(raw)
        with wave.open(io.BytesIO(result), "rb") as wav:
            self.assertEqual(wav.getframerate(), 16000)
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getsampwidth(), 2)
            self.assertEqual(wav.getnframes(), 32000)

    def test_short_pcm_rejected(self):
        with self.assertRaises(ValueError):
            to_16k_wav(b"\x00\x00" * 2400)

    def test_ring_bounded_and_cleared(self):
        turn = SpeakerTurn()
        turn.start()
        sample = base64.b64encode(b"\x00\x00" * 16000).decode()
        for _ in range(14):
            self.assertTrue(turn.append_base64_pcm16(sample))
        gen, raw = turn.snapshot()
        self.assertLessEqual(len(raw), 24000 * 2 * 8)
        turn.discard()
        next_gen, empty = turn.snapshot()
        self.assertNotEqual(gen, next_gen)
        self.assertEqual(empty, b"")

    def test_unconfigured_identity_is_unknown(self):
        event = asyncio.run(identify_turn("", "", "item-001", b""))
        self.assertEqual(event, {
            "type":"kitty.speaker.result", "item_id":"item-001",
            "speaker_id":"unknown", "confidence":"unknown"
        })


if __name__ == "__main__":
    unittest.main()
