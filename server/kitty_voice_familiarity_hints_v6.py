#!/usr/bin/env python3
"""Short-lived, non-authorizing conversation familiarity hints for Kitty V6.

Helps Kitty react naturally to repeated likely-owner matches without giving
voice recognition permission to access private history or write owner facts.
This is NOT biometrics-based authentication, no enrollment, and never emits
person:owner or a signed speaker attestation.

Integrate ONLY after a trusted gateway CPU recognizer has produced a candidate
for its independently observed microphone item. Never read user-supplied
speaker labels, transcript contents or S3 sidecars to call observe().
No I/O, profile mutation, model inference or audio storage.
"""
import math
import re
import time

ITEM = re.compile(r"[A-Za-z0-9_-]{1,160}\Z")
CANDIDATE = "person:shana"
MIN_CONFIDENT_SCORE = 0.960
MAX_AGE_SECONDS = 180
MAX_ITEMS = 128


class CandidateFamiliarity:
    def __init__(self, *, clock=time.monotonic):
        self._clock=clock
        self._count=0
        self._last=None
        self._items=set()
        self._active=False

    def begin_call(self):
        self._count=0
        self._last=None
        self._items.clear()
        self._active=True

    def end_call(self):
        self._active=False
        self._count=0
        self._last=None
        self._items.clear()

    def interrupted(self):
        """Unknown/multiple speaker or barge-in must not inherit confidence."""
        self._count=0
        self._last=None

    def observe(self, *, provider_item_id, speaker_candidate, score,
                recognizer_source, echo_or_overlap=False):
        """Return a nonprivate hint with owner_authenticated=False ALWAYS."""
        if not self._active:
            return None
        now=self._clock()
        if (self._last is not None
                and now-self._last>MAX_AGE_SECONDS):
            self._count=0
        if (not isinstance(provider_item_id,str)
                or not ITEM.fullmatch(provider_item_id)
                or provider_item_id in self._items
                or len(self._items)>=MAX_ITEMS):
            self.interrupted()
            return None
        self._items.add(provider_item_id)
        if (recognizer_source!="trusted_gateway_cpu"
                or speaker_candidate!=CANDIDATE
                or type(score) not in (float,int)
                or not math.isfinite(score)
                or not MIN_CONFIDENT_SCORE<=score<=1.0
                or echo_or_overlap is not False):
            self.interrupted()
            return None
        self._last=now
        self._count=min(self._count+1,8)
        return {
            "candidate_speaker_id":CANDIDATE,
            "candidate_provenance":"voice_probable",
            "familiarity":"strong_hint" if self._count>=3 else "growing_hint",
            "observed_consistent_turns":self._count,
            "owner_authenticated":False,
            "private_memory_authorized":False,
            "profile_learning_authorized":False,
        }

    @property
    def owner_authenticated(self):
        return False

    @property
    def private_memory_authorized(self):
        return False
