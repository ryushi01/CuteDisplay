import os, tempfile, unittest
from unittest import mock
from pathlib import Path
from server import kitty_memory_service as m

class MemoryTests(unittest.TestCase):
 def test_upsert_recall_delete_and_archive(self):
  with tempfile.TemporaryDirectory() as d:
   with mock.patch.object(m,"DB",str(Path(d)/"kitty.db")):
    m.init()
    m.store("remember",{"topic":"Kyoto trip","detail":"Travelling in December"})
    self.assertEqual(len(m.recall("Kyoto")),1)
    m.store("remember",{"topic":"Kyoto trip","detail":"Changed destination to Osaka"})
    found=m.recall("Kyoto")
    self.assertEqual(len(found),1)
    self.assertIn("Osaka",found[0]["detail"])
    m.store("turn",{"speaker":"user","text":"Going to Osaka"})
    with m.connect() as db:
     self.assertEqual(db.execute("SELECT count(*) FROM conversation_archive").fetchone()[0],1)
    m.store("forget",{"id":found[0]["id"]})
    self.assertEqual(m.recall("Kyoto"),[])
 def test_empty_search(self):
  self.assertEqual(m.recall(""),[])

if __name__=="__main__":unittest.main()
