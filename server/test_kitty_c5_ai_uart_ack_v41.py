#!/usr/bin/env python3
"""Regression for v40 C5 NACK CALL_ACTIVE dropping valid delegated AI replies.

This tests source contracts only. Hardware and Open WebUI live calls still need
verification after the local private combined firmware is flashed.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
C5 = (ROOT/"firmware/CuteDisplay/lcd.ino").read_text(encoding="utf-8")
S3_AI = (ROOT/"firmware/CuteDisplayBrain/BrainAI.h").read_text(encoding="utf-8")
S3_BRAIN = (ROOT/"firmware/CuteDisplayBrain/CuteDisplayBrain.ino").read_text(encoding="utf-8")
C5_VERSION = (ROOT/"firmware/CuteDisplay/C5FirmwareVersion.h").read_text(encoding="utf-8")


def case(type_name, next_name):
    start = C5.index('else if(f.type=="'+type_name+'")')
    stop = C5.index('else if(f.type=="'+next_name+'")', start)
    return C5[start:stop]


class C5SilentDelegatedAiAckTests(unittest.TestCase):
    def test_version_bumped_from_installed_v40(self):
        self.assertIn("C5_FIRMWARE_VERSION = 41;", C5_VERSION)

    def test_v40_call_active_nack_regression_removed(self):
        self.assertNotIn('"NACK","CALL_ACTIVE"', C5)

    def test_ai_begin_acknowledged_without_background_bubble(self):
        body = case("AI_BEGIN", "AI_DATA")
        suppressed = body.split("if(callModeActive || callStopPending){",1)[1].split("}else if",1)[0]
        self.assertIn('CuteLink::send(Serial1,f.seq,"ACK","AI");', suppressed)
        self.assertNotIn("aiScrollMode=true", suppressed)
        self.assertNotIn("drawMessage()", suppressed)
        self.assertIn('CuteLink::send(Serial1,f.seq,"NACK","DISPLAY")',body)
        self.assertIn('aiScrollMode=true;aiStreamFinished=false;',body)

    def test_ai_data_acknowledged_without_append_or_redraw(self):
        body = case("AI_DATA", "AI_END")
        suppressed = body.split("else if(callModeActive || callStopPending){",1)[1].split("}else if",1)[0]
        self.assertIn('CuteLink::send(Serial1,f.seq,"ACK","AI");', suppressed)
        self.assertNotIn("message+=",suppressed)
        self.assertNotIn("drawMessage()",suppressed)
        self.assertIn('CuteLink::send(Serial1,f.seq,"NACK","AI_STATE");',body)
        self.assertIn("f.payload.length()>80",body)
        self.assertIn("message+=f.payload;",body)
        self.assertIn("drawMessage();",body)

    def test_ai_end_acknowledged_without_hidden_typewriter_updates(self):
        body = case("AI_END","CMDHEX")
        suppressed = body.split("if(callModeActive || callStopPending){",1)[1].split("}else{",1)[0]
        self.assertIn('CuteLink::send(Serial1,f.seq,"ACK","AI");', suppressed)
        self.assertNotIn("aiStreamFinished=true;",suppressed)
        self.assertIn("if(aiScrollMode){aiStreamFinished=true;",body)

    def test_s3_ai_worker_expects_valid_ai_ack_not_nack(self):
        self.assertIn('if(type=="ACK" && payload=="AI"){',S3_AI)
        self.assertIn("pending=0;failed=true;",S3_AI)
        self.assertIn("for(int i=0;i<e->data_len && !failed && !cancelRequested;i++)",S3_AI)
        self.assertIn("sendPacket(\"AI_BEGIN\",\"\");",S3_AI)
        self.assertIn("sendPacket(\"AI_END\",\"\");",S3_AI)
        self.assertIn('if(f.type=="ACK"||f.type=="NACK"){',S3_BRAIN)

    def test_old_bubble_remains_suspended_while_call_active(self):
        self.assertIn("callHidesNormalChat=true;",C5)
        self.assertIn("if(callModeActive || callStopPending)return;",C5)
        self.assertIn("if((bubbleEnabled && !callHidesNormalChat) || aiScrollMode)",C5)
        self.assertIn('if(callStopPending && next.startsWith("CALL_")',C5)


if __name__=="__main__":
    unittest.main()
