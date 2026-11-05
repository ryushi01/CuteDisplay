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
        self.assertIn("KittyMemory::requestExport(i,offset,frozen[i])",code)
        self.assertIn("pauseForSpeech()",code)
        self.assertIn("return saved!=KittyMemory::saved",code)
        self.assertIn("factsBefore!=KittyMemory::factRevision",code)
        self.assertIn("WiFiClientSecure client;client.setCACert",code)
    def test_fixed_sd_export_boundaries(self):
        memory=(ROOT/"firmware/CuteDisplayBrain/KittyMemory.h").read_text()
        sync=(ROOT/"firmware/CuteDisplayBrain/KittyMemorySyncV6.h").read_text()
        self.assertIn("if(exportReq.file==EXPORT_COUNT)",memory)
        self.assertIn("block.boundaries[n]=(uint32_t)f.size()",memory)
        self.assertIn("block.total-exportReq.offset",memory)
        self.assertIn("KittyMemory::requestExport(KittyMemory::EXPORT_COUNT,0)",sync)
        self.assertIn("frozen[n]=boundary.boundaries[n]",sync)
        self.assertIn("KittyMemory::requestExport(i,offset,frozen[i])",sync)
        self.assertNotIn("archiveChanged(savedBefore,factsBefore,summariesBefore)",sync)
    def test_call_stop_clears_active_state_and_preserves_controls(self):
        direct=(ROOT/"firmware/CuteDisplayBrain/BrainRealtimeDirect.h").read_text()
        main=(ROOT/"firmware/CuteDisplayBrain/CuteDisplayBrain.ino").read_text()
        self.assertIn("inline void stop(){",direct)
        self.assertIn('status("CALL_OFF");',direct)
        self.assertIn("if(requested){stop();return true;}",direct)
        self.assertIn('f.type=="CALL_STOP"',main)
        self.assertIn("if(BrainRealtimeDirect::active())BrainRealtimeDirect::stop();",main)
        self.assertIn("BrainRealtimeDirect::stop();",main)
        self.assertIn("Manual USB stop requested",main)
        self.assertIn("[CALL NET] ws_disconnected",direct)
    def test_mic_jitter_queue_and_adaptive_catchup(self):
        audio=(ROOT/"firmware/CuteDisplayBrain/BrainRealtimeAudio.h").read_text()
        direct=(ROOT/"firmware/CuteDisplayBrain/BrainRealtimeDirect.h").read_text()
        self.assertIn("MIC_FRAMES=48",audio)
        self.assertIn("MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT",audio)
        self.assertIn("queuedMicFrames()",audio)
        self.assertIn("queuedMicFrames()>=8?4:2",direct)
        self.assertIn("for(int n=0;n<micBudget;n++)",direct)
        self.assertIn("BrainRealtimeAudio::takeMic(frame)",direct)
        self.assertIn("ws.sendTXT(payload)",direct)
    def test_archive_revision_guard_and_audio_safe_diagnostics(self):
        sync=(ROOT/"firmware/CuteDisplayBrain/KittyMemorySyncV6.h").read_text()
        self.assertIn("ARCHIVE_QUIET_MS=3000UL",sync)
        self.assertIn("summariesBefore!=KittyMemory::summaryRevision",sync)
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
