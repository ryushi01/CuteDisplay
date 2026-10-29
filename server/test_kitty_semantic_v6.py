#!/usr/bin/env python3
"""Offline V6 tests: no model download or Open WebUI needed."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("kitty_sd_semantic_index", ROOT / "kitty_sd_semantic_index.py")
v6 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v6)

class FakeModel:
    def encode(self, texts, normalize_embeddings=True, batch_size=16):
        import numpy as np
        def vec(text):
            text=text.lower()
            # Deterministic tiny vectors only for lifecycle testing.
            values=np.array([text.count("cat")+text.count("chat"), text.count("date")+text.count("plan"), 1.0],dtype=np.float32)
            return values / np.linalg.norm(values)
        return np.stack([vec(t) for t in texts])

class SemanticV6Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        (self.root/"sd"/"kitty").mkdir(parents=True)
        self.data=self.root/"sd"/"kitty"/"facts.tsv"
        self.db=self.root/"index.sqlite3"
        v6._MODEL_CACHE["fake-test"]=FakeModel()
    def tearDown(self):
        self.tmp.cleanup()
    def test_rebuild_reuses_vectors_and_removes_deleted_memory(self):
        self.data.write_text("pet\tmy cat\nplan\tdate plan\n",encoding="utf-8")
        first=v6.build(self.root/"sd",self.db,"fake-test")
        self.assertEqual((first["indexed"],first["embedded"],first["reused"]),(2,2,0))
        second=v6.build(self.root/"sd",self.db,"fake-test")
        self.assertEqual((second["indexed"],second["embedded"],second["reused"]),(2,0,2))
        self.assertEqual(len(v6.search(self.db,"cat",5,"fake-test")),2)
        self.data.write_text("pet\tmy cat\nnew\tnew cat\n",encoding="utf-8")
        third=v6.build(self.root/"sd",self.db,"fake-test")
        self.assertEqual((third["indexed"],third["embedded"],third["reused"]),(2,1,1))
        hits=v6.search(self.db,"cat",5,"fake-test")
        self.assertTrue(all("plan" not in h["id"] for h in hits))
    def test_missing_and_empty_query(self):
        self.assertEqual(v6.search(self.db,"",5,"fake-test"),[])
        with self.assertRaises(FileNotFoundError):
            v6.search(self.db,"cat",5,"fake-test")

if __name__=="__main__":
    unittest.main()
