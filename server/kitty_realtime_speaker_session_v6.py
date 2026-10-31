"""Kitty V6 server-observed microphone-to-transcription binding.

This adapter is designed to run beside (not instead of) the existing
WebSocket forwarding logic. A captured sample is usable only with the
upstream item_id associated with the same stopped utterance. No persistent
audio storage, client-provided speaker IDs, or session-global memory.
"""
import asyncio
import base64
import binascii
import collections
import re
from kitty_realtime_speaker_v6 import SpeakerTurn, identify_turn

_ITEM = re.compile(r"^[A-Za-z0-9_-]{1,120}$")

class SpeakerSession:
    def __init__(self, *, identify=identify_turn):
        self._identify = identify
        self._audio = SpeakerTurn()
        self._preroll = collections.deque()
        self._preroll_bytes = 0
        self._collecting = False
        self._generation = 0
        self._stopped = None
        self._task = None
        self._closed = False

    def microphone_chunk(self, encoded):
        """Observe client PCM *without changing or delaying forwarding*."""
        if self._closed:
            return
        if self._collecting:
            self._audio.append_base64_pcm16(encoded)
            return
        # VAD speech-start notifications arrive after initial PCM packets.
        # Hold bounded pre-roll only in RAM; never retain recordings.
        if not isinstance(encoded, str) or len(encoded) > 65536:
            return
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            return
        if not raw or len(raw) % 2:
            return
        self._preroll.append(raw)
        self._preroll_bytes += len(raw)
        while self._preroll_bytes > 24000:
            chunk = self._preroll.popleft()
            self._preroll_bytes -= len(chunk)

    def speech_started(self):
        self._cancel()
        self._generation += 1
        self._stopped = None
        self._audio.start()
        self._collecting = True
        for chunk in self._preroll:
            self._audio.append_base64_pcm16(base64.b64encode(chunk).decode("ascii"))
        self._preroll.clear()
        self._preroll_bytes = 0

    def speech_stopped(self, *, item_id=None):
        """Freeze a bounded audio snapshot; item ID may arrive later."""
        if self._closed:
            return
        self._audio.stop()
        self._collecting = False
        _, pcm = self._audio.snapshot()
        self._stopped = (self._generation, item_id, pcm)

    def transcription(self, item_id):
        """Assign actual upstream transcription ID; no client claim allowed."""
        if self._closed or not _ITEM.fullmatch(item_id or "") or self._stopped is None:
            return None
        gen, stopped_id, pcm = self._stopped
        if gen != self._generation or (stopped_id and stopped_id != item_id):
            return None
        self._stopped = None
        return gen, item_id, pcm

    def schedule(self, item_id, url, token, emit, *, timeout=0.9):
        """Fire and forget; a stale result never reaches S3."""
        captured = self.transcription(item_id)
        if captured is None:
            return False
        gen, verified_item, pcm = captured
        if self._task and not self._task.done():
            self._task.cancel()
        async def job():
            try:
                event = await self._identify(url, token, verified_item, pcm,
                                             timeout=timeout)
                if (event and not self._closed and self._generation == gen
                        and event.get("item_id") == verified_item):
                    await emit(event)
            except (asyncio.CancelledError, OSError, ValueError):
                return
        self._task = asyncio.create_task(job())
        return True

    def _cancel(self):
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

    def close(self):
        self._closed = True
        self._cancel()
        self._stopped = None
        self._audio.discard()
        self._collecting = False
        self._preroll.clear()
        self._preroll_bytes = 0
