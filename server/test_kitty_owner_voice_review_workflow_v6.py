#!/usr/bin/env python3
"""End-to-end simulated owner review -> signed learning -> post-call profile CAS."""
import base64
import copy
import hashlib
import unittest

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from kitty_owner_session_v6 import issue_grant
from kitty_owner_voice_postcall_v6 import PostCallOwnerVoiceLearner
from kitty_owner_voice_review_issuer_v6 import (
    OwnerVoiceLearningApproval, review_message)
from kitty_owner_voice_review_workflow_v6 import ReviewedOwnerVoiceLearning
from test_kitty_voice_learning_v6 import clean_wav, vector, MODEL, OWNER_PROFILE

SIGNER=b"learning-review-signature-key-32bytes"
OWNER=b"session-owner-grant-secret-32bytes"
SESSION="gateway-session-00000012345678"
ITEM="provider-voice-01"


class ReviewedLearningE2ETests(unittest.TestCase):
    def setUp(self):
        self.now=1900000000
        self.audio=clean_wav()
        self.consent=True
        self.sample={
            "session_id":SESSION, "item_id":ITEM,
            "source":"gateway_observed_s3_microphone",
            "final_transcript":True, "overlap":False,
            "playback_active":False, "wav":self.audio,
            "transcript":"I decided to preserve the Kitty SD archive.",
        }
        self.owner_key=ec.generate_private_key(ec.SECP256R1())
        public=self.owner_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo)
        self.profile={
            "consent":"local_explicit_enrollment",
            "adaptive_learning_consent":True,
            "owner_enrollment_id":OWNER_PROFILE,
            "model_id":MODEL,
            "anchor_embeddings":[vector(0,0.02),vector(0,0.03),vector(0,0.06)],
            "adaptive_embeddings":[],
        }
        self.before=copy.deepcopy(self.profile)
        self.saved=0
        self.embeddings=0
        def profile_save(expected, updated):
            if expected!=self.profile or not self.consent:
                return False
            self.saved+=1
            self.profile=copy.deepcopy(updated)
            return True
        def embedding(_data):
            self.embeddings+=1
            return vector(0,0.05)
        self.capture=lambda sid,item: (self.sample
            if (sid,item)==(SESSION,ITEM) else None)
        self.issuer=OwnerVoiceLearningApproval(
            enrolled_public_key_pem=public,
            learning_signer_secret=SIGNER,
            capture_lookup=self.capture,
            consent_check=lambda:self.consent,
            wall_clock=lambda:self.now)
        self.learner=PostCallOwnerVoiceLearner(
            enabled=True,attestation_secret=SIGNER,
            owner_grant_secret=OWNER,
            model_id=MODEL,owner_profile_id=OWNER_PROFILE,
            load_profile=lambda:copy.deepcopy(self.profile),
            save_profile=profile_save,
            embedding_fn=embedding,
            wall_clock=lambda:self.now,
            monotonic=lambda:100.,
            other_profiles_fn=lambda:())
        self.workflow=ReviewedOwnerVoiceLearning(
            issuer=self.issuer,learner=self.learner,
            capture_lookup=self.capture)
        self.grant=issue_grant(OWNER,True,SESSION,now=self.now,ttl=120)

    def signature(self,review):
        signature=self.owner_key.sign(
            review_message(SESSION,ITEM,
                review["audio_sha256"],review["transcript_sha256"],
                review["nonce"]),ec.ECDSA(hashes.SHA256()))
        return base64.urlsafe_b64encode(signature).decode().rstrip("=")

    def test_exact_review_learns_only_after_end_of_call(self):
        self.assertTrue(self.workflow.begin_call(SESSION))
        challenge=self.workflow.request_sample_review(ITEM)
        self.assertIsNotNone(challenge)
        self.assertTrue(self.workflow.confirm_sample_review(
            ITEM,challenge["nonce"],self.signature(challenge),
            owner_session_grant=self.grant))
        self.assertEqual(self.embeddings,0)
        self.assertEqual(self.saved,0)
        self.assertTrue(self.workflow.finish_call(background=False))
        self.assertEqual(self.embeddings,1)
        self.assertEqual(self.saved,1)
        self.assertEqual(self.workflow.outcome,"learned")
        self.assertEqual(self.profile["anchor_embeddings"],
                         self.before["anchor_embeddings"])
        self.assertEqual(len(self.profile["adaptive_embeddings"]),1)
        self.assertIs(self.profile["memory_authorization"],False)
        self.assertNotIn("wav",str(self.profile).lower())

    def test_client_speaker_claim_without_user_review_never_learns(self):
        self.assertTrue(self.workflow.begin_call(SESSION))
        self.assertFalse(self.workflow.confirm_sample_review(
            ITEM,"fake-nonce","voice_probable",
            owner_session_grant=self.grant))
        self.assertFalse(self.workflow.finish_call(background=False))
        self.assertEqual(self.embeddings,0)

    def test_review_changed_audio_refused_then_discarded(self):
        self.assertTrue(self.workflow.begin_call(SESSION))
        review=self.workflow.request_sample_review(ITEM)
        self.sample["wav"]=clean_wav(6500)
        self.assertFalse(self.workflow.confirm_sample_review(
            ITEM,review["nonce"],self.signature(review),
            owner_session_grant=self.grant))
        self.assertFalse(self.workflow.finish_call(background=False))
        self.assertEqual(self.saved,0)

    def test_consent_revoked_after_review_prevents_commit(self):
        self.assertTrue(self.workflow.begin_call(SESSION))
        review=self.workflow.request_sample_review(ITEM)
        self.assertTrue(self.workflow.confirm_sample_review(
            ITEM,review["nonce"],self.signature(review),
            owner_session_grant=self.grant))
        self.consent=False
        self.profile["adaptive_learning_consent"]=False
        self.assertFalse(self.workflow.finish_call(background=False))
        self.assertEqual(self.saved,0)

    def test_wrong_owner_session_grant_denied(self):
        self.assertTrue(self.workflow.begin_call(SESSION))
        review=self.workflow.request_sample_review(ITEM)
        other=issue_grant(OWNER,True,"wrong-session-0000000000",
                          now=self.now,ttl=120)
        self.assertFalse(self.workflow.confirm_sample_review(
            ITEM,review["nonce"],self.signature(review),
            owner_session_grant=other))
        self.assertFalse(self.workflow.finish_call(background=False))

    def test_interrupt_discards_one_time_review(self):
        self.assertTrue(self.workflow.begin_call(SESSION))
        review=self.workflow.request_sample_review(ITEM)
        self.workflow.cancel()
        self.assertFalse(self.workflow.confirm_sample_review(
            ITEM,review["nonce"],self.signature(review),
            owner_session_grant=self.grant))
        self.assertFalse(self.workflow.finish_call(background=False))
        self.assertEqual(self.embeddings,0)


if __name__=="__main__":
    unittest.main()
