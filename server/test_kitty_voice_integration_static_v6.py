"""Static invariants for voice delegation safety; no board or service required.

These checks catch accidental reintroduction of cross-speaker context and
blocking waits. They do not replace compiling the ESP32-S3 firmware.
"""
from pathlib import Path
import unittest

FIRMWARE = Path(__file__).resolve().parents[1] / "firmware" / "CuteDisplayBrain"

class VoiceIntegrationSafety(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.voice = (FIRMWARE / "BrainRealtimeDirect.h").read_text()
        cls.chat = (FIRMWARE / "BrainAI.h").read_text()

    def test_nonblocking_delegation_grace(self):
        self.assertIn("waitingDelegationAt)>=80UL", self.voice)
        self.assertIn("ws.loop();", self.voice)
        self.assertNotIn("delay(80)", self.voice)

    def test_pending_voice_blocks_session_memory_refresh(self):
        self.assertIn("waitingDelegationId.isEmpty() && !semanticPending &&", self.voice)

    def test_exact_transcript_and_one_shot(self):
        self.assertIn("prompt==semanticTranscript", self.voice)
        # Both immediate and delayed delegation must consume the context once.
        self.assertIn("clearSemanticTurn();\n      if(!delegatedCallId.isEmpty()", self.voice)
        self.assertIn("clearSemanticTurn();\n  if(!delegatedCallId.isEmpty()", self.voice)
        self.assertIn('cJSON_AddStringToObject(m,"turn_id",turnId.c_str())', self.voice)

    def test_delegated_chat_excludes_unscoped_memory(self):
        self.assertIn("delegated?0:historyCount", self.chat)
        self.assertIn('delegated?String(""):KittyMemory::semanticFactRecall', self.chat)
        self.assertIn("if(delegated && !scopedContext.isEmpty())", self.chat)
        self.assertIn("if(!delegated){\n   rememberTurn(prompt,currentAnswer);", self.chat)

    def test_disconnect_and_failure_clear_pending_delegation(self):
        failure = self.voice.split("inline void fail(const char *why){", 1)[1].split(
            "// V6 speaker recognition", 1)[0]
        disconnect = self.voice.split("if(event==WStype_DISCONNECTED){", 1)[1].split(
            "if(event==WStype_CONNECTED)", 1)[0]
        for block in (failure, disconnect):
            self.assertIn('clearSemanticTurn();', block)
            self.assertIn('waitingDelegationId="";waitingDelegationPrompt="";waitingDelegationAt=0;', block)

    def test_new_speech_invalidates_prior_context(self):
        self.assertIn("A new utterance invalidates an earlier speaker-specific result", self.voice)
        self.assertIn("A new transcript invalidates every earlier speaker-scoped recall", self.voice)

if __name__ == "__main__":
    unittest.main()
