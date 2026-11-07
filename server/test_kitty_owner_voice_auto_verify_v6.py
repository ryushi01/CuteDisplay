#!/usr/bin/env python3
"""Offline voice-based owner authorization and impersonation tests."""
import io
import math
import struct
import time
import unittest
import wave

from kitty_owner_voice_auto_verify_v6 import AutomaticVoiceOwner
from kitty_attested_live_call_v6 import verify_external_attestation
from kitty_owner_session_v6 import verify_grant

SESSION = "gateway_voice_auto_session_123"
SIGNER = b"t"*32
GRANT = b"g"*32
# HTTP boundary tests run against the actual current clock; using a
# future fixed epoch would make every signed grant not-yet-valid.
WALL = int(time.time())


def captured_wav(freq=180):
    with io.BytesIO() as raw:
        with wave.open(raw, "wb") as w:
            w.setnchannels(1)
            w.setframerate(16000)
            w.setsampwidth(2)
            # Distinct 2s microphone samples, not from device/HTTP JSON.
            pcm = b"".join(struct.pack("<h", int(9000 * math.sin(
                2*math.pi*freq*(j/16000)))) for j in range(32000))
            w.writeframes(pcm)
        return raw.getvalue()


class VoiceOwnerTests(unittest.TestCase):
    def setup_gate(self, matcher=None, **settings):
        opts = {
            "session_id": SESSION,
            "match_audio": matcher if matcher is not None else (
                lambda wav: {"speaker_id":"person:shana", "score":0.983}),
            "turn_issuer_secret": SIGNER,
            "grant_secret": GRANT,
            "opt_in": True,
            "enrolled_owner_profile": True,
            "clock": lambda: 2.0,
            "wall_clock": lambda: WALL,
        }
        opts.update(settings)
        return AutomaticVoiceOwner(**opts)

    def observe(self, gate, item, transcript, wav=None, trust=True):
        return gate.observe(
            item_id=item, transcript=transcript,
            microphone_wav=wav if wav is not None else captured_wav(
                freq=180 + len(item)*5),
            trusted_provider_capture=trust)

    def test_two_voice_matches_issue_matching_short_lived_proofs(self):
        gate = self.setup_gate()
        self.assertTrue(gate.enabled)
        self.assertIsNone(self.observe(gate, "turn_A",
                                       "My name is Shana.", captured_wav(175)))
        result = self.observe(gate, "turn_B",
                              "What was my plan?", captured_wav(225))
        self.assertEqual(result["speaker_id"], "person:owner")
        self.assertFalse(result["self_introduction_confirmed"])
        self.assertEqual(verify_external_attestation(
            SIGNER, result["turn_attestation"], session_id=SESSION,
            item_id="turn_B", transcript="What was my plan?",
            audio_sha256=result["audio_sha256"], now=WALL),
            ("person:owner","owner"))
        self.assertTrue(verify_grant(
            GRANT, result["owner_grant"], SESSION, now=WALL))
        self.assertFalse(verify_grant(
            GRANT, result["owner_grant"], "another_session_1234", now=WALL))
        self.assertIsNone(verify_external_attestation(
            SIGNER, result["turn_attestation"], session_id=SESSION,
            item_id="turn_A", transcript="What was my plan?", now=WALL))
        self.assertIsNone(verify_external_attestation(
            SIGNER, result["turn_attestation"], session_id=SESSION,
            item_id="turn_B", transcript="What was my plan?", now=WALL+11))
        self.assertFalse(verify_grant(
            GRANT, result["owner_grant"], SESSION, now=WALL+61))
        gate.close()
        self.assertFalse(gate.enabled)
        self.assertIsNone(self.observe(gate, "turn_C", "Hello Kitty", captured_wav(250)))

    def test_named_convenience_requires_matching_voice_and_explicit_opt_in(self):
        for statement in (
            "My name is Shana.", "I'm Shana!", "Je m'appelle Shana.",
            "私はシャナです", "Shana",
        ):
            with self.subTest(statement=statement):
                gate = self.setup_gate(
                    named_confirmation_opt_in=True,
                    matcher=lambda wav: {
                        "speaker_id":"person:shana","score":0.966})
                result=self.observe(
                    gate,"named", statement, captured_wav(245))
                self.assertIsNotNone(result)
                self.assertTrue(result["self_introduction_confirmed"])
                self.assertTrue(verify_grant(
                    GRANT,result["owner_grant"],SESSION,now=WALL))
                gate.close()

        # A high score is still not a grant without the opt-in route.
        gate=self.setup_gate(matcher=lambda wav: {
            "speaker_id":"person:shana","score":0.966})
        self.assertIsNone(self.observe(
            gate,"first","My name is Shana",captured_wav(250)))
        self.assertIsNone(self.observe(
            gate,"second","Hello",captured_wav(270)))

    def test_wrong_name_and_name_only_fail_even_in_named_mode(self):
        for statement,score in (
                ("I'm Shana",0.964),
                ("I'm Shana",0.960),
                ("I'm somebody else",0.999),
                ("my name is Shana",0.1),
                ("Shana",0.0),
                ("私はシャナです",0.95)):
            gate=self.setup_gate(
                named_confirmation_opt_in=True,
                matcher=lambda wav,s=score:{
                    "speaker_id":"person:shana","score":s})
            self.assertIsNone(self.observe(
                gate,"test",statement,captured_wav(180)))
            gate.close()

    def test_disallowed_by_default_or_without_consent_profile(self):
        for change in (
                {"opt_in":False},
                {"enrolled_owner_profile":False},
                {"grant_secret":SIGNER},
                {"turn_issuer_secret":b"short"},
                {"threshold":0.960},
                {"session_id":"invalid"},
                {"candidate_id":"person:owner"}):
            with self.subTest(change=change):
                gate=self.setup_gate(**change)
                self.assertFalse(gate.enabled)
                self.assertIsNone(self.observe(
                    gate, "turn_A", "My name is Shana.", captured_wav(175)))
                self.assertIsNone(self.observe(
                    gate, "turn_B", "What was my plan?", captured_wav(225)))

    def test_spoken_name_alone_never_discloses_private_memory(self):
        gate = self.setup_gate(matcher=lambda wav: {
            "speaker_id":"unknown","score":0.1})
        for item, statement, hz in (
                ("guest_1", "I am Shana", 230),
                ("guest_2", "My name is Shana", 280),
                ("guest_3", "This is Shana", 290)):
            self.assertIsNone(self.observe(gate,item,statement,captured_wav(hz)))
        self.assertEqual(gate._observed, [])

    def test_one_probable_match_is_not_private_authorization(self):
        gate = self.setup_gate(matcher=lambda wav: {
            "speaker_id":"person:shana","score":0.960})
        for i in range(3):
            self.assertIsNone(self.observe(
                gate,f"turn_{i}","Please remember my plans",captured_wav(180+i*13)))
        self.assertEqual(gate._observed, [])

    def test_no_scores_supplied_by_client_and_no_untrusted_audio(self):
        gate=self.setup_gate()
        self.assertIsNone(self.observe(
            gate, "a", "I am Shana", captured_wav(180), trust=False))
        self.assertIsNone(gate.observe(
            item_id="b",transcript="I am Shana",
            microphone_wav=b"fake",trusted_provider_capture=True))
        self.assertEqual(gate._observed, [])
        self.assertIsNone(gate.observe(
            item_id="c",transcript="I am Shana",
            microphone_wav=captured_wav(180),
            trusted_provider_capture=False))
        self.assertIsNone(self.observe(
            gate, "d", "Hello", captured_wav(180)))
        self.assertIsNone(self.observe(
            gate, "d", "Hello", captured_wav(225)))  # same provider item

    def test_replayed_identical_audio_and_speaker_switch_reset_evidence(self):
        gate=self.setup_gate()
        audio=captured_wav(180)
        self.assertIsNone(self.observe(gate,"first","Hello",audio))
        self.assertIsNone(self.observe(gate,"second","Hello again",audio))
        self.assertIsNone(self.observe(gate,"third","Next",captured_wav(200)))
        result=self.observe(gate,"fourth","What did I say?",captured_wav(240))
        self.assertIsNotNone(result)
        gate.speaker_change()
        self.assertIsNone(self.observe(gate,"fifth","Hi",captured_wav(270)))

    def test_guest_between_matches_resets_owner_evidence(self):
        responses=iter([
            {"speaker_id":"person:shana","score":0.98},
            {"speaker_id":"person:guest","score":0.99},
            {"speaker_id":"person:shana","score":0.99},
            {"speaker_id":"person:shana","score":0.97},
        ])
        gate=self.setup_gate(matcher=lambda wav: next(responses))
        self.assertIsNone(self.observe(gate,"a","Hi",captured_wav(180)))
        self.assertIsNone(self.observe(gate,"b","Hello",captured_wav(205)))
        self.assertIsNone(self.observe(gate,"c","Hi again",captured_wav(240)))
        result=self.observe(gate,"d","Recall my plan",captured_wav(270))
        self.assertIsNotNone(result)

    def test_no_explicit_provider_capture_or_repeated_stale_turn(self):
        gate=self.setup_gate()
        self.assertIsNone(self.observe(gate,"a","Hello",captured_wav(180)))
        self.assertIsNone(self.observe(gate,"a","Hello",captured_wav(250)))
        self.assertEqual(len(gate._observed),0)
        self.assertIsNone(self.observe(gate,"b","Hello",captured_wav(265),trust=False))
        self.assertIsNone(self.observe(gate,"c","Hello",captured_wav(268)))
        self.assertIsNotNone(self.observe(gate,"d","Recall",captured_wav(273)))


if __name__=="__main__":
    unittest.main()
