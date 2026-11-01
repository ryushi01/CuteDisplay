"""Targeted regression for claim attribution surviving SD semantic indexing."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from kitty_sd_semantic_index import build, search


class DummyModel:
    def encode(self, texts, normalize_embeddings=True, batch_size=16):
        return np.asarray([[1., 0.] for _ in texts], dtype=np.float32)


class ClaimAttributionTest(unittest.TestCase):
    def test_claim_sources_remain_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            sd=Path(tmp)/"sd"
            (sd/"kitty").mkdir(parents=True)
            (sd/"kitty"/"speaker_claims_v6.tsv").write_text(
                "123\tperson:camille\tname\tCamille\texplicit_introduction\n"
                "124\tperson:aki\tname\tAki\tvoice_probable\n", encoding="utf-8")
            db=str(Path(tmp)/"derived.db")
            with patch("kitty_sd_semantic_index.get_model", return_value=DummyModel()):
                build(sd, db, model_name="test")
                camille=search(db,"私の名前は?",model_name="test",speaker_id="person:camille")
                aki=search(db,"Comment je m'appelle?",model_name="test",speaker_id="person:aki")
            self.assertEqual(len(camille), 1)
            self.assertEqual(len(aki), 1)
            self.assertEqual(camille[0]["provenance"], "explicit_introduction")
            self.assertEqual(aki[0]["provenance"], "voice_probable")
            self.assertNotIn("Aki", camille[0]["text"])
            self.assertNotIn("Camille", aki[0]["text"])


if __name__ == "__main__":
    unittest.main()
