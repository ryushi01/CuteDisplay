#!/usr/bin/env python3
"""Offline-only regression for exact-hash gateway rollout and rollback.

No Docker, sudo, network, provider or real gateway is opened.
"""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import kitty_gateway_response_bound_rollout_v6 as d
from kitty_gateway_response_bound_patch_v6 import patch as patch_route
from test_kitty_gateway_response_bound_patch_v6 import FIXTURE


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class DeploymentTests(unittest.TestCase):
    def test_preflight_builds_source_only_and_never_deploys(self):
        raw = FIXTURE.encode()
        meta = {"sha": digest(raw), "dev": 1, "ino": 2,
                "mode": 0o600, "uid": 1000, "gid": 1000}
        calls = []
        g = SimpleNamespace(
            health=lambda: "healthy",
            mounted_host_source=lambda: "/safe/host/gateway.py",
            verified_host_stat=lambda path: meta,
            source_in_container=lambda: raw,
            sha=digest,
            preflight_host_writable=lambda *args: calls.append("preflight"),
        )
        helper = b"# source-only RAM helper\n"
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(d, "STATE", Path(folder) / "state.json"), \
             patch.object(d, "helper_inventory", return_value="absent"):
            result = d.preflight(g, SimpleNamespace(patch=patch_route), helper)
        self.assertEqual(result[0], "/safe/host/gateway.py")
        self.assertEqual(result[2], raw)
        self.assertEqual(result[3].count(b"await upstream.send_json("),
                         raw.count(b"await upstream.send_json("))
        self.assertEqual(result[4], "absent")
        self.assertEqual(calls, ["preflight"])

    def _exercise(self, fail_health=False):
        raw = FIXTURE.encode()
        changed = patch_route(FIXTURE).encode()
        helper = b"# source-only verified helper\n"
        checksum = digest(raw)
        meta = {"sha": checksum, "dev": 1, "ino": 2,
                "mode": 0o600, "uid": 1000, "gid": 1000}
        state = {"source": raw, "running": True, "stops": 0, "starts": 0,
                 "health_tries": 0}
        def docker(action, container, timeout=75):
            self.assertEqual(container, "open-webui")
            if action == "stop":
                state["running"] = False
                state["stops"] += 1
            elif action == "start":
                state["running"] = True
                state["starts"] += 1
            else:
                raise AssertionError("unexpected docker command")
        def root_write(path, data, expected, info):
            self.assertFalse(state["running"])
            self.assertEqual(digest(state["source"]), expected)
            self.assertEqual(info, meta)
            state["source"] = data
        def recover(path, original, candidate, info):
            self.assertFalse(state["running"])
            self.assertIn(state["source"], (original, candidate))
            state["source"] = original
        def healthy():
            state["health_tries"] += 1
            return not (fail_health and state["health_tries"] == 1)
        g = SimpleNamespace(
            CONTAINER="open-webui",
            sha=digest,
            mounted_host_source=lambda: "/safe/host/gateway.py",
            source_in_container=lambda: state["source"],
            verified_host_stat=lambda _: {"sha": digest(state["source"])},
            file_copy_private=lambda target, data: target.write_bytes(data),
            atomic_private=lambda target, data: target.write_bytes(data),
            docker=docker,
            state=lambda: "running" if state["running"] else "exited",
            root_write=root_write,
            recover_partial_write=recover,
            wait_healthy=healthy,
        )
        with tempfile.TemporaryDirectory() as folder:
            store = Path(folder) / "private"
            with patch.object(d, "STORE", store), \
                 patch.object(d, "STATE", store / "state.json"), \
                 patch.object(d, "ORIGINAL", store / "gateway.py"), \
                 patch.object(d, "components", return_value=(
                     g, SimpleNamespace(patch=patch_route), helper)), \
                 patch.object(d, "preflight", return_value=(
                     "/safe/host/gateway.py", meta, raw, changed, "absent")), \
                 patch.object(d, "copy_helper"), \
                 patch.object(d, "remove_created_helper"), \
                 patch.object(d, "checked", return_value=b"a" * 40):
                if fail_health:
                    with self.assertRaises(d.Refusal):
                        d.install()
                    self.assertEqual(state["source"], raw)
                    self.assertEqual(json.loads(d.STATE.read_text())[
                        "status"], "rolled_back")
                    self.assertEqual(state["stops"], 2)
                    self.assertEqual(state["starts"], 2)
                else:
                    d.install()
                    self.assertEqual(state["source"], changed)
                    self.assertEqual(json.loads(d.STATE.read_text())[
                        "source_ref"], "a" * 40)
                    self.assertEqual(state["stops"], 1)
                    self.assertEqual(state["starts"], 1)
                    d.rollback()
                    self.assertEqual(state["source"], raw)
                    self.assertEqual(json.loads(d.STATE.read_text())[
                        "status"], "rolled_back")
                    self.assertEqual(state["stops"], 2)
                    self.assertEqual(state["starts"], 2)

    def test_successful_install_exact_rollback(self):
        self._exercise(False)

    def test_failed_gateway_health_automatically_rolls_back(self):
        self._exercise(True)

    def test_pinned_revision_hash_must_be_full(self):
        with self.assertRaises(d.Refusal):
            # Refusal must happen before git file/module loading.
            d.components("invalid-revision")

    def test_only_source_backup_and_no_conversation_storage(self):
        source = Path(d.__file__).read_text()
        self.assertNotIn("transcript_archive", source)
        self.assertNotIn("snapshot/chunk", source)
        self.assertNotIn("speaker_grant", source)
        self.assertIn("gateway-before-response-bound.py", source)
        self.assertIn("rollback=completed", source)


if __name__ == "__main__":
    unittest.main()
