#!/usr/bin/env python3
"""Short-lived owner attribution grants, issued ONLY after trusted app login.

An S3 API key proves device possession, not which human is speaking.
This module verifies cryptographic grants; it deliberately does NOT turn
audio self-identification or paired hardware into owner verification.
"""
import base64
import hashlib
import hmac
import json
import time

MAX_TTL=300

def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

def _unb64(data):
    return base64.urlsafe_b64decode(data + "="*((-len(data))%4))

def issue_grant(secret, authenticated_owner, session_id, now=None, ttl=120):
    """Call only from a server endpoint with independently verified owner login."""
    if authenticated_owner is not True:
        raise PermissionError("owner login must already be independently verified")
    if not isinstance(session_id,str) or not 8<=len(session_id)<=100:
        raise ValueError("invalid session")
    if not isinstance(secret,bytes) or len(secret)<32 or not 1<=ttl<=MAX_TTL:
        raise ValueError("invalid grant configuration")
    now=int(time.time() if now is None else now)
    payload={"sub":"person:owner","aud":"kitty-memory-v6",
             "sid":session_id,"iat":now,"exp":now+ttl}
    body=_b64(json.dumps(payload,sort_keys=True,separators=(",",":")).encode())
    sig=_b64(hmac.new(secret,body.encode("ascii"),hashlib.sha256).digest())
    return body+"."+sig

def verify_grant(secret,grant,session_id,now=None):
    if not isinstance(secret,bytes) or len(secret)<32 or not isinstance(grant,str) or len(grant)>1024:
        return False
    try:
        body,sig=grant.split(".")
        good=_b64(hmac.new(secret,body.encode("ascii"),hashlib.sha256).digest())
        if not hmac.compare_digest(sig,good):
            return False
        obj=json.loads(_unb64(body))
        now=int(time.time() if now is None else now)
        return (obj.get("aud")=="kitty-memory-v6" and obj.get("sub")=="person:owner"
                and obj.get("sid")==session_id and
                type(obj.get("iat")) is int and type(obj.get("exp")) is int
                and obj["iat"]<=now<obj["exp"] and
                0<obj["exp"]-obj["iat"]<=MAX_TTL)
    except (ValueError,TypeError,UnicodeError,KeyError):
        return False
