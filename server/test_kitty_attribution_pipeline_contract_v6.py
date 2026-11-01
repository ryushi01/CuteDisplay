"""Static source contract for Kitty SD memory attribution boundaries.

No hardware, audio, database writes or network required.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FW = ROOT / "firmware/CuteDisplayBrain/BrainRealtimeDirect.h"
OBS = ROOT / "server/kitty_realtime_gateway_observer_v6.py"
CPU = ROOT / "server/kitty_speaker_cpu_v6.py"
REALTIME = ROOT / "server/kitty_realtime_speaker_v6.py"
ATTR = ROOT / "server/kitty_semantic_attribution_v6.py"
INDEX = ROOT / "server/kitty_sd_semantic_index.py"

class AttributionContract(unittest.TestCase):
    def test_firmware_writes_explicit_provenance(self):
        code = FW.read_text()
        self.assertIn('KittyMemory::queueAttributed(transcript', code)
        self.assertIn('KittyMemory::queueAttributed(t.transcript', code)
        self.assertIn('source="explicit_introduction"', code)
        self.assertIn('source="voice_probable"', code)
        self.assertIn('findSpeakerTurn(String(id->valuestring))', code)
        self.assertIn('clearSpeakerTurn((uint8_t)slot)', code)
        self.assertIn('const String introduction=speakerTurns[slot].intro;', code)
        self.assertIn('t.intro.isEmpty()?String("unknown")', code)
        self.assertIn('t.intro.isEmpty()?String("unverified")', code)

    def test_candidate_does_not_enter_authorized_identity(self):
        cpu = CPU.read_text()
        self.assertIn('"candidate_speaker_id": candidate', cpu)
        self.assertIn('"speaker_id":"unknown"', cpu)
        realtime = REALTIME.read_text()
        self.assertIn('"candidate_speaker_id":candidate', realtime)
        observer = OBS.read_text()
        self.assertIn('candidate = event.get("candidate_speaker_id")', observer)
        self.assertIn('self.gate.accept_speaker(self.epoch, item, sid, confidence)', observer)
        self.assertIn('"speaker_id": event.get("speaker_id", "unknown")', observer)
        self.assertIn('safe_event["candidate_speaker_id"] = candidate', observer)
        self.assertIn('safe_event["candidate_provenance"] = "voice_probable"', observer)
        self.assertIn('candidate_provenance', code := FW.read_text())
        self.assertIn('if(source=="voice_probable" && cJSON_IsString(sid)', code)
        self.assertIn('strcmp(sid->valuestring,speaker.c_str())==0', code)

    def test_unverified_history_fails_closed(self):
        attribution = ATTR.read_text()
        self.assertIn('if role=="owner":', attribution)
        self.assertIn('"provenance": "unverified"', attribution)
        index = INDEX.read_text()
        self.assertIn('if attribution["speaker_id"] != speaker_id:', index)

if __name__ == "__main__":
    unittest.main()
