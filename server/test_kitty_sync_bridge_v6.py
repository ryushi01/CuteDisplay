#!/usr/bin/env python3
"""Offline V6 sync/bridge contract tests; no GPU/model/server needed."""
import asyncio
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from kitty_sd_snapshot_v6 import SnapshotReceiver
from kitty_semantic_bridge_v6 import bounded_semantic_context, _bounded_lookup

class SyncContractTests(unittest.TestCase):
    def test_resumable_snapshot_and_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            receiver=SnapshotReceiver(tmp)
            raw="1761800000\tBonjour シャナ\tHello\n".encode()
            self.assertEqual(receiver.chunk("test_20261030","conversations.tsv",0,raw[:12]),12)
            self.assertEqual(receiver.chunk("test_20261030","conversations.tsv",0,raw[:12]),12)
            self.assertEqual(receiver.chunk("test_20261030","conversations.tsv",12,raw[12:]),len(raw))
            with self.assertRaises(ValueError):
                receiver.chunk("test_20261030","conversations.tsv",0,b"incorrect")
            with self.assertRaises(ValueError):
                receiver.finalize("test_20261030",{"conversations.tsv":{"size":len(raw),"sha256":"0"*64}})
            path=receiver.finalize("test_20261030",{"conversations.tsv":{"size":len(raw),"sha256":hashlib.sha256(raw).hexdigest()}})
            self.assertEqual((Path(path)/"kitty"/"conversations.tsv").read_bytes(),raw)
    def test_reject_bad_names_and_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=SnapshotReceiver(tmp)
            with self.assertRaises(ValueError):r.chunk("../danger","facts.tsv",0,b"a")
            with self.assertRaises(ValueError):r.chunk("test_20261030","../../etc/passwd",0,b"a")
            with self.assertRaises(ValueError):r.chunk("test_20261030","facts.tsv",3,b"a")

class BridgeContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_fallback_when_service_disabled(self):
        context,source=await bounded_semantic_context("question","original",url="",token="")
        self.assertEqual((context,source),("original","local"))
    async def test_retrieved_source_not_labeled_owner(self):
        result=[{"speaker_id":"remote_ai:chatgpt","provenance":"explicit_introduction",
                 "text":"ChatGPT spoke with Kitty."}]
        with patch("kitty_semantic_bridge_v6._lookup",return_value=result):
            context,source=await bounded_semantic_context("What did ChatGPT say?","original",url="http://127.0.0.1:8766",token="test")
        self.assertEqual(source,"hybrid")
        self.assertIn("remote_ai:chatgpt",context)
        self.assertTrue(context.startswith("original"))
    async def test_busy_semantic_slot_falls_back_immediately(self):
        from kitty_semantic_bridge_v6 import _LOOKUP_SLOT
        import time
        self.assertTrue(_LOOKUP_SLOT.acquire(blocking=False))
        try:
            start=time.monotonic()
            with patch("kitty_semantic_bridge_v6._lookup",side_effect=AssertionError("must not run")):
                context,source=await bounded_semantic_context("Where?","original",url="http://127.0.0.1:8766",token="test",timeout=0.05)
            self.assertEqual((context,source),("original","local"))
            self.assertLess(time.monotonic()-start,0.5)
        finally:
            _LOOKUP_SLOT.release()

    async def test_timeout_returns_local(self):
        def slow(*args):
            import time
            time.sleep(0.12)
            return []
        with patch("kitty_semantic_bridge_v6._lookup",side_effect=slow):
            context,source=await bounded_semantic_context("What happened?","original",url="http://127.0.0.1:8766",token="test",timeout=0.03)
        self.assertEqual((context,source),("original","local"))

if __name__=="__main__":unittest.main()
