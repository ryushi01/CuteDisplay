#!/usr/bin/env python3
"""No model or audio: X-vector adaptive hints stay candidate-only and opt-in."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from kitty_voice_adaptation_policy_v6 import _unit
from kitty_xvector_shadow_worker_v6 import _adaptive_candidates


def v512(axis):
    samples=[0.0]*512
    samples[axis]=1.0
    return samples


class XvectorAdaptiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/"shadow.json"
        self.timestamp=datetime.now(timezone.utc)
        self.profile={
            "mode":"shadow_only",
            "memory_authorization":False,
            "adaptive_learning_consent":True,
            "speaker_id":"person:shana",
            "owner_enrollment_id":"person:shana",
            "model_id":"speechbrain/spkrec-xvect-voxceleb",
            "adaptive_source":"independently_attested_owner_turn",
            "adaptive_embeddings":[
                {"timestamp":(self.timestamp-timedelta(days=i)).isoformat(),
                 "embedding":v512(0)}
                for i in range(1,4)],
        }
        self.write()
        self.environment=patch.dict(os.environ,{
            "KITTY_XVECTOR_SHADOW_PROFILE":str(self.path),
            "KITTY_XVECTOR_ADAPTIVE_CANDIDATE":"1"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        import kitty_xvector_shadow_worker_v6 as worker
        worker._ADAPTIVE=()
        worker._ADAPTIVE_MTIME=None
        worker._ADAPTIVE_LAST_CHECK=-1000000.0
        self.worker=worker

    def write(self):
        self.path.write_text(json.dumps(self.profile),encoding="utf-8")
        os.chmod(self.path,0o600)

    def refresh(self):
        self.worker._ADAPTIVE_LAST_CHECK=-1000000.
        self.worker._ADAPTIVE_MTIME=None
        return self.worker._adaptive_candidates()

    def test_valid_three_day_cohort_readable_and_memory_disabled(self):
        self.assertEqual(len(self.refresh()),3)
        self.assertFalse(self.profile["memory_authorization"])

    def test_never_activate_without_model_pin_and_owner_consent(self):
        for key,value in (
                ("adaptive_learning_consent",False),
                ("owner_enrollment_id","person:guest"),
                ("model_id","unrelated-model"),
                ("adaptive_source","voice_probable"),
                ("memory_authorization",True)):
            original=self.profile[key]
            self.profile[key]=value
            self.write()
            self.assertEqual(self.refresh(),())
            self.profile[key]=original

    def test_not_enough_sessions_or_private_file_permissions(self):
        original=self.profile["adaptive_embeddings"]
        self.profile["adaptive_embeddings"]=original[:2]
        self.write()
        self.assertEqual(self.refresh(),())
        self.profile["adaptive_embeddings"]=original
        self.write()
        os.chmod(self.path,0o644)
        self.assertEqual(self.refresh(),())

    def test_default_disabled_and_no_memory_authorization(self):
        with patch.dict(os.environ,{"KITTY_XVECTOR_ADAPTIVE_CANDIDATE":"0"}):
            self.assertEqual(self.refresh(),())
        self.assertEqual(len(_unit(v512(0))),512)


if __name__=="__main__":
    unittest.main()
