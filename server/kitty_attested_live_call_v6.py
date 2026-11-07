#!/usr/bin/env python3
"""Opt-in, memory-only bridge for independently attested live Kitty turns.

NEVER wire this to a client-supplied speaker label, owner session grant alone,
voice_probable result, or transcript self-introduction. An independent trusted
speaker verifier must issue a short-lived HMAC attestation for the exact
gateway-generated session, upstream item ID, and completed transcript digest.
The signer and its secret are NOT installed in the live gateway; this module
does not claim to implement verified speaker recognition.

No HTTP, filesystem writes, Mac inference, S3 flash or audio callbacks.
"""
import base64
import hashlib
import hmac
import json
import re
import secrets
import time

from kitty_live_rolling_context_v6 import LiveCallContinuity

AUDIENCE = "kitty-verified-spoken-turn-v6"
LEARNING_AUDIENCE = "kitty-verified-voice-learning-v6"
RESERVED_OWNER_LOCAL_ID = "person:attested_owner_local"
ITEM = re.compile(r"[A-Za-z0-9_-]{1,160}\Z")
PERSON = re.compile(r"person:[A-Za-z0-9_-]{1,48}\Z")
SESSION = re.compile(r"[A-Za-z0-9_-]{16,100}\Z")
MAX_TURN_BYTES = 1200
MAX_TURNS_PER_CALL = 2048
MAX_WAITING_TURNS = 8
MAX_TICKET_TTL = 15
AUDIO_HASH = re.compile(r"[0-9a-f]{64}\Z")


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decode(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 1024:
        raise ValueError("bad token")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _digest(transcript):
    if not isinstance(transcript, str):
        return None
    raw = transcript.encode("utf-8")
    if not raw.strip() or len(raw) > MAX_TURN_BYTES:
        return None
    return hashlib.sha256(raw).hexdigest()


def issue_external_attestation(secret, *, session_id, item_id, transcript,
                               speaker_id, speaker_role, now=None, ttl=10,
                               audio_sha256=None, purpose="turn"):
    """Issuer-side protocol helper ONLY; caller must verify a human separately.

    This function is not a speaker classifier and is never invoked by the
    gateway. Secret possession authenticates the issuer, not the microphone.
    """
    digest = _digest(transcript)
    if (not isinstance(secret, bytes) or len(secret) < 32
            or not isinstance(session_id, str) or not SESSION.fullmatch(session_id)
            or not isinstance(item_id, str) or not ITEM.fullmatch(item_id)
            or not isinstance(speaker_id, str) or not PERSON.fullmatch(speaker_id)
            or (speaker_role, speaker_id) not in (("owner", "person:owner"),)
                and (speaker_role != "guest" or speaker_id in
                     ("person:owner", RESERVED_OWNER_LOCAL_ID))
            or (audio_sha256 is not None and (
                not isinstance(audio_sha256, str)
                or not AUDIO_HASH.fullmatch(audio_sha256)))
            or purpose not in ("turn", "learning")
            or (purpose == "learning" and audio_sha256 is None)
            or digest is None or type(ttl) is not int
            or not 1 <= ttl <= MAX_TICKET_TTL):
        raise ValueError("invalid attestation")
    now = int(time.time() if now is None else now)
    fields = {
        "aud": AUDIENCE if purpose == "turn" else LEARNING_AUDIENCE,
        "sid": session_id,
        "item": item_id,
        "digest": digest,
        "speaker": speaker_id,
        "role": speaker_role,
        "iat": now,
        "exp": now + ttl,
        "nonce": secrets.token_urlsafe(12),
    }
    if audio_sha256 is not None:
        # The independent issuer must have verified these exact microphone
        # bytes, not merely signed a voice classification or transcript.
        fields["audio_sha256"] = audio_sha256
    body = _b64(json.dumps(fields, sort_keys=True, separators=(",", ":")).encode())
    signature = _b64(hmac.new(secret, body.encode("ascii"), hashlib.sha256).digest())
    return body + "." + signature


def verify_external_attestation(secret, ticket, *, session_id, item_id,
                                transcript, now=None, audio_sha256=None,
                                purpose="turn"):
    """Return signed speaker/role ONLY for the explicitly named purpose."""
    digest = _digest(transcript)
    if (not isinstance(secret, bytes) or len(secret) < 32
            or not isinstance(ticket, str) or len(ticket) > 1024
            or not isinstance(session_id, str) or not SESSION.fullmatch(session_id)
            or not isinstance(item_id, str) or not ITEM.fullmatch(item_id)
            or purpose not in ("turn","learning")
            or (purpose == "learning" and audio_sha256 is None)
            or digest is None
            or (audio_sha256 is not None and (
                not isinstance(audio_sha256, str)
                or not AUDIO_HASH.fullmatch(audio_sha256)))):
        return None
    try:
        parts = ticket.split(".")
        if len(parts) != 2:
            return None
        body, signature = parts
        expected = _b64(hmac.new(secret, body.encode("ascii"),
                                 hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        obj = json.loads(_decode(body))
        now = int(time.time() if now is None else now)
        audience=AUDIENCE if purpose=="turn" else LEARNING_AUDIENCE
        if (not isinstance(obj, dict) or obj.get("aud") != audience
                or obj.get("sid") != session_id or obj.get("item") != item_id
                or obj.get("digest") != digest
                or (obj.get("audio_sha256") is not None and
                    obj.get("audio_sha256") != audio_sha256)
                or (audio_sha256 is not None and
                    obj.get("audio_sha256") != audio_sha256)
                or type(obj.get("iat")) is not int
                or type(obj.get("exp")) is not int
                or not obj["iat"] <= now < obj["exp"]
                or not 0 < obj["exp"] - obj["iat"] <= MAX_TICKET_TTL
                or not isinstance(obj.get("nonce"), str)
                or not 10 <= len(obj["nonce"]) <= 64):
            return None
        speaker = obj.get("speaker")
        role = obj.get("role")
        if not isinstance(speaker, str) or not PERSON.fullmatch(speaker):
            return None
        if (role == "owner" and speaker == "person:owner") or (
                role == "guest" and speaker not in
                ("person:owner", RESERVED_OWNER_LOCAL_ID)):
            return speaker, role
    except (ValueError, TypeError, UnicodeError, OverflowError):
        pass
    return None


class AttestedLiveCall:
    """One gateway-side call; default has NO signer/owner authorization.

    Only pass events from the authenticated upstream provider socket.
    In particular do not call observed_transcript() using an S3 or phone
    JSON speaker claim. The private transcript is held only in bounded RAM.
    """

    def __init__(self, *, attestation_secret=None, owner_grant_secret=None,
                 clock=time.monotonic, wall_clock=time.time,
                 max_context_bytes=1000):
        self._secret = (attestation_secret
                        if isinstance(attestation_secret, bytes)
                        and len(attestation_secret) >= 32 else None)
        self._owner_secret = (owner_grant_secret
                             if isinstance(owner_grant_secret, bytes)
                             and len(owner_grant_secret) >= 32
                             and owner_grant_secret != self._secret else None)
        self._clock = clock
        self._wall_clock = wall_clock
        self._session_id = secrets.token_urlsafe(24)
        self._continuity = LiveCallContinuity(max_context_bytes=max_context_bytes)
        self._continuity.begin_call(self._session_id)
        self._stopped = None
        self._waiting = {}
        self._seen = set()
        self._current = None
        self._generation = 0
        self._closed = False

    @property
    def session_id(self):
        return self._session_id

    def _clear_notes(self):
        self._generation += 1
        self._waiting.clear()
        self._continuity.begin_call(self._session_id)
        self._current = None

    def upstream_speech_started(self):
        """Invalidate pending retrieval on a new speaker; retain notes until verified."""
        self._stopped = None
        self._waiting.clear()  # Never apply a late verdict during another utterance.
        self._generation += 1
        self._current = None

    def upstream_speech_stopped(self, item_id):
        if self._closed or not isinstance(item_id, str) or not ITEM.fullmatch(item_id):
            self._stopped = None
            self._clear_notes()
            return False
        if item_id in self._seen:
            self._stopped = None
            self._clear_notes()
            return False
        self._stopped = item_id
        self._current = None
        return True

    def upstream_transcript_completed(self, item_id, transcript):
        if (self._closed or self._stopped is None
                or not isinstance(item_id, str) or not ITEM.fullmatch(item_id)
                or item_id != self._stopped or _digest(transcript) is None
                or item_id in self._seen
                or len(self._seen) >= MAX_TURNS_PER_CALL):
            self._stopped = None
            self._clear_notes()
            return False
        self._stopped = None
        if self._secret is None:
            self._clear_notes()
            return False
        if len(self._waiting) >= MAX_WAITING_TURNS:
            self._waiting.clear()
            self._clear_notes()
            return False
        self._waiting[item_id] = (transcript, self._clock())
        self._seen.add(item_id)
        return True

    def verify_turn(self, item_id, signed_attestation, *, owner_grant=None,
                    audio_sha256=None):
        """Authorize an exact turn using a signed ticket and valid owner grant."""
        self._current = None
        waiting = self._waiting.pop(item_id, None)
        if self._closed or waiting is None or self._secret is None:
            self._clear_notes()
            return False
        transcript, recorded_at = waiting
        if self._clock() - recorded_at > MAX_TICKET_TTL:
            self._clear_notes()
            return False
        verified = verify_external_attestation(
            self._secret, signed_attestation, session_id=self._session_id,
            item_id=item_id, transcript=transcript, now=self._wall_clock(),
            audio_sha256=audio_sha256)
        if verified is None:
            self._clear_notes()
            return False
        speaker, role = verified
        if role == "owner":
            # The owner grant may follow enrolled phone proof or the explicit
            # voice-only issuer policy. Neither mere voice probability nor
            # a claimed name can issue that grant or a trusted turn ticket.
            if not self._owner_secret:
                self._clear_notes()
                return False
            from kitty_owner_session_v6 import verify_grant
            if not verify_grant(self._owner_secret, owner_grant,
                                self._session_id, now=self._wall_clock()):
                self._clear_notes()
                return False
        # The rolling buffer uses guest-role storage for this one call only.
        # For a verified owner, use a local-only pseudonym: do NOT store under
        # or search any guest's persistent semantic identity.
        local_speaker = (RESERVED_OWNER_LOCAL_ID if role == "owner" else speaker)
        attribution = {
            "session_id": self._session_id, "item_id": item_id,
            "speaker_id": local_speaker, "speaker_role": "guest",
            "provenance": "session_verified",
        }
        if not self._continuity.observe(transcript, attribution,
                                        trusted_item_id=item_id):
            self._clear_notes()
            return False
        self._generation += 1
        # Retain only this current signed ticket in volatile call RAM; it is
        # bound to the exact provider item and expires quickly.
        self._current = (item_id, attribution, role, transcript,
                         signed_attestation if role == "owner" else None,
                         audio_sha256 if role == "owner" else None)
        return True

    def context_for_verified_turn(self, item_id):
        if (self._closed or self._current is None
                or self._current[0] != item_id):
            return ""
        return self._continuity.context_for_turn(
            self._current[1], trusted_item_id=item_id)

    async def owner_history_for_verified_turn(self, item_id, service_url,
                                              service_token, owner_grant, *,
                                              lookup=None):
        """Optional owner-only historical lookup, async and late-result safe.

        A session owner grant alone is NEVER enough. The exact current item
        must already have a valid independent per-transcript attestation and
        the grant must still verify at request time and completion time.
        Do not await this helper in a realtime audio/WebSocket event callback.
        """
        current = self._current
        if (self._closed or not self._owner_secret
                or current is None or current[0] != item_id
                or current[2] != "owner"):
            return ""
        from kitty_owner_session_v6 import verify_grant
        if not verify_grant(self._owner_secret, owner_grant, self._session_id,
                            now=self._wall_clock()):
            return ""
        from kitty_semantic_async_client_v6 import (
            owner_semantic_context, _local_memory_endpoint)
        if (not _local_memory_endpoint(service_url)
                or not isinstance(service_token, str) or not service_token):
            return ""
        generation = self._generation
        query = current[3]
        try:
            executor = lookup if lookup is not None else owner_semantic_context
            evidence = {"item_id": item_id, "transcript": query,
                        "turn_attestation": current[4]}
            if current[5] is not None:
                evidence["audio_sha256"] = current[5]
            response = await executor(
                service_url, service_token, query,
                self._session_id, owner_grant, **evidence)
        except (OSError, ValueError, TypeError, TimeoutError, RuntimeError):
            return ""
        if (self._closed or self._generation != generation
                or self._current is not current
                or not verify_grant(self._owner_secret, owner_grant,
                                    self._session_id, now=self._wall_clock())):
            return ""
        return response[:1800] if isinstance(response, str) else ""

    def unknown_turn(self):
        """Guest, uncertain speaker, barge-in or cancellation; drop private notes."""
        self._waiting.clear()
        self._stopped = None
        self._clear_notes()

    def end_call(self):
        self.unknown_turn()
        self._continuity.end_call()
        self._closed = True
