import hashlib
import hmac
import unittest
from kitty_ota_frames_v6 import CHUNK_BYTES, MAX_FRAME_BYTES, chunk_frame, iter_frames, start_frame, decode_key

class OTAFramesTests(unittest.TestCase):
    def test_chunk_bounded(self):
        key=b"k"*32; nonce=b"n"*16
        frame=chunk_frame(key,nonce,0,b"z"*CHUNK_BYTES)
        self.assertLessEqual(len(frame),MAX_FRAME_BYTES)
        self.assertTrue(frame.startswith("OTA_DATA 00000000 "))
    def test_mac_binds_offset_and_contents(self):
        a=chunk_frame(b"k"*32,b"n"*16,0,b"abc")
        self.assertNotEqual(a,chunk_frame(b"k"*32,b"n"*16,1,b"abc"))
        self.assertNotEqual(a,chunk_frame(b"k"*32,b"n"*16,0,b"abd"))
    def test_invalid_input_blocked(self):
        with self.assertRaises(ValueError):chunk_frame(b"k"*32,b"n"*16,0,b"x"*49)
        with self.assertRaises(ValueError):start_frame(0,"f"*64)
        with self.assertRaises(ValueError):decode_key("abcd")
    def test_full_image_coverage(self):
        content=b"a"*103
        frames=list(iter_frames(content,b"k"*32,b"n"*16))
        self.assertEqual(len(frames),3)
        self.assertTrue(frames[-1].startswith("OTA_DATA 00000060 "))
    def test_sha_start_frame(self):
        digest=hashlib.sha256(b"x").hexdigest()
        self.assertEqual(start_frame(1024,digest),f"OTA_BEGIN 1024 {digest}")
if __name__=="__main__": unittest.main()
