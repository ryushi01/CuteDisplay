"""Fail-closed, disposable authorization state for Kitty V6 realtime memory.

This module never authenticates an owner. It prevents late or cross-turn
speaker recognition and semantic recall from being accepted by a gateway.
No transcript, voice sample, or memory is persisted here.
"""
import re
import time

ITEM = re.compile(r"^[A-Za-z0-9_-]{1,160}$")
SPEAKER = re.compile(r"^person:[A-Za-z0-9_-]{1,48}$")


class MemoryTurnGate:
    def __init__(self, *, clock=time.monotonic, ttl=15.0):
        self._clock = clock
        self._ttl = min(max(float(ttl), 0.25), 30.0)
        self._epoch = 0
        self._item = None
        self._started = 0.0
        self._speaker = None
        self._provenance = None
        self._consumed = False

    def invalidate(self):
        """Use on speech-start, barge-in, disconnect, or response cancellation."""
        self._epoch += 1
        self._item = None
        self._speaker = None
        self._provenance = None
        self._consumed = False

    def begin(self, item_id):
        self.invalidate()
        if not isinstance(item_id, str) or not ITEM.fullmatch(item_id):
            return None
        self._item = item_id
        self._started = self._clock()
        return self._epoch

    def accept_speaker(self, epoch, item_id, speaker_id, confidence):
        if not self._valid(epoch, item_id):
            return False
        if confidence != "probable" or not isinstance(speaker_id, str) or not SPEAKER.fullmatch(speaker_id):
            self._speaker = None
            self._provenance = None
            return False
        if self._speaker is not None and self._speaker != speaker_id:
            self.invalidate()
            return False
        self._speaker = speaker_id
        self._provenance = "voice_probable"
        return True

    def allow_recall(self, epoch, item_id, speaker_id):
        return (self._valid(epoch, item_id) and self._speaker == speaker_id
                and self._provenance == "voice_probable" and not self._consumed)

    def consume_context(self, epoch, item_id, speaker_id, value):
        """Return context once, only if still authorized for this exact turn."""
        if not self.allow_recall(epoch, item_id, speaker_id):
            return ""
        self._consumed = True
        if not isinstance(value, str) or not value.strip():
            return ""
        return value[:1800]

    def _valid(self, epoch, item_id):
        if (type(epoch) is not int or epoch != self._epoch or
                self._item is None or item_id != self._item):
            return False
        if self._clock() - self._started >= self._ttl:
            self.invalidate()
            return False
        return True
