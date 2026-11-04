#!/usr/bin/env python3
"""Offline proof tests; never reads real owner keys or microphone recordings."""
import base64
import hashlib
import unittest

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from kitty_attested_live_call_v6 import (
    verify_external_attestation,
)
from kitty_owner_voice_review_issuer_v6 import (
    OwnerVoiceLearningApproval, review_message,
)
from test_kitty_voice_learning_v6 import clean_wav


LEARNING_KEY = b"independent-review-learning-issuer-32bytes"
SESSION_ID = "trusted-gateway-session-123456789"
ITEM_ID = "provider-item-005"


class ReviewIssuerTests(unittest.TestCase):
    def setUp(self):
        self.now=1900000000
        self.key=ec.generate_private_key(ec.SECP256R1())
        self.public=self.key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo)
        self.consent=True
        self.record={
            "session_id": SESSION_ID, "item_id": ITEM_ID,
            "source":"gateway_observed_s3_microphone",
            "final_transcript":True, "overlap":False,
            "playback_active":False,
            "wav":clean_wav(7000),
            "transcript":"We decided to keep Bluetooth on the C5.",
        }
        self.issuer=OwnerVoiceLearningApproval(
            enrolled_public_key_pem=self.public,
            learning_signer_secret=LEARNING_KEY,
            capture_lookup=lambda s,i: self.record if (
                s==SESSION_ID and i==ITEM_ID) else None,
            consent_check=lambda:self.consent,
            wall_clock=lambda:self.now)

    def sign(self,review):
        message=review_message(
            review["session_id"], review["item_id"],
            review["audio_sha256"],review["transcript_sha256"],
            review["nonce"])
        return base64.urlsafe_b64encode(
            self.key.sign(message,ec.ECDSA(hashes.SHA256()))).decode().rstrip("=")

    def approve(self,review,signature=None):
        return self.issuer.approve_review(
            session_id=SESSION_ID,item_id=ITEM_ID,
            nonce=review["nonce"],
            signature=self.sign(review) if signature is None else signature)

    def test_review_is_learning_only_never_unlocks_private_semantic_turn(self):
        review=self.issuer.request_review(SESSION_ID,ITEM_ID)
        self.assertIsNotNone(review)
        ticket=self.approve(review)
        self.assertIsInstance(ticket,str)
        kwargs={"session_id":SESSION_ID, "item_id":ITEM_ID,
                "transcript":self.record["transcript"],
                "audio_sha256":hashlib.sha256(
                    self.record["wav"]).hexdigest(), "now":self.now}
        self.assertIsNone(verify_external_attestation(
            LEARNING_KEY,ticket,**kwargs))
        self.assertEqual(verify_external_attestation(
            LEARNING_KEY,ticket,purpose="learning",**kwargs),
            ("person:owner","owner"))
        self.assertIsNone(self.approve(review)) # single use

    def test_modified_audio_and_transcript_never_train(self):
        review=self.issuer.request_review(SESSION_ID,ITEM_ID)
        self.record["wav"]=clean_wav(7500)
        self.assertIsNone(self.approve(review))
        review=self.issuer.request_review(SESSION_ID,ITEM_ID)
        self.record["transcript"]="Different words."
        self.assertIsNone(self.approve(review))

    def test_reviewer_key_and_challenge_nonce_must_be_correct(self):
        review=self.issuer.request_review(SESSION_ID,ITEM_ID)
        bad=ec.generate_private_key(ec.SECP256R1())
        sig=base64.urlsafe_b64encode(
            bad.sign(review_message(
                SESSION_ID,ITEM_ID,review["audio_sha256"],
                review["transcript_sha256"],review["nonce"]),
                ec.ECDSA(hashes.SHA256()))).decode().rstrip("=")
        self.assertIsNone(self.approve(review,signature=sig))
        self.assertIsNone(self.approve(review))
        review2=self.issuer.request_review(SESSION_ID,ITEM_ID)
        self.now+=61
        self.assertIsNone(self.approve(review2))

    def test_consent_revoked_before_signature_prevents_approval(self):
        review=self.issuer.request_review(SESSION_ID,ITEM_ID)
        self.consent=False
        self.assertIsNone(self.approve(review))
        self.assertIsNone(self.issuer.request_review(SESSION_ID,ITEM_ID))

    def test_guest_playback_overlap_or_untrusted_source_refused(self):
        for key,value in [
            ("source","s3_client_json"),
            ("final_transcript",False),
            ("overlap",True),
            ("playback_active",True),
            ("session_id","different-session")]:
            previous=self.record[key]
            self.record[key]=value
            self.assertIsNone(self.issuer.request_review(SESSION_ID,ITEM_ID))
            self.record[key]=previous

    def test_unsafe_audio_quality_refused(self):
        self.record["wav"]=clean_wav(0)
        self.assertIsNone(self.issuer.request_review(SESSION_ID,ITEM_ID))

    def test_wrong_session_or_item_denied(self):
        self.assertIsNone(self.issuer.request_review("another-session-00001",ITEM_ID))
        self.assertIsNone(self.issuer.request_review(SESSION_ID,"other-item"))
        review=self.issuer.request_review(SESSION_ID,ITEM_ID)
        self.assertIsNone(self.issuer.approve_review(
            session_id="wrong-session-00001",item_id=ITEM_ID,
            nonce=review["nonce"],signature=self.sign(review)))

    def test_clear_revokes_review(self):
        review=self.issuer.request_review(SESSION_ID,ITEM_ID)
        self.issuer.clear()
        self.assertIsNone(self.approve(review))


if __name__=="__main__":
    unittest.main()
