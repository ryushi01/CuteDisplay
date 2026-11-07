#!/usr/bin/env python3
"""Attested gateway context adapter: never provide private data after interruption."""
import asyncio
import unittest
from kitty_attested_live_call_v6 import AttestedLiveCall, issue_external_attestation
from kitty_owner_session_v6 import issue_grant
from kitty_turn_context_v6 import attested_voice_turn_context

SIGNER=b"T"*32
OWNER=b"O"*32
LOCAL="http://127.0.0.1:8766"


class AttestedContextAdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now=1_900_000_000
        self.call=AttestedLiveCall(attestation_secret=SIGNER,
            owner_grant_secret=OWNER,wall_clock=lambda:self.now)

    def verify(self,item,text,role="guest",speaker="person:aki",grant=None):
        self.call.upstream_speech_started()
        self.call.upstream_speech_stopped(item)
        self.call.upstream_transcript_completed(item,text)
        ticket=issue_external_attestation(
            SIGNER,session_id=self.call.session_id,item_id=item,
            transcript=text,speaker_id=speaker,speaker_role=role,
            now=self.now)
        return self.call.verify_turn(item,ticket,owner_grant=grant)

    async def test_verified_guest_live_context_never_queries_owner_history(self):
        self.assertTrue(self.verify("a","We decided to keep Bluetooth on C5."))
        seen=[]
        async def forbidden(*args):
            seen.append(args)
            raise AssertionError("guest must not query owner history")
        result=await attested_voice_turn_context(
            self.call,"a",LOCAL,"token","fabricated",
            include_owner_history=True,owner_lookup=forbidden)
        self.assertIn("Bluetooth on C5",result)
        self.assertFalse(seen)

    async def test_owner_private_history_requires_both_proofs(self):
        text="What was our earlier plan?"
        grant=issue_grant(OWNER,True,self.call.session_id,now=self.now,ttl=120)
        self.assertTrue(self.verify("o",text,"owner","person:owner",grant))
        calls=[]
        async def fake(url,token,query,session,proof,**signed):
            calls.append((url,query,session,proof,signed))
            return "- Owner decided to keep the S3 microSD as authority."
        out=await attested_voice_turn_context(
            self.call,"o",LOCAL,"token",grant,
            include_owner_history=True,owner_lookup=fake)
        self.assertIn("microSD",out)
        self.assertEqual(calls[0][1],text)
        self.assertLessEqual(len(out.encode("utf-8")),1800)

    async def test_no_ticket_or_wrong_item_returns_empty(self):
        async def forbidden(*args):
            raise AssertionError("no request should happen")
        self.assertEqual(await attested_voice_turn_context(
            self.call,"bad",LOCAL,"token",include_owner_history=True,
            owner_lookup=forbidden),"")
        self.assertTrue(self.verify("a","My goal is to learn about Saturn."))
        self.assertEqual(await attested_voice_turn_context(
            self.call,"different",LOCAL,"token",include_owner_history=True,
            owner_lookup=forbidden),"")
        self.call.unknown_turn()
        self.assertEqual(await attested_voice_turn_context(
            self.call,"a",LOCAL,"token",include_owner_history=True,
            owner_lookup=forbidden),"")

    async def test_barge_in_during_owner_lookup_discards_all_context(self):
        text="What did I say yesterday?"
        grant=issue_grant(OWNER,True,self.call.session_id,now=self.now,ttl=120)
        self.assertTrue(self.verify("owner-1",text,"owner","person:owner",grant))
        started=asyncio.Event()
        done=asyncio.Event()
        async def fake(*args, **kwargs):
            started.set()
            await done.wait()
            return "private historical secret"
        task=asyncio.create_task(attested_voice_turn_context(
            self.call,"owner-1",LOCAL,"token",grant,
            include_owner_history=True,owner_lookup=fake))
        await asyncio.wait_for(started.wait(),timeout=0.5)
        self.call.upstream_speech_started()
        done.set()
        self.assertEqual(await task,"")

    async def test_fail_closed_without_trusted_bridge(self):
        attr={"speaker_id":"person:owner","provenance":"session_verified",
              "item_id":"a","session_id":"spoofed-session-123"}
        self.assertEqual(await attested_voice_turn_context(
            attr,"a",LOCAL,"token",include_owner_history=True),"")
        self.assertEqual(await attested_voice_turn_context(
            self.call,"a",LOCAL,"token",include_owner_history=True),"")


if __name__=="__main__":
    unittest.main()
