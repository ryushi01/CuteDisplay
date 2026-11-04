#!/usr/bin/env python3
"""Offline no-audio-service tests for automatic post-call owner adaptation."""
import copy
import hashlib
import math
import unittest
from datetime import datetime, timezone

from kitty_attested_live_call_v6 import issue_external_attestation
from kitty_owner_session_v6 import issue_grant
from kitty_owner_voice_postcall_v6 import PostCallOwnerVoiceLearner
from test_kitty_voice_learning_v6 import clean_wav, vector, SIGNER, OWNER, MODEL, OWNER_PROFILE


class PostCallLearningTests(unittest.TestCase):
    def setUp(self):
        self.wall=1900000000
        self.mono=1000.
        self.call="verified-session-123456789"
        self.profile={
            "consent":"local_explicit_enrollment",
            "adaptive_learning_consent":True,
            "owner_enrollment_id":OWNER_PROFILE,
            "model_id":MODEL,
            "anchor_embeddings":[vector(0,0.02),vector(0,0.04),vector(0,0.07)],
            "adaptive_embeddings":[],
        }
        self.saved=0
        self.embedded=0
        def embed(_wav):
            self.embedded+=1
            return vector(0,0.04)
        def save(original,updated):
            if original!=self.profile:
                return False
            self.saved+=1
            self.profile=copy.deepcopy(updated)
            return True
        self.worker=PostCallOwnerVoiceLearner(
            enabled=True, attestation_secret=SIGNER,owner_grant_secret=OWNER,
            model_id=MODEL,owner_profile_id=OWNER_PROFILE,
            load_profile=lambda:copy.deepcopy(self.profile),
            save_profile=save,embedding_fn=embed,
            other_profiles_fn=lambda:(),
            wall_clock=lambda:self.wall,monotonic=lambda:self.mono)
        self.audio=clean_wav()
        self.transcript="I decided to keep Bluetooth on the C5."
        self.item="item-1"

    def proof(self, speaker="person:owner", role="owner", *, transcript=None, audio=None):
        text=self.transcript if transcript is None else transcript
        data=self.audio if audio is None else audio
        ticket=issue_external_attestation(
            SIGNER,session_id=self.call,item_id=self.item,transcript=text,
            speaker_id=speaker,speaker_role=role,now=self.wall,
            audio_sha256=hashlib.sha256(data).hexdigest())
        grant=issue_grant(OWNER,True,self.call,now=self.wall,ttl=120)
        return ticket,grant

    def offer(self, *, ticket=None, grant=None, audio=None, transcript=None):
        candidate, approved=self.proof()
        return self.worker.offer_verified_owner_turn(
            session_id=self.call,item_id=self.item,
            transcript=self.transcript if transcript is None else transcript,
            microphone_wav=self.audio if audio is None else audio,
            attestation=candidate if ticket is None else ticket,
            owner_grant=approved if grant is None else grant)

    def test_learns_after_call_not_in_live_audio_handler(self):
        self.assertTrue(self.worker.begin_call(self.call))
        self.assertTrue(self.offer())
        self.assertEqual(self.saved,0)
        self.assertEqual(self.embedded,0)
        self.assertEqual(self.worker.outcome,"queued")
        self.assertTrue(self.worker.finish_call(background=False))
        self.assertEqual(self.worker.outcome,"learned")
        self.assertEqual(self.saved,1)
        self.assertEqual(self.embedded,1)
        self.assertEqual(len(self.profile["adaptive_embeddings"]),1)
        self.assertEqual(self.worker._pending,None)

    def test_one_pending_sample_per_call_no_wav_history(self):
        self.worker.begin_call(self.call)
        self.assertTrue(self.offer())
        self.item="item-2"
        self.audio=clean_wav(8100)
        self.assertTrue(self.offer())
        self.assertEqual(self.worker._count,2)
        self.assertEqual(self.embedded,0)
        self.assertTrue(self.worker.finish_call(background=False))
        self.assertEqual(len(self.profile["adaptive_audio_hashes"]),1)
        self.assertEqual(self.worker._pending,None)

    def test_unknown_guest_and_cancel_do_not_train(self):
        self.worker.begin_call(self.call)
        guest,_=self.proof(speaker="person:aki",role="guest")
        self.assertFalse(self.offer(ticket=guest))
        self.assertEqual(self.embedded,0)
        self.assertTrue(self.offer())
        self.worker.cancel()
        self.assertFalse(self.worker.finish_call(background=False))
        self.assertEqual(self.saved,0)

    def test_client_claim_and_owner_session_grant_not_enough(self):
        self.worker.begin_call(self.call)
        _,grant=self.proof()
        self.assertFalse(self.offer(ticket="voice_probable",grant=grant))
        self.assertFalse(self.worker.finish_call(background=False))
        self.assertEqual(self.saved,0)

    def test_audio_substitution_and_unrelated_call_rejected(self):
        self.worker.begin_call("unrelated-session-0001")
        self.assertFalse(self.offer())
        self.worker.begin_call(self.call)
        self.assertFalse(self.offer(audio=clean_wav(6000)))
        self.assertFalse(self.worker.finish_call(background=False))

    def test_consent_revoke_before_processing_prevents_write(self):
        self.worker.begin_call(self.call)
        self.assertTrue(self.offer())
        self.profile["adaptive_learning_consent"]=False
        self.assertFalse(self.worker.finish_call(background=False))
        self.assertEqual(self.saved,0)

    def test_consent_absent_at_call_start_never_retains_microphone_audio(self):
        self.profile["adaptive_learning_consent"]=False
        self.assertFalse(self.worker.begin_call(self.call))
        self.assertFalse(self.offer())
        self.assertIsNone(self.worker._pending)
        self.assertFalse(self.worker.finish_call(background=False))

    def test_cancel_during_attestation_validation_cannot_queue_late_sample(self):
        from unittest import mock
        self.assertTrue(self.worker.begin_call(self.call))
        def late_verdict(*args,**kwargs):
            self.worker.cancel()
            return ("person:owner","owner")
        with mock.patch("kitty_owner_voice_postcall_v6.verify_external_attestation",
                        side_effect=late_verdict):
            self.assertFalse(self.offer())
        self.assertIsNone(self.worker._pending)
        self.assertFalse(self.worker.finish_call(background=False))
        self.assertEqual(self.saved,0)

    def test_stale_samples_are_discarded(self):
        self.worker.begin_call(self.call)
        self.assertTrue(self.offer())
        self.mono+=14401
        self.assertFalse(self.worker.finish_call(background=False))
        self.assertEqual(self.saved,0)

    def test_disabled_default_does_not_accept_or_persist_samples(self):
        worker=PostCallOwnerVoiceLearner(
            enabled=False,attestation_secret=SIGNER,
            owner_grant_secret=OWNER,model_id=MODEL,
            owner_profile_id=OWNER_PROFILE,
            load_profile=lambda:self.profile,save_profile=lambda a,b:True)
        self.assertFalse(worker.begin_call(self.call))
        self.assertFalse(worker.offer_verified_owner_turn(
            session_id=self.call,item_id=self.item,
            transcript=self.transcript,microphone_wav=self.audio,
            attestation=self.proof()[0],owner_grant=self.proof()[1]))
        self.assertFalse(worker.finish_call(background=False))
        self.assertEqual(worker.outcome,"disabled")


if __name__=="__main__":
    unittest.main()
