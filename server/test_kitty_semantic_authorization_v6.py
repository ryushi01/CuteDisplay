#!/usr/bin/env python3
"""Offline HTTP-level regression: the device token cannot read private SD history.

No live API calls, embeddings, downloads, iPhone keys or secret logs.
"""
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from server import kitty_memory_service as service
from kitty_owner_session_v6 import issue_grant
from kitty_attested_live_call_v6 import issue_external_attestation
from kitty_semantic_authorization_v6 import authorized_semantic_speaker


class _OfflineRequest(service.Handler):
    def __init__(self, path, payload, token="device"):
        raw=json.dumps(payload).encode("utf-8")
        self.path=path
        self.rfile=io.BytesIO(raw)
        self.headers={"Authorization":f"Bearer {token}","Content-Length":str(len(raw))}
        self.response=None

    def _reply(self,status,obj):
        self.response=(status,obj)
        return self.response


class SemanticGrantTests(unittest.TestCase):
    def setUp(self):
        self.secret=b"G"*32
        self.turn_secret=b"T"*32
        self.owner=SimpleNamespace(secret=self.secret)
        self.session="trusted-owner-session-1234"
        self.grant=issue_grant(self.secret,True,self.session,ttl=120)
        self.query="last decision"
        self.item="owner_item_1"
        self.ticket=issue_external_attestation(
            self.turn_secret, session_id=self.session, item_id=self.item,
            transcript=self.query, speaker_id="person:owner",
            speaker_role="owner")
        self.good={"speaker_id":"person:owner", "session_id":self.session,
                   "owner_grant":self.grant, "query":self.query,
                   "item_id":self.item,"transcript":self.query,
                   "turn_attestation":self.ticket}
        self.temp=tempfile.TemporaryDirectory()
        self.index=str(Path(self.temp.name)/"derived-index.sqlite3")
        Path(self.index).write_bytes(b"test")  # gate checks file presence, mock search

    def tearDown(self):
        self.temp.cleanup()

    def request(self,endpoint,data,owner=None,token="device"):
        request=_OfflineRequest(endpoint,data,token)
        with mock.patch.object(service,"TOKEN","device"),mock.patch.object(
                service,"OWNER_PROOF",owner),mock.patch.object(
                service,"TRUSTED_TURN_SECRET",self.turn_secret),mock.patch.dict(
                os.environ,{"KITTY_SEMANTIC_DB":self.index}):
            request.do_POST()
        return request.response

    def test_missing_owner_proof_fails_closed(self):
        self.assertIsNone(authorized_semantic_speaker(
            self.good,None,self.turn_secret))
        for endpoint in ("/semantic","/semantic/context"):
            status,_=self.request(endpoint,self.good)
            self.assertEqual(status,403)

    def test_valid_owner_session_accesses_only_owner_rows(self):
        observed=[]
        def fake_recall(index,query,speaker):
            observed.append((query,speaker))
            return "owner-only context"
        with mock.patch("kitty_memory_context_v6.recall_context",fake_recall):
            status,result=self.request("/semantic/context",self.good,self.owner)
        self.assertEqual((status,result),(200,{"context":"owner-only context"}))
        self.assertEqual(observed,[("last decision","person:owner")])

        def fake_search(index,query,*,speaker_id):
            observed.append((query,speaker_id))
            return [{"speaker_id":speaker_id,"text":"owner-only result"}]
        with mock.patch("kitty_sd_semantic_index.search",fake_search):
            status,result=self.request("/semantic",self.good,self.owner)
        self.assertEqual(status,200)
        self.assertEqual(result["results"][0]["speaker_id"],"person:owner")
        self.assertEqual(observed[-1],("last decision","person:owner"))

    def test_device_token_cannot_select_arbitrary_person(self):
        for sid in ("person:shana","person:guest","unknown","person:owner-admin",""):
            data={**self.good,"speaker_id":sid}
            self.assertIsNone(authorized_semantic_speaker(
                data,self.owner,self.turn_secret))
            for endpoint in ("/semantic","/semantic/context"):
                status,_=self.request(endpoint,data,self.owner)
                self.assertEqual(status,403)

    def test_missing_forged_expired_and_wrong_session_grants_fail(self):
        invalid=(
            {**self.good,"owner_grant":""},
            {**self.good,"owner_grant":"Shana"},
            {**self.good,"owner_grant":self.grant[:-5]+"wrong"},
            {**self.good,"session_id":"different-session"},
            {**self.good,"session_id":""},
        )
        for data in invalid:
            self.assertIsNone(authorized_semantic_speaker(
                data,self.owner,self.turn_secret))
            for endpoint in ("/semantic","/semantic/context"):
                status,_=self.request(endpoint,data,self.owner)
                self.assertEqual(status,403)
        expired=issue_grant(self.secret,True,self.session,now=int(time.time())-600)
        self.assertIsNone(authorized_semantic_speaker(
            {**self.good,"owner_grant":expired},self.owner,self.turn_secret))

    def test_owner_grant_alone_voice_score_and_self_claim_are_denied(self):
        for changes in (
            {"turn_attestation": ""},
            {"turn_attestation": "person:owner"},
            {"turn_attestation": self.ticket[:-3]+"bad"},
            {"item_id": "different_item"},
            {"transcript": "another transcript"},
            {"query": "other private fact"},
            {"session_id": "other_verified_session"},
        ):
            forged = {**self.good, **changes}
            self.assertIsNone(authorized_semantic_speaker(
                forged,self.owner,self.turn_secret))
            for endpoint in ("/semantic", "/semantic/context"):
                self.assertEqual(self.request(endpoint, forged, self.owner)[0],403)
        self.assertIsNone(authorized_semantic_speaker(
            self.good,self.owner,None))
        self.assertIsNone(authorized_semantic_speaker(
            self.good,self.owner,self.secret))  # no reused grant key
        self.assertIsNone(authorized_semantic_speaker(
            self.good,self.owner,b"wrong verifier key material 00000000"))

    def test_guest_and_learning_ticket_can_never_unlock_owner(self):
        for purpose,speaker,role in (
                ("turn","person:guest","guest"),
                ("learning","person:owner","owner")):
            ticket=issue_external_attestation(
                self.turn_secret,session_id=self.session,item_id=self.item,
                transcript=self.query,speaker_id=speaker,
                speaker_role=role,purpose=purpose,
                audio_sha256="a"*64 if purpose=="learning" else None)
            data={**self.good,"turn_attestation":ticket}
            self.assertIsNone(authorized_semantic_speaker(
                data,self.owner,self.turn_secret))
            self.assertEqual(self.request(
                "/semantic/context",data,self.owner)[0],403)

    def test_missing_device_authorization_denied_even_with_owner_grant(self):
        for endpoint in ("/semantic","/semantic/context"):
            status,_=self.request(endpoint,self.good,self.owner,token="wrong")
            self.assertEqual(status,401)

    def test_denied_requests_do_not_access_index(self):
        forbidden=self.good.copy()
        forbidden["owner_grant"]="invalid"
        with mock.patch("kitty_memory_context_v6.recall_context",
                        side_effect=AssertionError("private context must not load")):
            with mock.patch("kitty_sd_semantic_index.search",
                            side_effect=AssertionError("private search must not load")):
                for endpoint in ("/semantic","/semantic/context"):
                    self.assertEqual(self.request(endpoint,forbidden,self.owner)[0],403)

    def test_wrong_typed_or_excessively_long_parameters_denied(self):
        for data in (None,[],{"speaker_id":"person:owner","session_id":42,
                               "owner_grant":self.grant},
                     {**self.good,"owner_grant":"x"*1025}):
            self.assertIsNone(authorized_semantic_speaker(
                data,self.owner,self.turn_secret))


if __name__=="__main__":
    unittest.main()
