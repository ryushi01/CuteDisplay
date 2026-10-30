#!/usr/bin/env python3
"""Offline V6 tests: no model download or Open WebUI needed."""
import importlib.util
import tempfile
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
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
    def test_speaker_sidecar_and_legacy_are_distinct(self):
        archive=self.root/"sd"/"kitty"/"conversations.tsv"
        a="1761790000\\tI am ChatGPT\\tNice to meet you.\\n".encode()
        b="1761790001\\tMy owner Shana is not here\\tUnderstood.\\n".encode()
        archive.write_bytes(a+b)
        sidecar=self.root/"sd"/"kitty"/"turn_sources.tsv"
        sidecar.write_text(f"1761790000\\t0\\tremote_ai:chatgpt\\tremote_ai\\texplicit_introduction\\n")
        v6.build(self.root/"sd",self.db,"fake-test")
        ai=v6.search(self.db,"cat",10,"fake-test",speaker_id="remote_ai:chatgpt")
        self.assertEqual(len(ai),1)
        self.assertEqual(ai[0]["speaker_role"],"remote_ai")
        # No sidecar record => unknown, never inherited owner's identity.
        others=v6.search(self.db,"cat",10,"fake-test",speaker_id="unknown")
        self.assertGreaterEqual(len(others),1)
        self.assertTrue(all(h["speaker_id"]=="unknown" for h in others))
        self.assertEqual(v6.search(self.db,"cat",10,"fake-test",speaker_id="person:owner"),[])

    def test_missing_and_empty_query(self):
        self.assertEqual(v6.search(self.db,"",5,"fake-test"),[])
        with self.assertRaises(FileNotFoundError):
            v6.search(self.db,"cat",5,"fake-test")

if __name__=="__main__":
    unittest.main()
