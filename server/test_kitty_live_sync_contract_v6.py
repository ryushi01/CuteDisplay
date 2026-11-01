"""Static checks for live, non-blocking Kitty microSD sync behavior."""
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class LiveSyncContract(unittest.TestCase):
    def test_call_is_not_global_sync_blocker(self):
        main=(ROOT/"firmware/CuteDisplayBrain/CuteDisplayBrain.ino").read_text()
        a=main.index("KittyMemorySyncV6::init([]")
        b=main.index("BrainRealtimeDirect::init();", a)
        block=main[a:b]
        self.assertIn("return !BrainC5OTA::updating();",block)
        self.assertIn("KittyMemorySyncV6::setCallActive",block)
        self.assertIn("KittyMemorySyncV6::setSpeechActive",block)
    def test_paced_and_fast_retry(self):
        code=(ROOT/"firmware/CuteDisplayBrain/KittyMemorySyncV6.h").read_text()
        self.assertIn("callActive && callActive()?750:12",code)
        self.assertIn("FAILURE_RETRY_MS=15000UL",code)
        self.assertIn("IDLE_QUIET_MS=500UL",code)
        self.assertIn("KittyMemory::requestExport(i,offset)",code)
        self.assertIn("pauseForSpeech()",code)
        self.assertIn("return saved!=KittyMemory::saved",code)
        self.assertIn("archiveChanged(savedBefore,factsBefore,summariesBefore)",code)
        self.assertIn("WiFiClientSecure client;client.setCACert",code)
    def test_archive_revision_guard_and_audio_safe_diagnostics(self):
        sync=(ROOT/"firmware/CuteDisplayBrain/KittyMemorySyncV6.h").read_text()
        self.assertIn("ARCHIVE_QUIET_MS=3000UL",sync)
        self.assertIn("archiveChanged(savedBefore,factsBefore,summariesBefore)",sync)
        self.assertIn("failureStage=4;changedDuringExport++;ok=false;break;",sync)
        self.assertIn("if(failureStage!=4)",sync)
        self.assertIn("lastArchiveChange=now",sync)
        self.assertIn("inCallPosts++",sync)
        self.assertIn("speechOverlapPosts++",sync)
        self.assertIn("slowestPostMs=elapsed",sync)
        self.assertIn('send("/snapshot/finalize",body,reply)',sync)
        self.assertIn('client.setCACert(KITTY_SYNC_V6_CA_PEM)',sync)
        # A comment documents the forbidden API; exclude comments from the check.
        executable="\n".join(line.split("//",1)[0] for line in sync.splitlines())
        self.assertNotIn("setInsecure(",executable)

if __name__=="__main__":
    unittest.main()
