import unittest
from kitty_ota_simulator_v6 import simulate
class SimulatorTests(unittest.TestCase):
 def test_complete_image(self):
  image=bytes([0xe9])+b"z"*5101
  result=simulate(image,b"k"*32,b"n"*16,6553600)
  self.assertTrue(result["simulated_valid"])
  self.assertFalse(result["hardware_flash_performed"])
 def test_oversized_image_rejected(self):
  with self.assertRaises(ValueError):simulate(bytes([0xe9])+b"x"*100,b"k"*32,b"n"*16,100)
 def test_invalid_header_rejected(self):
  with self.assertRaises(ValueError):simulate(b"x"*500,b"k"*32,b"n"*16,6553600)
if __name__=="__main__":unittest.main()
