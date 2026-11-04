#!/usr/bin/env python3
"""Offline protected profile compare-and-swap, no access to private voice files."""
import copy
import unittest
from unittest import mock

from kitty_owner_voice_profile_store_v6 import (
    load_consented_owner_profile, save_if_original_unchanged,
    other_enrolled_profiles,
)
from test_kitty_voice_learning_v6 import vector, OWNER_PROFILE, MODEL


class OwnerProfileStoreTests(unittest.TestCase):
    def setUp(self):
        self.initial={
            "consent":"local_explicit_enrollment",
            "adaptive_learning_consent":True,
            "owner_enrollment_id":OWNER_PROFILE,
            "model_id":MODEL,
            "anchor_embeddings":[vector(0,0.01),vector(0,0.03),vector(0,0.04)],
            "adaptive_embeddings":[],
        }
        self.db={"version":6,"speakers":{
            OWNER_PROFILE:copy.deepcopy(self.initial),
            "person:aki":{"embeddings":[vector(3)]*3,
                          "consent":"local_explicit_enrollment"}
        }}
        self.updates=[]
        def load():
            return copy.deepcopy(self.db)
        def save(value):
            self.updates.append(copy.deepcopy(value))
            self.db=copy.deepcopy(value)
        self.mockload=mock.patch("kitty_speaker_cpu_v6._load",side_effect=load)
        self.mocksave=mock.patch("kitty_speaker_cpu_v6._save",side_effect=save)
        self.mockload.start()
        self.mocksave.start()
        self.addCleanup(self.mockload.stop)
        self.addCleanup(self.mocksave.stop)

    def test_model_pinned_consent_required_to_read(self):
        self.assertEqual(load_consented_owner_profile(OWNER_PROFILE),self.initial)
        self.assertIsNone(load_consented_owner_profile("person:owner"))
        self.db["speakers"][OWNER_PROFILE]["adaptive_learning_consent"]=False
        self.assertIsNone(load_consented_owner_profile(OWNER_PROFILE))
        self.assertEqual(self.updates,[])

    def test_cas_preserves_anchors_and_all_other_speakers(self):
        original=load_consented_owner_profile(OWNER_PROFILE)
        candidate={**original,"adaptive_embeddings":[{
            "embedding":vector(0,0.08),"timestamp":"2026-11-04T01:00:00+00:00",
            "similarity":0.98}],"memory_authorization":False}
        self.assertTrue(save_if_original_unchanged(
            OWNER_PROFILE,original,candidate))
        self.assertEqual(self.db["speakers"][OWNER_PROFILE]["anchor_embeddings"],
                         self.initial["anchor_embeddings"])
        self.assertEqual(self.db["speakers"]["person:aki"]["embeddings"],
                         [vector(3)]*3)
        self.assertEqual(len(self.updates),1)

    def test_concurrent_change_or_revoked_consent_fails_closed(self):
        original=load_consented_owner_profile(OWNER_PROFILE)
        candidate={**original,"adaptive_embeddings":[{
            "embedding":vector(0,0.08),"timestamp":"2026-11-04T01:00:00+00:00",
            "similarity":0.98}],"memory_authorization":False}
        self.db["speakers"][OWNER_PROFILE]["adaptive_learning_consent"]=False
        self.assertFalse(save_if_original_unchanged(
            OWNER_PROFILE,original,candidate))
        self.assertEqual(self.updates,[])

    def test_protected_changes_refused(self):
        original=load_consented_owner_profile(OWNER_PROFILE)
        for revised in (
            {**original,"anchor_embeddings":[vector(1)]*3,
             "memory_authorization":False,"adaptive_embeddings":[]},
            {**original,"model_id":"new_unknown_model",
             "memory_authorization":False,"adaptive_embeddings":[]},
            {**original,"memory_authorization":True}):
            self.assertFalse(save_if_original_unchanged(
                OWNER_PROFILE,original,revised))
        self.assertEqual(self.updates,[])

    def test_other_profiles_for_margin_are_copies(self):
        others=other_enrolled_profiles(OWNER_PROFILE)
        self.assertEqual(len(others),1)
        others[0]["consent"]="changed"
        self.assertNotEqual(others[0]["consent"],
                            self.db["speakers"]["person:aki"]["consent"])


if __name__=="__main__":
    unittest.main()
