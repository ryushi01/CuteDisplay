#!/usr/bin/env python3
"""Offline proof tests, cryptography installed; no real iPhone needed."""
import base64
import unittest
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec
from kitty_owner_proof_v6 import OwnerProof
from kitty_owner_session_v6 import verify_grant

class ProofTests(unittest.TestCase):
    def setUp(self):
        self.private=ec.generate_private_key(ec.SECP256R1())
        pem=self.private.public_key().public_bytes(
            serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
        self.secret=b"t"*32
        self.verifier=OwnerProof(self.secret,pem)
        self.session="owner-session-123456"
    def test_owner_proof_one_time_session_bound(self):
        ch=self.verifier.challenge(self.session,now=1000)["challenge"]
        sig=self.private.sign(OwnerProof.message(self.session,ch),ec.ECDSA(hashes.SHA256()))
        b64=base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
        grant=self.verifier.verify(self.session,ch,b64,now=1001)
        self.assertIsNotNone(grant)
        self.assertTrue(verify_grant(self.secret,grant,self.session,now=1002))
        self.assertIsNone(self.verifier.verify(self.session,ch,b64,now=1002))
    def test_bad_signature_consumes_challenge(self):
        ch=self.verifier.challenge(self.session,now=1000)["challenge"]
        self.assertIsNone(self.verifier.verify(self.session,ch,"invalid",now=1001))
        sig=self.private.sign(OwnerProof.message(self.session,ch),ec.ECDSA(hashes.SHA256()))
        b64=base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
        self.assertIsNone(self.verifier.verify(self.session,ch,b64,now=1002))
    def test_wrong_session_and_expiry(self):
        ch=self.verifier.challenge(self.session,now=1000)["challenge"]
        sig=self.private.sign(OwnerProof.message(self.session,ch),ec.ECDSA(hashes.SHA256()))
        b64=base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
        self.assertIsNone(self.verifier.verify("different-session",ch,b64,now=1001))
        ch2=self.verifier.challenge(self.session,now=1000)["challenge"]
        sig2=self.private.sign(OwnerProof.message(self.session,ch2),ec.ECDSA(hashes.SHA256()))
        b642=base64.urlsafe_b64encode(sig2).rstrip(b"=").decode()
        self.assertIsNone(self.verifier.verify(self.session,ch2,b642,now=1100))
if __name__=="__main__":unittest.main()
