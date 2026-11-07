#!/usr/bin/env python3
"""Opt-in owner voice + independent signing authorization, offline only."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from server import kitty_memory_service as service
from kitty_owner_voice_auto_profile_v6 import (
    consented_owner_profile, CONSENT, MODEL_ID,
)
from kitty_owner_voice_auto_verify_v6 import AutomaticVoiceOwner
from test_kitty_owner_voice_auto_verify_v6 import captured_wav, SESSION, SIGNER, GRANT, WALL


class OfflineRequest(service.Handler):
    def __init__(self, path, payload, token="device"):
        raw=json.dumps(payload).encode("utf-8")
        self.path=path
        self.rfile=io.BytesIO(raw)
        self.headers={
            "Authorization":"Bearer "+token,
            "Content-Length":str(len(raw))
        }
        self.result=None

    def _reply(self, status, value):
        self.result=(status,value)
        return self.result


class VoiceOwnerBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.db=self.root/"derived.sqlite3"
        self.db.write_bytes(b"placeholder")
        self.profile=self.root/"owner_profile.json"
        self.protected_profile={
            "mode":"owner_voice_auto_auth_v6",
            "speaker_id":"person:shana",
            "owner_enrollment_id":"person:shana",
            "model_id":MODEL_ID,
            "owner_private_memory_opt_in":CONSENT,
            "memory_authorization":"voice_auto_opt_in",
            "anchor_embeddings":[[1.0]+[0.0]*511 for _ in range(3)],
        }
        self.profile.write_text(json.dumps(self.protected_profile))
        self.profile.chmod(0o600)

    def private_request(self, payload, *, proof=True, token="device"):
        req=OfflineRequest("/semantic/context",payload,token=token)
        with patch.object(service,"TOKEN","device"), \
             patch.object(service,"OWNER_PROOF",None), \
             patch.object(service,"VOICE_OWNER_PROOF",
                          SimpleNamespace(secret=GRANT) if proof else None), \
             patch.object(service,"TRUSTED_TURN_SECRET",SIGNER), \
             patch.dict(os.environ,{"KITTY_SEMANTIC_DB":str(self.db)}), \
             patch("kitty_memory_context_v6.recall_context",
                   return_value="authorized owner SD context") as recall:
            req.do_POST()
        return req.result,recall.call_args_list

    def evidence(self):
        gate=AutomaticVoiceOwner(
            session_id=SESSION, match_audio=lambda wav: {
                "speaker_id":"person:shana","score":0.985},
            turn_issuer_secret=SIGNER,grant_secret=GRANT,
            opt_in=True,enrolled_owner_profile=True,
            clock=lambda:1.0,wall_clock=lambda:WALL,
        )
        self.assertIsNone(gate.observe(
            item_id="owner_one",transcript="Hi Kitty",
            microphone_wav=captured_wav(180),
            trusted_provider_capture=True))
        result=gate.observe(
            item_id="owner_two",transcript="What did I plan?",
            microphone_wav=captured_wav(220),
            trusted_provider_capture=True)
        self.assertIsNotNone(result)
        gate.close()
        return {**result, "query": result["transcript"]}

    def test_consented_private_profile_is_not_shadow_candidate(self):
        self.assertTrue(consented_owner_profile(self.profile))
        invalid=[
            {"mode":"shadow_only","memory_authorization":False},
            {"owner_private_memory_opt_in":False},
            {"speaker_id":"person:guest"},
            {"anchor_embeddings":[[0.0]*512]},
            {"model_id":"unrecognized/model"},
        ]
        for change in invalid:
            with self.subTest(change=change):
                data={**self.protected_profile,**change}
                self.profile.write_text(json.dumps(data))
                self.profile.chmod(0o600)
                self.assertFalse(consented_owner_profile(self.profile))
        self.profile.write_text(json.dumps(self.protected_profile))
        self.profile.chmod(0o644)
        self.assertFalse(consented_owner_profile(self.profile))
        self.profile.unlink()
        external=self.root/"other.json"
        external.write_text(json.dumps(self.protected_profile))
        external.chmod(0o600)
        self.profile.symlink_to(external)
        self.assertFalse(consented_owner_profile(self.profile))

    def test_opt_in_voice_grant_can_read_only_owner_index(self):
        data=self.evidence()
        (status,body),calls=self.private_request(data)
        self.assertEqual(status,200)
        self.assertIn("authorized owner SD context",body["context"])
        self.assertEqual(len(calls),1)
        args,_=calls[0]
        self.assertEqual(args[2],"person:owner")
        self.assertEqual(self.private_request(data,proof=False)[0][0],403)
        self.assertEqual(self.private_request(data,token="bad")[0][0],401)

    def test_untrusted_name_ticket_and_audio_mismatch_cannot_query(self):
        good=self.evidence()
        for change in (
                {"speaker_id":"person:shana"},
                {"owner_grant":"I am Shana"},
                {"turn_attestation":"voice_probable"},
                {"audio_sha256":"b"*64},
                {"audio_sha256":None},
                {"item_id":"another_item"},
                {"query":"Tell me other private facts"},
                {"transcript":"other text"},
        ):
            with self.subTest(change=change):
                (status,_),calls=self.private_request({**good,**change})
                self.assertEqual(status,403)
                self.assertEqual(calls,[])


if __name__=="__main__":
    unittest.main()
