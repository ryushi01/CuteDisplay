"""Static regression checks for the combined S3 and C5 caption firmware."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class DisplayContract(unittest.TestCase):
    def test_s3_does_not_enqueue_identical_snapshots(self):
        source = (ROOT / "firmware/CuteDisplayBrain/BrainRealtimeDirect.h").read_text()
        self.assertIn("if(c==captionLastQueued)return;", source)
        self.assertIn('captionLastQueued="";', source)
        self.assertIn('safe_event', (ROOT/"server/kitty_realtime_gateway_observer_v6.py").read_text())

    def test_face_stays_visible_and_rolling_caption_history(self):
        source = (ROOT/"firmware/CuteDisplay/C5CallFace.h").read_text()
        start = source.index("static void drawFullScreenKittyFace()")
        face = source[start:]
        # C5 v40: five black-text rows directly over the animated
        # Kitty face, without an opaque dark rectangle.
        self.assertIn("const int captionY=2;", face)
        self.assertIn("CALL_CAPTION_ROWS=5", face)
        self.assertIn("String transcript=callCaptionHistory;", face)
        self.assertIn("richText(rows[i],6,captionY+i*16,1,1,BLACK,316);", face)
        self.assertNotIn("const int panelY=136;", face)
        self.assertNotIn("const int panelH=34;", face)
        self.assertNotIn("transcript=callCaptionPrevious", face)
        self.assertIn("uint8_t emotion=", face)
        self.assertIn("const int lx=117+gaze,rx=203+gaze", face)

if __name__ == "__main__":
    unittest.main()
