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
    def test_paced_and_fast_retry(self):
        code=(ROOT/"firmware/CuteDisplayBrain/KittyMemorySyncV6.h").read_text()
        self.assertIn("callActive && callActive()?200:12",code)
        self.assertIn("FAILURE_RETRY_MS=5000UL",code)
        self.assertIn("IDLE_QUIET_MS=500UL",code)
        self.assertIn("KittyMemory::requestExport(i,offset)",code)
        self.assertIn("savedBefore!=KittyMemory::saved",code)
        self.assertIn("WiFiClientSecure client;client.setCACert",code)
if __name__=="__main__":
    unittest.main()
