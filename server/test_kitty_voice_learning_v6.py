#!/usr/bin/env python3
"""No-model owner voice-learning tests; nothing recorded, installed or modified."""
import hashlib
import io
import math
import unittest
import wave
from datetime import datetime, timedelta, timezone

from kitty_attested_live_call_v6 import issue_external_attestation
from kitty_owner_session_v6 import issue_grant
from kitty_voice_learning_v6 import (
    learn_verified_owner_utterance, wav_quality_ok,
)

SIGNER = b"independent-acoustic-owner-verifier-key"
OWNER = b"enrolled-owner-key-separate-from-voice-signing"
SESSION = "trusted-audio-session-123456789"
MODEL = "speechbrain-ecapa-pinned-v6"
OWNER_PROFILE = "person:shana"


def vector(axis=0, offset=0.02):
    raw=[0.0]*192
    raw[axis]=1.0
    raw[(axis+1)%192]=offset
    magnitude=math.sqrt(sum(x*x for x in raw))
    return [x/magnitude for x in raw]


def clean_wav(value=7500):
    data=io.BytesIO()
    with wave.open(data,"wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(int(value).to_bytes(2,"little",signed=True)*32000)
    return data.getvalue()


class GradualOwnerLearningTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,11,4,1,0,0,tzinfo=timezone.utc)
        self.profile={
            "consent":"local_explicit_enrollment",
            "adaptive_learning_consent":True,
            "owner_enrollment_id":OWNER_PROFILE,
            "model_id":MODEL,
            "anchor_embeddings":[vector(0,0.02),vector(0,0.04),vector(0,0.07)],
            "adaptive_embeddings":[],
        }
        self.audio=clean_wav()
        self.transcript="We decided to keep Bluetooth on the C5."
        self.item="item_1"

    def proof(self, *, audio=None, item=None, speaker="person:owner",
              role="owner", now=None, with_audio_hash=True):
        audio=self.audio if audio is None else audio
        when=self.now if now is None else now
        ticket=issue_external_attestation(
            SIGNER,session_id=SESSION,item_id=item or self.item,
            transcript=self.transcript,speaker_id=speaker,
            speaker_role=role,now=int(when.timestamp()),
            audio_sha256=hashlib.sha256(audio).hexdigest()
                         if with_audio_hash else None,purpose="learning")
        owner_grant=issue_grant(OWNER,True,SESSION,now=int(when.timestamp()),
                                ttl=120)
        return ticket,owner_grant

    def learn(self, *, profile=None, audio=None, ticket=None,
              grant=None, now=None, embedding=None, **changes):
        when=self.now if now is None else now
        supplied_ticket,supplied_grant=self.proof(now=when)
        return learn_verified_owner_utterance(
            profile if profile is not None else self.profile,
            audio if audio is not None else self.audio,
            session_id=SESSION,item_id=self.item,
            transcript=self.transcript,
            signed_turn_ticket=ticket if ticket is not None else supplied_ticket,
            owner_grant=grant if grant is not None else supplied_grant,
            speaker_signer_secret=SIGNER,
            owner_grant_secret=OWNER,
            model_id=MODEL,
            owner_profile_id=OWNER_PROFILE,
            embedding_fn=lambda audio: embedding if embedding is not None
                                    else vector(0,0.06),
            now=when,**changes)

    def test_three_separate_days_improve_recognition_cohort_without_anchor_changes(self):
        profile=self.profile
        original_anchors=profile["anchor_embeddings"]
        for index in range(3):
            timepoint=self.now+timedelta(days=index)
            self.item="item_"+str(index+1)
            self.audio=clean_wav(7300+index*100)
            profile=self.learn(profile=profile,now=timepoint)
            self.assertEqual(profile["anchor_embeddings"],original_anchors)
            self.assertEqual(len(profile["adaptive_embeddings"]),index+1)
        self.assertEqual(len(profile["adaptive_embeddings"]),3)
        self.assertIs(profile["memory_authorization"],False)
        self.assertEqual(self.profile["adaptive_embeddings"],[])
        self.assertTrue(all("text" not in p and "wav" not in p
                            for p in profile["adaptive_embeddings"]))
        self.assertEqual(len(profile["adaptive_audio_hashes"]),3)

    def test_no_consent_and_old_enrollment_do_not_learn(self):
        for amended in (
            {"adaptive_learning_consent":False},
            {"adaptive_learning_consent":None},
            {"consent":"voice_match"},
        ):
            with self.assertRaises(PermissionError):
                self.learn(profile={**self.profile,**amended})
        with self.assertRaises(ValueError):
            self.learn(profile={**self.profile,"model_id":"other-encoder"})
        with self.assertRaises(ValueError):
            self.learn(profile={**self.profile,"owner_enrollment_id":"person:guest"})

    def test_owner_grant_alone_or_unsigned_probable_voice_cannot_train(self):
        with self.assertRaises(ValueError):
            self.proof(with_audio_hash=False)  # learning receipts need microphone binding
        _,grant=self.proof()
        with self.assertRaises(PermissionError):
            self.learn(ticket="voice_probable",grant=grant)
        ticket,grant=self.proof()
        with self.assertRaises(PermissionError):
            self.learn(ticket=ticket,grant="not-a-grant")
        guest_ticket,grant=self.proof(speaker="person:aki",role="guest")
        with self.assertRaises(PermissionError):
            self.learn(ticket=guest_ticket,grant=grant)

    def test_ticket_is_bound_to_exact_audio(self):
        ticket,grant=self.proof()
        alternative=clean_wav(6200)
        with self.assertRaises(PermissionError):
            self.learn(ticket=ticket,grant=grant,audio=alternative)

    def test_rejects_bad_audio_and_malformed_embedding(self):
        for audio in (b"fake audio",clean_wav(0),clean_wav(32767)):
            ticket,grant=self.proof(audio=audio)
            with self.assertRaises(ValueError):
                self.learn(ticket=ticket,grant=grant,audio=audio)
        with self.assertRaises(ValueError):
            self.learn(embedding=[float("nan")]*192)
        with self.assertRaises(ValueError):
            self.learn(embedding=[1.0]*4)

    def test_nearby_other_speaker_and_outlier_never_poison_anchors(self):
        with self.assertRaises(ValueError):
            self.learn(embedding=vector(1,0.01))
        peer={"anchor_embeddings":[vector(0,0.02),vector(0,0.04),vector(0,0.06)]}
        with self.assertRaises(ValueError):
            self.learn(other_profiles=[peer])
        self.assertEqual(self.profile["adaptive_embeddings"],[])

    def test_spacing_and_duplicate_replay_prevent_many_samples_per_call(self):
        first=self.learn()
        with self.assertRaises(ValueError):
            self.learn(profile=first,now=self.now+timedelta(minutes=1))
        self.item="item_2"
        later=self.now+timedelta(days=1)
        # Even if an independent verifier signed the same WAV next day,
        # the same recording bytes must not be admitted twice.
        with self.assertRaises(ValueError):
            self.learn(profile=first,now=later)

    def test_independently_verified_xvector_below_live_threshold_can_teach(self):
        def xvec(offset):
            v=[0.0]*512
            v[0]=1.0
            v[2]=offset
            length=math.sqrt(sum(x*x for x in v))
            return [x/length for x in v]
        shadow={
            "consent":"local_explicit_enrollment",
            "adaptive_learning_consent":True,
            "owner_enrollment_id":OWNER_PROFILE,
            "model_id":"speechbrain/spkrec-xvect-voxceleb",
            "mode":"shadow_only",
            "memory_authorization":False,
            "min_genuine_floor":0.965,
            "verified_learning_floor":0.92,
            "anchor_embeddings":[xvec(0),xvec(0.02),xvec(0.04)],
            "adaptive_embeddings":[],
        }
        observed=xvec(0.37)  # Genuine drift: about 0.94 from original anchors.
        ticket,grant=self.proof()
        result=learn_verified_owner_utterance(
            shadow,self.audio,session_id=SESSION,item_id=self.item,
            transcript=self.transcript,signed_turn_ticket=ticket,
            owner_grant=grant,speaker_signer_secret=SIGNER,
            owner_grant_secret=OWNER,
            model_id="speechbrain/spkrec-xvect-voxceleb",
            owner_profile_id=OWNER_PROFILE,
            embedding_fn=lambda _:observed,now=self.now)
        self.assertEqual(len(result["adaptive_embeddings"]),1)
        self.assertEqual(result["min_genuine_floor"],0.965)
        self.assertEqual(result["verified_learning_floor"],0.92)
        self.assertEqual(result["anchor_embeddings"],shadow["anchor_embeddings"])
        self.assertFalse(result["memory_authorization"])
        shadow["verified_learning_floor"]=0.90
        with self.assertRaises(ValueError):
            learn_verified_owner_utterance(
                shadow,self.audio,session_id=SESSION,item_id=self.item,
                transcript=self.transcript,signed_turn_ticket=ticket,
                owner_grant=grant,speaker_signer_secret=SIGNER,
                owner_grant_secret=OWNER,
                model_id="speechbrain/spkrec-xvect-voxceleb",
                owner_profile_id=OWNER_PROFILE,
                embedding_fn=lambda _:observed,now=self.now)

    def test_expired_attestation_denied(self):
        signed,grant=self.proof(now=self.now)
        with self.assertRaises(PermissionError):
            self.learn(ticket=signed,grant=grant,now=self.now+timedelta(minutes=5))


if __name__=="__main__":
    unittest.main()
