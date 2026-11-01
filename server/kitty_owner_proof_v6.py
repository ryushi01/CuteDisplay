#!/usr/bin/env python3
"""Server-side enrolled-key owner proof for Kitty V6.

The administrator must pre-enroll the public key out-of-band after verifying
the owner. Neither device BLE pairing nor a claimed name enrolls a key.
Uses cryptography; runs on Ubuntu, never in the realtime audio callback.
"""
import base64
import hashlib
import secrets
import threading
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec
from kitty_owner_session_v6 import issue_grant

def _decode(s):
    return base64.urlsafe_b64decode(s+"="*((-len(s))%4))

class OwnerProof:
    def __init__(self, grant_secret:bytes, public_key_pem:bytes, ttl=60):
        key=serialization.load_pem_public_key(public_key_pem)
        if not isinstance(key,ec.EllipticCurvePublicKey) or not isinstance(key.curve,ec.SECP256R1):
            raise ValueError("Only enrolled P-256 keys are supported")
        self.key=key
        self.secret=grant_secret
        self.ttl=min(90,max(10,int(ttl)))
        self.pending={}
        self.lock=threading.Lock()

    def challenge(self, session_id:str, now=None):
        if not isinstance(session_id,str) or not 8<=len(session_id)<=100:
            raise ValueError("invalid session id")
        now=int(time.time() if now is None else now)
        nonce=secrets.token_urlsafe(32)
        with self.lock:
            self.pending={k:v for k,v in self.pending.items() if v[1]>now}
            self.pending[nonce]=(session_id,now+self.ttl)
        return {"challenge":nonce,"expires_at":now+self.ttl}

    @staticmethod
    def message(session_id,nonce):
        return ("kitty-owner-v6\n"+session_id+"\n"+nonce).encode("utf-8")

    def verify(self, session_id, nonce, signature_b64, now=None):
        now=int(time.time() if now is None else now)
        if not isinstance(nonce,str) or not isinstance(session_id,str) or not isinstance(signature_b64,str):
            return None
        with self.lock:
            entry=self.pending.pop(nonce,None)
        # Single-use even if verification failed: no replay or online guessing
        if not entry or entry[0]!=session_id or now>=entry[1]:
            return None
        try:
            signature=_decode(signature_b64)
            self.key.verify(signature,self.message(session_id,nonce),ec.ECDSA(hashes.SHA256()))
        except (InvalidSignature, ValueError, TypeError, OverflowError):
            return None
        return issue_grant(self.secret,True,session_id,now=now,ttl=120)
