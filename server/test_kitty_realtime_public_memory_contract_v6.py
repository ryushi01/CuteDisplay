#!/usr/bin/env python3
"""Fail-closed contract for realtime memory contexts on an unverified voice call.

Static source assertions intentionally avoid booting the gateway, calling Mac
models, opening the microSD, or accessing owner/private memory during tests.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
BRAIN = ROOT / "firmware" / "CuteDisplayBrain"
CONTEXT = (BRAIN / "KittyMemoryContextV6.h").read_text()
REALTIME = (BRAIN / "BrainRealtimeDirect.h").read_text()
MEMORY = (BRAIN / "KittyMemory.h").read_text()
AI = (BRAIN / "BrainMemoryAI.h").read_text()


class RealtimePublicMemoryTests(unittest.TestCase):
    def test_session_context_is_public_only(self):
        self.assertIn("inline String unverifiedCallSnapshot(", CONTEXT)
        block = CONTEXT.split("inline String unverifiedCallSnapshot(", 1)[1].split(
            "} // namespace KittyMemoryContextV6", 1)[0]
        self.assertIn("KittyMemory::shareableContext()", block)
        self.assertIn("BrainClock::calendarContext()", block)
        for forbidden in ("KittyMemory::factSummary(", "KittyMemory::latestSummaryContext(",
                          "KittyMemory::recall(", "unverified_summaries_v6.tsv",
                          "KittyMemory::requestSearch("):
            self.assertNotIn(forbidden, block, forbidden)
        self.assertIn("KittyMemory::clipUTF8(text,maxBytes)", block)

    def test_unverified_auth_and_refresh_both_use_public_context(self):
        self.assertEqual(REALTIME.count("KittyMemoryContextV6::unverifiedCallSnapshot("), 2)
        self.assertNotIn("KittyMemoryContextV6::snapshot(", REALTIME)
        self.assertIn('cJSON_AddStringToObject(auth,"kitty_sd_memory",publicMemory.c_str())', REALTIME)
        self.assertIn('cJSON_AddStringToObject(message,"memory",context.c_str())', REALTIME)
        self.assertIn("KittyMemory::sharedRevision!=memorySharedSeen", REALTIME)
        self.assertIn("memorySharedSeen=sharedVersion;", REALTIME)
        self.assertNotIn("memoryFactSeen", REALTIME)
        self.assertNotIn("memorySummarySeen", REALTIME)

    def test_owner_facts_and_unverified_summaries_remain_separate(self):
        self.assertIn('"/kitty/unverified_summaries_v6.tsv"', MEMORY)
        self.assertIn("if(summary.ownerVerified && !item.isEmpty() && cacheMutex", MEMORY)
        self.assertIn("if(!e.ownerVerified){", MEMORY)
        self.assertIn("if(!summarize && cJSON_IsArray(facts)", AI)
        self.assertIn("static volatile uint32_t sharedRevision=0;", MEMORY)

    def test_no_extra_inference_or_audio_modification_needed(self):
        self.assertIn("KittyMemory::shareableContext()", CONTEXT)
        self.assertIn("memoryRefreshSupported && !remoteResponse", REALTIME)
        self.assertIn("BrainRealtimeAudio::hasSpeakerAudio()", REALTIME)
        self.assertNotIn("esp_http_client", CONTEXT)
        self.assertNotIn("SD_MMC.open(", CONTEXT)


if __name__ == "__main__":
    unittest.main()
