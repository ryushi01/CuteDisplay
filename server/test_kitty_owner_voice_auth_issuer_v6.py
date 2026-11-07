#!/usr/bin/env python3
"""Synthetic, offline privacy and call-boundary tests (not biometric calibration)."""
import hashlib
import io
import struct
import unittest
import wave

from kitty_attested_live_call_v6 import verify_external_attestation
from kitty_owner_session_v6 import verify_grant
from kitty_owner_voice_auth_issuer_v6 import VoiceOwnerIssuer

GRANT = b"voice-owner-grant-separate-issuer-32-bytes!!"
TURN = b"voice-owner-turn-separate-issuer-32-bytes!!!"
SESSION = "authenticated-provider-session-123456"


def wav_sample(seed):
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b"".join(
            struct.pack("<h", 2600 if (i + seed) % (100 + seed) < 50 else -2600)
            for i in range(32000)))
    return output.getvalue()


class VoiceOwnerIssuerTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_900_000_000
        self.policy = {
            "voice_owner_auth_consent": True,
            "voice_owner_auth_min_score": 0.975,
            "voice_owner_auth_min_margin": 0.11,
            "owner_enrollment_id": "person:shana",
            "model_id": "pinned-model-v6",
            "memory_authorization": False,
            "anchor_embeddings": [[1], [1], [1]],
        }
        self.records = {}
        self.guess = {
            "source": "issuer_local_model",
            "model_id": "pinned-model-v6",
            "speaker_id": "person:shana",
            "candidate_only": False,
            "score": 0.989,
            "runner_up_score": 0.60,
        }
        self.issuer = VoiceOwnerIssuer(
            profile_loader=lambda: self.policy,
            capture_lookup=lambda session, item: self.records[item],
            score_audio=lambda wav: self.guess,
            grant_secret=GRANT, turn_secret=TURN, clock=lambda: self.now)
        self.assertTrue(self.issuer.begin_call(SESSION))

    def utterance(self, n, words="Tell me my personal plan", *, wav=None, **changes):
        item = "provider-item-" + str(n)
        self.records[item] = {
            "source": "gateway_observed_s3_microphone",
            "authenticated_s3_session": True,
            "final_transcript": True,
            "overlap": False,
            "playback_active": False,
            "session_id": SESSION,
            "item_id": item,
            "transcript": words,
            "wav": wav if wav is not None else wav_sample(n),
            "captured_at": self.now,
        }
        self.records[item].update(changes)
        return self.issuer.verify_microphone_turn(item)

    def warmed(self):
        self.assertIsNone(self.utterance(1))
        self.now += 3
        self.assertIsNone(self.utterance(2, "My name is Shana"))
        self.now += 3
        return self.utterance(3)

    def test_three_distinct_trusted_turns_issue_audio_bound_proof(self):
        result = self.warmed()
        self.assertIsNotNone(result)
        self.assertEqual(result["speaker_id"], "person:owner")
        self.assertFalse(result["name_corrob"])
        self.assertTrue(verify_grant(
            GRANT, result["owner_grant"], SESSION, now=self.now))
        self.assertEqual(verify_external_attestation(
            TURN, result["turn_attestation"], session_id=SESSION,
            item_id="provider-item-3", transcript="Tell me my personal plan",
            audio_sha256=result["audio_sha256"], now=self.now),
            ("person:owner", "owner"))
        self.assertIsNone(verify_external_attestation(
            TURN, result["turn_attestation"], session_id=SESSION,
            item_id="provider-item-3", transcript="Tell me my personal plan",
            audio_sha256="0" * 64, now=self.now))
        self.assertIsNone(verify_external_attestation(
            TURN, result["turn_attestation"], session_id=SESSION,
            item_id="provider-item-99", transcript="Tell me my personal plan",
            audio_sha256=result["audio_sha256"], now=self.now))
        self.assertIsNotNone(self.utterance(4))

    def test_name_only_or_probable_conversation_threshold_never_grants(self):
        self.guess["score"] = 0.960
        for n in (1, 2, 3, 4):
            self.assertIsNone(self.utterance(n, "I am Shana"))
        self.guess["score"] = 0.989
        self.guess["speaker_id"] = "person:guest"
        for n in (5, 6, 7):
            self.assertIsNone(self.utterance(n, "My name is Shana"))
        self.guess["speaker_id"] = "person:shana"
        self.assertIsNone(self.utterance(8, "I am Shana"))
        self.assertIsNone(self.utterance(9))
        self.assertIsNotNone(self.utterance(10, "I am Shana"))

    def test_replay_same_audio_and_echo_revoke_accumulated_matches(self):
        sample = wav_sample(1)
        self.assertIsNone(self.utterance(1, wav=sample))
        self.assertIsNone(self.utterance(2, wav=sample))
        self.assertIsNone(self.utterance(3))
        self.assertIsNone(self.utterance(4))
        self.assertIsNotNone(self.utterance(5))
        self.assertIsNone(self.utterance(6, playback_active=True))
        self.assertIsNone(self.utterance(7))
        self.assertIsNone(self.utterance(8))
        self.assertIsNotNone(self.utterance(9))

    def test_expired_capture_unknown_speaker_and_caller_metadata_rejected(self):
        self.assertIsNone(self.utterance(1))
        self.assertIsNone(self.utterance(2, authenticated_s3_session=False))
        self.assertIsNone(self.utterance(3, captured_at=self.now-13))
        self.assertIsNone(self.utterance(4))
        self.guess["candidate_only"] = True
        self.assertIsNone(self.utterance(5))
        self.guess["candidate_only"] = False
        self.assertIsNone(self.utterance(6))
        self.guess["runner_up_score"] = 0.955
        self.assertIsNone(self.utterance(7))
        self.guess["runner_up_score"] = 0.6
        self.assertIsNone(self.utterance(8))

    def test_interrupt_switch_disconnect_and_duplicate_item(self):
        self.assertIsNone(self.utterance(1))
        self.issuer.interrupt()
        self.assertIsNone(self.utterance(2))
        self.assertIsNone(self.issuer.verify_microphone_turn("provider-item-2"))
        self.assertIsNone(self.utterance(3))
        self.assertIsNone(self.utterance(4))
        self.assertIsNotNone(self.utterance(5))
        self.issuer.end_call()
        self.assertIsNone(self.utterance(6))
        self.assertTrue(self.issuer.begin_call("another-provider-session-0001"))
        self.assertIsNone(self.issuer.verify_microphone_turn("provider-item-6"))

    def test_opt_in_revoke_bad_policy_and_time_gap(self):
        self.assertIsNone(self.utterance(1))
        self.policy["voice_owner_auth_consent"] = False
        self.assertIsNone(self.utterance(2))
        self.policy["voice_owner_auth_consent"] = True
        self.assertIsNone(self.utterance(3))
        self.now += 91
        self.assertIsNone(self.utterance(4))
        self.assertIsNone(self.utterance(5))
        self.assertIsNotNone(self.utterance(6))
        self.policy["voice_owner_auth_min_score"] = 0.960
        self.assertIsNone(self.utterance(7))
        self.assertFalse(self.issuer.begin_call(SESSION))

    def test_ticket_expiry_independent_key_and_bad_source(self):
        result = self.warmed()
        self.assertIsNone(verify_external_attestation(
            TURN, result["turn_attestation"], session_id=SESSION,
            item_id="provider-item-3", transcript="Tell me my personal plan",
            audio_sha256=result["audio_sha256"], now=self.now+11))
        self.assertFalse(verify_grant(
            TURN, result["owner_grant"], SESSION, now=self.now))
        self.assertIsNone(self.utterance(4, source="untrusted_phone_json"))

    def test_malformed_configuration_requires_explicit_consent(self):
        self.policy["owner_enrollment_id"] = "person:guest"
        self.assertFalse(self.issuer.begin_call(SESSION))
        with self.assertRaises(ValueError):
            VoiceOwnerIssuer(profile_loader=lambda:{}, capture_lookup=lambda *_:None,
                score_audio=lambda _:None, grant_secret=GRANT, turn_secret=GRANT)


if __name__ == "__main__":
    unittest.main()
