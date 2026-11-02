#!/usr/bin/env python3
"""Regression guard for the accepted S3 memory/stack baseline.

Static checks only: hardware heap minima and task stack margins must be
measured on the actual S3. Never change audio or task scheduling here.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
BRAIN = (ROOT / "firmware/CuteDisplayBrain/CuteDisplayBrain.ino").read_text()
AI = (ROOT / "firmware/CuteDisplayBrain/BrainAI.h").read_text()
BUILD = (ROOT / "tools/build_s3_with_c5_update.sh").read_text()

class S3StabilityContract(unittest.TestCase):
    def test_c5_exclusively_owns_bluetooth(self):
        self.assertIn("#if !KITTY_C5_BLE_MIGRATION_ENABLED", BRAIN)
        self.assertIn("#if KITTY_C5_BLE_MIGRATION_ENABLED && defined(CONFIG_BT_ENABLED)", BRAIN)
        self.assertIn("esp_bt_controller_get_status()==ESP_BT_CONTROLLER_STATUS_IDLE", BRAIN)
        self.assertIn("esp_bt_controller_mem_release(ESP_BT_MODE_BLE)", BRAIN)
        # A healthy C5 link never enters UART recovery; release on normal boot.
        setup = BRAIN[BRAIN.index("void setup(){"):BRAIN.index("void loop(){")]
        self.assertIn("esp_bt_controller_mem_release(ESP_BT_MODE_BLE)", setup)
        recovery = BRAIN[BRAIN.index("static void recoverFreshBootUART("):BRAIN.index("static void pollFace(){")]
        self.assertNotIn("esp_bt_controller_mem_release(ESP_BT_MODE_BLE)", recovery)

    def test_bounded_legacy_http_transport(self):
        self.assertRegex(AI, r"cfg\.buffer_size\s*=\s*1024\s*;")
        self.assertRegex(AI, r"cfg\.buffer_size_tx\s*=\s*512\s*;")
        self.assertIn("MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT", AI)

    def test_live_call_ai_internal_heap_guard(self):
        self.assertRegex(AI, r"internalFree\s*<\s*32768")
        self.assertRegex(AI, r"largestBlock\s*<\s*16384")
        self.assertIn('xTaskCreatePinnedToCore(run,"brain_ai",16384', AI)

    def test_readonly_diagnostics_preserved(self):
        for marker in ("loop_stack_highwater_bytes=", "internal_min=", "internal_largest=",
                       "psram_min=", "audio_stack_free=", "sd_stack_free=",
                       "ai_stack_free=", "reset_reason="):
            self.assertIn(marker, BRAIN)

    def test_loop_stack_has_conservative_headroom(self):
        # Long-call hardware data showed a 548-byte minimum on 8 KiB loopTask.
        # Keep audio buffers/loop timing unchanged and reserve 2 KiB more.
        self.assertIn("SET_LOOP_TASK_STACK_SIZE(10 * 1024);", BRAIN)
        self.assertIn("loop_stack_highwater_bytes=", BRAIN)

    def test_uart_diagnostics_do_not_change_ack_timing(self):
        # Observe the reported timeouts without changing C5, packet content,
        # retry thresholds, or the working 24 kHz audio worker.
        for key in ("uartAckAccepted", "uartAckIgnored", "uartRetransmitted",
                    "uartPacketTimeouts"):
            self.assertIn(key, AI)
        self.assertIn("if(millis()-pendingAt<1800)return;", AI)
        self.assertIn("if(++retries>4)", AI)
        self.assertIn("[SYS UART AI] ack_ok=", BRAIN)
        self.assertIn("BrainAI::uartPacketTimeouts", BRAIN)

    def test_flash_configuration_unchanged(self):
        for marker in ("PSRAM=opi", "LoopCore=1", "EventsCore=0",
                       "CPUFreq=240", "PartitionScheme=custom"):
            self.assertIn(marker, BUILD)

if __name__ == "__main__":
    unittest.main()
