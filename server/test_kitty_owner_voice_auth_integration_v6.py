#!/usr/bin/env python3
"""Synthetic end-to-end proof/recall contract; no live gateway or audio I/O."""
import asyncio
import io
import struct
import unittest
import wave
from types import SimpleNamespace

from kitty_attested_live_call_v6 import AttestedLiveCall
from kitty_owner_voice_auth_issuer_v6 import VoiceOwnerIssuer
from kitty_semantic_authorization_v6 import authorized_semantic_speaker

GRANT_KEY = b"separate-voice-owner-grant-test-key-32!"
TURN_KEY = b"separate-voice-owner-turn-test-key-32!!"


def sample(k):
    result = io.BytesIO()
    with wave.open(result, "wb") as wav:
        wav.setframerate(16000)
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.writeframes(b"".join(
            struct.pack("<h", 2600 if (i + k) % (100+k) < 50 else -2600)
            for i in range(32000)))
    return result.getvalue()


class VoiceRecallIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_owner_voice_proof_follows_existing_private_history_gate(self):
        now = 1_900_000_000
        call = AttestedLiveCall(
            attestation_secret=TURN_KEY, owner_grant_secret=GRANT_KEY,
            wall_clock=lambda: now)
        sid = call.session_id
        records = {}
        profile = {
            "voice_owner_auth_consent": True,
            "voice_owner_auth_min_score": 0.975,
            "voice_owner_auth_min_margin": 0.10,
            "owner_enrollment_id": "person:shana",
            "model_id": "pinned-xvector-model",
            "memory_authorization": False,
            "anchor_embeddings": [[1], [1], [1]],
        }
        issuer = VoiceOwnerIssuer(
            profile_loader=lambda: profile,
            capture_lookup=lambda session, item: records[item],
            score_audio=lambda audio: {
                "source": "issuer_local_model", "model_id": "pinned-xvector-model",
                "speaker_id": "person:shana", "candidate_only": False,
                "score": 0.987, "runner_up_score": 0.5},
            grant_secret=GRANT_KEY, turn_secret=TURN_KEY,
            clock=lambda: now)
        self.assertTrue(issuer.begin_call(sid))
        issued = None
        for i in range(1, 4):
            item = "mic_item_" + str(i)
            transcript = "What did I ask Kitty to remember?"
            call.upstream_speech_started()
            self.assertTrue(call.upstream_speech_stopped(item))
            self.assertTrue(call.upstream_transcript_completed(item, transcript))
            records[item] = {
                "source": "gateway_observed_s3_microphone",
                "authenticated_s3_session": True,
                "final_transcript": True,
                "overlap": False,
                "playback_active": False,
                "session_id": sid,
                "item_id": item,
                "wav": sample(i),
                "transcript": transcript,
                "captured_at": now,
            }
            issued = issuer.verify_microphone_turn(item)
            if i < 3:
                self.assertIsNone(issued)
                self.assertEqual(call.context_for_verified_turn(item), "")
        self.assertTrue(call.verify_turn(
            "mic_item_3", issued["turn_attestation"],
            owner_grant=issued["owner_grant"],
            audio_sha256=issued["audio_sha256"]))
        owner_proof = SimpleNamespace(secret=GRANT_KEY)
        payload = {
            "speaker_id": "person:owner", "session_id": sid,
            "item_id": "mic_item_3", "transcript": transcript,
            "query": transcript,
            "owner_grant": issued["owner_grant"],
            "turn_attestation": issued["turn_attestation"],
            "audio_sha256": issued["audio_sha256"],
        }
        self.assertEqual(authorized_semantic_speaker(
            payload, owner_proof, TURN_KEY, now=now), "person:owner")
        self.assertIsNone(authorized_semantic_speaker(
            {**payload, "audio_sha256": "0"*64}, owner_proof, TURN_KEY, now=now))
        self.assertIsNone(authorized_semantic_speaker(
            {key:value for key,value in payload.items()
             if key != "audio_sha256"}, owner_proof, TURN_KEY, now=now))
        self.assertIsNone(authorized_semantic_speaker(
            {**payload, "query":"Tell me someone else's secret"},
            owner_proof, TURN_KEY, now=now))

        observed = []
        async def local_lookup(url, token, query, session_id, grant, **evidence):
            observed.append(evidence)
            check = dict(payload)
            check.update(evidence)
            return "private SD-derived context" if (
                authorized_semantic_speaker(
                    check, owner_proof, TURN_KEY, now=now) == "person:owner") else ""
        recalled = await call.owner_history_for_verified_turn(
            "mic_item_3", "http://127.0.0.1:8766",
            "local-token", issued["owner_grant"], lookup=local_lookup)
        self.assertEqual(recalled, "private SD-derived context")
        self.assertEqual(observed[0]["audio_sha256"], issued["audio_sha256"])
        call.unknown_turn()
        self.assertEqual(await call.owner_history_for_verified_turn(
            "mic_item_3", "http://127.0.0.1:8766",
            "local-token", issued["owner_grant"], lookup=local_lookup), "")

    async def test_semantic_client_forwards_audio_hash_only_when_supplied(self):
        from kitty_semantic_async_client_v6 import owner_semantic_context
        seen = []
        def fake(*args, **kwargs):
            seen.append((args, kwargs))
            return "private SD context"
        params = {
            "item_id": "observed_item_3", "transcript": "Recall my SD notes",
            "turn_attestation": "signed.turn.ticket",
        }
        url = "http://127.0.0.1:8766"
        result = await owner_semantic_context(
            url, "service-token", "Recall my SD notes",
            "some-gateway-session-12345", "grant", audio_sha256="a"*64,
            request_fn=fake, **params)
        self.assertEqual(result, "private SD context")
        self.assertEqual(seen[0][1], {"audio_sha256": "a"*64})
        result = await owner_semantic_context(
            url, "service-token", "Recall my SD notes",
            "some-gateway-session-12345", "grant", request_fn=fake, **params)
        self.assertEqual(result, "private SD context")
        self.assertEqual(seen[1][1], {})
        result = await owner_semantic_context(
            url, "service-token", "Recall my SD notes",
            "some-gateway-session-12345", "grant", audio_sha256="not-a-hash",
            request_fn=fake, **params)
        self.assertEqual(result, "")
        self.assertEqual(len(seen), 2)

    async def test_wrong_microphone_digest_rejected_before_owner_context(self):
        now = 1_900_000_000
        call = AttestedLiveCall(
            attestation_secret=TURN_KEY, owner_grant_secret=GRANT_KEY,
            wall_clock=lambda: now)
        from kitty_attested_live_call_v6 import issue_external_attestation
        from kitty_owner_session_v6 import issue_grant
        sid = call.session_id
        call.upstream_speech_stopped("item1")
        call.upstream_transcript_completed("item1", "hello")
        ticket = issue_external_attestation(
            TURN_KEY, session_id=sid, item_id="item1", transcript="hello",
            speaker_id="person:owner", speaker_role="owner",
            audio_sha256="a"*64, now=now)
        grant = issue_grant(GRANT_KEY, True, sid, now=now)
        self.assertFalse(call.verify_turn(
            "item1", ticket, owner_grant=grant, audio_sha256="b"*64))
        self.assertEqual(call.context_for_verified_turn("item1"), "")


if __name__ == "__main__":
    unittest.main()
