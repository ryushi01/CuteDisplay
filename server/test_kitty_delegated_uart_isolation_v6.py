#!/usr/bin/env python3
"""Regression: realtime tool replies must not require hidden C5 AI_* ACKs.

Source-only checks. The C5 v41 standalone-chat and physical-call behavior stays
unchanged; a private S3 firmware compile/flash is a separate deliberate step.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
AI = (ROOT / "firmware/CuteDisplayBrain/BrainAI.h").read_text(encoding="utf-8")
BRAIN = (ROOT / "firmware/CuteDisplayBrain/CuteDisplayBrain.ino").read_text(encoding="utf-8")
CALL = (ROOT / "firmware/CuteDisplayBrain/BrainRealtimeDirect.h").read_text(encoding="utf-8")


class DelegatedAiUartIsolation(unittest.TestCase):
    def test_legacy_begin_and_end_only_for_standalone_chat(self):
        self.assertEqual(AI.count('if(!delegated)sendPacket("AI_BEGIN","");'), 1)
        self.assertEqual(AI.count('if(!delegated)sendPacket("AI_END","");'), 3)
        self.assertNotIn('if(!delegated)if(!delegated)', AI)

    def test_delegated_sse_still_updates_call_text_and_tool_result(self):
        stream = AI.split("inline void processSSELine(String line){", 1)[1].split("static String sseBuffer;", 1)[0]
        self.assertIn("if(callDelegated && liveTextQueue && chunk.length())", stream)
        self.assertIn("if(currentAnswer.length()<HISTORY_RESPONSE_LIMIT)", stream)
        self.assertIn("if(!callDelegated){", stream)
        guard, rest = stream.split("if(!callDelegated){", 1)
        self.assertIn("liveTextQueue", guard)
        self.assertIn("currentAnswer+=", guard)
        self.assertIn('sendPacket("AI_DATA",part)', AI)
        self.assertIn("releaseText(false);", rest)

    def test_call_delegation_result_is_independent_of_c5_uart(self):
        self.assertIn("callResultText=(!failed && doneSeen && !cancelRequested)?currentAnswer:String(\"\");", AI)
        self.assertIn("BrainAI::takeCallStream(piece)", CALL)
        self.assertIn('CuteLink::send(Serial1,++brainActivitySeq,"CALL_TEXT",caption);', BRAIN)

    def test_no_changes_to_v41_display_protocol(self):
        display = (ROOT / "firmware/CuteDisplay/lcd.ino").read_text(encoding="utf-8")
        self.assertIn('CuteLink::send(Serial1,f.seq,"ACK","AI");', display)


if __name__ == "__main__":
    unittest.main()
