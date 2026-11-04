#!/usr/bin/env python3
"""Offline private X-vector profile storage tests; no real voiceprint touched."""
import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from kitty_xvector_adaptive_store_v6 import (
    load_owner_shadow_profile, save_shadow_if_original_unchanged, MODEL,
)


def basis():
    vector=[0.0]*512
    vector[0]=1.0
    return vector


class AdaptiveXvectorStorageTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)/"private-xvector.json"
        self.profile={
            "version":6,"speaker_id":"person:shana",
            "model":MODEL,"model_id":MODEL,
            "mode":"shadow_only","memory_authorization":False,
            "consent":"local_explicit_enrollment",
            "adaptive_learning_consent":True,
            "owner_enrollment_id":"person:shana",
            "anchor_embeddings":[basis(),basis(),basis()],
            "adaptive_embeddings":[],
        }
        self.write()

    def write(self):
        self.path.write_text(json.dumps(self.profile),encoding="utf-8")
        os.chmod(self.path,0o600)

    def update(self,original):
        result=copy.deepcopy(original)
        result["adaptive_source"]="independently_attested_owner_turn"
        result["adaptive_embeddings"]=[{
            "embedding":basis(),
            "timestamp":datetime.now(timezone.utc).isoformat(),
            "similarity":0.99,
        }]
        result["adaptive_audio_hashes"]=["a"*64]
        return result

    def test_protected_enrollment_unchanged_after_atomic_save(self):
        old=load_owner_shadow_profile(self.path)
        revised=self.update(old)
        self.assertTrue(save_shadow_if_original_unchanged(
            self.path,old,revised))
        read=load_owner_shadow_profile(self.path)
        self.assertEqual(read["anchor_embeddings"],old["anchor_embeddings"])
        self.assertEqual(read["adaptive_embeddings"],revised["adaptive_embeddings"])
        self.assertIs(read["memory_authorization"],False)
        self.assertEqual(self.path.stat().st_mode&0o777,0o600)
        self.assertNotIn("wav",json.dumps(read).lower())

    def test_stale_snapshot_cannot_replace_new_voice_learning(self):
        old=load_owner_shadow_profile(self.path)
        revised=self.update(old)
        self.assertTrue(save_shadow_if_original_unchanged(
            self.path,old,revised))
        self.assertFalse(save_shadow_if_original_unchanged(
            self.path,old,revised))

    def test_profile_revocation_and_unpinned_model_fail_closed(self):
        for key,value in (
            ("adaptive_learning_consent",False),
            ("model_id","another-model"),
            ("owner_enrollment_id","person:guest"),
            ("memory_authorization",True)):
            old=self.profile[key]
            self.profile[key]=value
            self.write()
            with self.assertRaises(PermissionError):
                load_owner_shadow_profile(self.path)
            self.profile[key]=old
        self.write()
        self.assertEqual(load_owner_shadow_profile(self.path),self.profile)

    def test_changed_anchors_and_owner_metadata_cannot_be_written(self):
        original=load_owner_shadow_profile(self.path)
        revised=self.update(original)
        revised["anchor_embeddings"]=[basis(),basis()]
        self.assertFalse(save_shadow_if_original_unchanged(
            self.path,original,revised))
        revised=self.update(original)
        revised["speaker_id"]="person:other"
        self.assertFalse(save_shadow_if_original_unchanged(
            self.path,original,revised))

    def test_symlink_and_world_readable_profiles_are_rejected(self):
        os.chmod(self.path,0o644)
        with self.assertRaises(PermissionError):
            load_owner_shadow_profile(self.path)
        os.chmod(self.path,0o600)
        alias=self.path.with_name("alias.json")
        alias.symlink_to(self.path)
        with self.assertRaises(ValueError):
            load_owner_shadow_profile(alias)


if __name__=="__main__":
    unittest.main()
