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

    def test_face_stays_visible_and_no_previous_caption(self):
        source = (ROOT/"firmware/CuteDisplay/C5CallFace.h").read_text()
        start = source.index("static void drawFullScreenKittyFace()")
        face = source[start:]
        self.assertIn("const int panelY=136;", face)
        self.assertIn("const int panelH=34;", face)
        self.assertNotIn("transcript=callCaptionPrevious", face)
        self.assertIn("uint8_t emotion=", face)
        self.assertIn("const int lx=117+gaze,rx=203+gaze", face)

if __name__ == "__main__":
    unittest.main()
