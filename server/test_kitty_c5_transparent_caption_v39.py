#!/usr/bin/env python3
"""Static C5 v39 caption safety: preserve Kitty face, remove solid caption mask."""
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]
FACE=ROOT/"firmware"/"CuteDisplay"/"C5CallFace.h"
VERSION=ROOT/"firmware"/"CuteDisplay"/"C5FirmwareVersion.h"


class TransparentCaptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.face=FACE.read_text(encoding="utf-8")
        cls.version=VERSION.read_text(encoding="utf-8")
        cls.caption=cls.face.split(
            "// Transparent 2-line live caption on the light forehead",1)[1]

    def test_c5_v39_and_no_opaque_caption_or_status_panel(self):
        self.assertIn("C5_FIRMWARE_VERSION = 39;",self.version)
        self.assertNotIn("panelY",self.caption)
        self.assertNotIn("panelH",self.caption)
        self.assertNotIn("rect(0,136,320,34",self.face)
        self.assertNotIn("rect(x+8,152,width-16,17,CF_INK)",self.face)

    def test_caption_has_black_text_directly_over_kitty_framebuffer(self):
        self.assertIn("const int captionY=40;",self.caption)
        self.assertIn("richText(rows[i],6,captionY+i*16,1,1,BLACK,316);",self.caption)
        self.assertNotIn("richText(rows[i],6,captionY+i*16,1,1,CF_WHITE",self.caption)
        self.assertNotIn("rect(",self.caption)
        self.assertIn("textAt(label,15,154,1,BLACK);",self.face)

    def test_wrap_and_unicode_preserved(self):
        for expected in (
            "decodeUTF8(callCaption,pos)",
            "utfWidth(cp,1,1)",
            "current+=callCaption.substring(begin,pos)",
            "if(used+glyph>304",
            "String rows[2]",
            "rows[0]=rows[1]",
            "rows[1]=value",
        ):
            self.assertIn(expected,self.caption)

    def test_expression_lips_and_call_state_still_present(self):
        for expected in (
            "drawFullScreenKittyFace()",
            "const bool speaking=kittyActivity==",
            "callFaceTransitionStart",
            "if(speaking){",
            "callLipLevel",
            "cfEye(lx,ey",
            "cfTri(49,42",
            "oval(160,119+bob",
        ):
            self.assertIn(expected,self.face)


if __name__=="__main__":
    unittest.main()
