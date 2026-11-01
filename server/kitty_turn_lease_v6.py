"""Fail-closed per-turn semantic context lease for Kitty V6.

A speaker's derived memory is usable only for the exact attributed turn.
Never promote it to system/session instructions or retain it after response.
This module stores no personal information on disk.
"""
from dataclasses import dataclass
from time import monotonic

@dataclass
class TurnLease:
    turn_id: str
    speaker_id: str
    context: str
    expires: float

class TurnContextGate:
    def __init__(self, *, clock=monotonic, ttl=5.0):
        self._clock = clock
        self._ttl = min(max(float(ttl), 0.1), 5.0)
        self._lease = None

    def clear(self):
        self._lease = None

    def stage(self, turn_id, speaker_id, context):
        self.clear()
        if (not isinstance(turn_id, str) or not 1 <= len(turn_id) <= 160
                or not isinstance(speaker_id, str) or not speaker_id.strip()
                or speaker_id == "unknown" or len(speaker_id) > 64
                or not isinstance(context, str) or not context.strip()):
            return False
        if any(ord(c) < 32 or ord(c) == 127 for c in turn_id + speaker_id):
            return False
        self._lease = TurnLease(turn_id, speaker_id, context[:1800],
                                self._clock() + self._ttl)
        return True

    def consume(self, turn_id, speaker_id):
        lease = self._lease
        self.clear()  # One-shot; another turn cannot inherit memory.
        if (lease is None or self._clock() >= lease.expires
                or turn_id != lease.turn_id or speaker_id != lease.speaker_id):
            return ""
        return lease.context
