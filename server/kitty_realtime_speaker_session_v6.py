"""Kitty V6 server-observed microphone-to-transcription binding.

This adapter is designed to run beside (not instead of) the existing
WebSocket forwarding logic. A captured sample is usable only with the
upstream item_id associated with the same stopped utterance. No persistent
audio storage, client-provided speaker IDs, or session-global memory.
"""
import asyncio
import re
from kitty_realtime_speaker_v6 import SpeakerTurn, identify_turn

_ITEM = re.compile(r"^[A-Za-z0-9_-]{1,120}$")

class SpeakerSession:
    def __init__(self, *, identify=identify_turn):
        self._identify = identify
        self._audio = SpeakerTurn()
        self._generation = 0
        self._stopped = None
        self._task = None
        self._closed = False

    def microphone_chunk(self, encoded):
        """Observe client PCM *without changing or delaying forwarding*."""
        if not self._closed:
            self._audio.append_base64_pcm16(encoded)

    def speech_started(self):
        self._cancel()
        self._generation += 1
        self._stopped = None
        self._audio.start()

    def speech_stopped(self, *, item_id=None):
        """Freeze a bounded audio snapshot; item ID may arrive later."""
        if self._closed:
            return
        self._audio.stop()
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
