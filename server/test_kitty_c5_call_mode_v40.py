#!/usr/bin/env python3
"""Static cross-board Call Mode contract (v40 behavior retained through v41)."""
import re
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
C5=(ROOT/"firmware/CuteDisplay/lcd.ino").read_text()
FACE=(ROOT/"firmware/CuteDisplay/C5CallFace.h").read_text()
VERSION=(ROOT/"firmware/CuteDisplay/C5FirmwareVersion.h").read_text()
S3=(ROOT/"firmware/CuteDisplayBrain/CuteDisplayBrain.ino").read_text()
BUILDER=(ROOT/"tools/build_s3_with_c5_update.sh").read_text()


class C5CallModeV40Contracts(unittest.TestCase):
    def test_version_and_transparent_five_line_layout(self):
        self.assertIn("C5_FIRMWARE_VERSION = 41;",VERSION)
        self.assertIn("CALL_CAPTION_ROWS=5;",FACE)
        self.assertIn("const int captionY=2;",FACE)
        self.assertIn("captionY+i*16",FACE)
        self.assertLessEqual(2+(5-1)*16+16, 170)
        self.assertIn("richText(rows[i],6,captionY+i*16,1,1,BLACK,316)",FACE)
        self.assertNotIn("panelY",FACE.split("// v40: five transparent rows",1)[1])
        self.assertIn("String transcript=callCaptionHistory;",FACE)

    def test_prior_turns_bounded_and_streaming_updates_not_duplicated(self):
        for marker in ("callCaptionHistory.length()>1024",
                       "callCaption.startsWith(first)",
                       "first.startsWith(callCaption)",
                       "callCaptionHistory+=callCaption",
                       "((uint8_t)callCaptionHistory[trim]&0xC0)==0x80",
                       "callCaption=\"\";callCaptionHistory=\"\""):
            self.assertIn(marker,C5)

    def test_input_poll_before_uart_frames_and_network_work(self):
        loop=C5.split("void loop(){",1)[1]
        self.assertLess(loop.index("pollVoiceButton(millis());"),loop.index("serviceBrain();"))
        self.assertLess(loop.index("pollVoiceButton(millis());"),loop.index("updateLAN();"))
        self.assertIn(">=20 && raw!=voiceButtonStable",C5)

    def test_stop_is_sent_on_press_and_is_not_toggle(self):
        button=C5.split("static void pollVoiceButton(uint32_t now){",1)[1].split(
            "static void sendBrainProbe",1)[0]
        pressed=button.split("if(raw==LOW){",1)[1].split("}else{",1)[0]
        self.assertIn('toS3("CALL_STOP");',pressed)
        self.assertNotIn('toS3("CALL_TOGGLE");',pressed)
        self.assertIn("callStopPending=true",pressed)
        self.assertIn("voiceButtonSession=false;voiceButtonHoldStarted=true;",pressed)
        self.assertIn("callStopAttempts<4",button)
        self.assertIn('toS3("CALL_TOGGLE");',button)
        self.assertIn("!callModeActive && !callStopPending",button)
        self.assertEqual(C5.count("static void pollVoiceButton(uint32_t now)"),1)

    def test_s3_stop_command_is_idempotent_and_authoritative(self):
        stop=S3.index('f.type=="CALL_STOP"')
        toggle=S3.index('f.type=="CALL_TOGGLE"')
        self.assertLess(stop,toggle)
        segment=S3[stop:toggle]
        self.assertIn("if(BrainRealtimeDirect::active())BrainRealtimeDirect::stop();",segment)
        self.assertIn("forceActivityResend=true;",segment)
        self.assertNotIn("BrainRealtimeDirect::toggle",segment)

    def test_call_mode_suspends_normal_ai_bubble_and_suppresses_stale_status(self):
        self.assertIn("static void suspendNormalChatForCall()",C5)
        for marker in ("callHidesNormalChat=true;",
                       "aiScrollMode=false;aiStreamFinished=true;aiFinishedAt=0;",
                       "message=normalDisplayMessage;",
                       "if(callModeActive || callStopPending)return;",
                       "if((bubbleEnabled && !callHidesNormalChat) || aiScrollMode)",
                       'if(callStopPending && next.startsWith("CALL_")',
                       'next!="CALL_OFF" && next!="CALL_ERROR"',
                       '"ACK","AI"'):
            self.assertIn(marker,C5)
        self.assertIn("callHidesNormalChat=false;",C5)
        self.assertNotIn('displayPrefs.putBool("callHidesNormalChat"',C5)

    def test_chat_display_framing_coalesces_lcd_transfers(self):
        body=C5.split("static void serviceBrain() {",1)[1].split(
            "void setup(){",1)[0]
        self.assertIn("bool callFrameRedraw=false;",body)
        self.assertIn("if(lcdReady)callFrameRedraw=true;",body)
        self.assertIn("callLipLevel=next;callFrameRedraw=true;",body)
        self.assertIn("if(callFrameRedraw && lcdReady && !C5UARTOTA::active())redrawCurrent();",body)

    def test_private_combined_build_and_c5_v40_payload_preserved(self):
        self.assertIn('KITTY_SYNC_PRIVATE_HEADER',BUILDER)
        self.assertIn('cp "$PRIVATE_HEADER" "$WORK/CuteDisplayBrain/KittySyncPrivateConfig.h"',BUILDER)
        self.assertIn('chmod 600 "$OUT/CuteDisplayBrain/KittySyncPrivateConfig.h"',BUILDER)
        self.assertIn('rm -f "$OUT/CuteDisplayBrain/KittySyncPrivateConfig.h"',BUILDER)
        self.assertIn('C5_FIRMWARE_VERSION',BUILDER)
        self.assertIn('GITHUB_ACTIONS',BUILDER)


if __name__=="__main__":
    unittest.main()
