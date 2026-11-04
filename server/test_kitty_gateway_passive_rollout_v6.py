#!/usr/bin/env python3
"""Unit-test the host-side Docker rollout orchestration with no Docker calls."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import kitty_gateway_passive_rollout_v6 as d


class RolloutSafetyTests(unittest.TestCase):
    def test_only_known_pure_python_helpers_staged(self):
        self.assertEqual(len(d.HELPERS),8)
        self.assertEqual(len(set(d.HELPERS)),8)
        self.assertIn("kitty_attested_live_call_v6.py",d.HELPERS)
        self.assertIn("kitty_passive_turn_bridge_v6.py",d.HELPERS)
        self.assertNotIn("kitty_memory_service.py",d.HELPERS)
        self.assertNotIn("realtime.py",d.HELPERS)
        self.assertNotIn("kitty_voice_learning_v6.py",d.HELPERS)
        self.assertIn("open_webui/routers/audio/realtime.py",str(d.LIVE))

    def test_manifest_is_local_private_owner_only(self):
        with tempfile.TemporaryDirectory() as root:
            store=Path(root)/"private"
            with patch.object(d,"STORE",store),patch.object(
                    d,"MANIFEST",store/"transaction.json"):
                d.save_manifest({"status":"prepared",
                                 "backup":"<private-host-copy>"})
                self.assertEqual(d.MANIFEST.stat().st_mode & 0o777,0o600)
                self.assertEqual(d.STORE.stat().st_mode & 0o777,0o700)
                self.assertEqual(json.loads(d.MANIFEST.read_text())[
                    "status"],"prepared")

    def test_prior_installation_blocks_repeat_before_source_patching(self):
        with tempfile.TemporaryDirectory() as root:
            store=Path(root)/"state"
            with patch.object(d,"STORE",store),patch.object(
                    d,"MANIFEST",store/"transaction.json"),patch.object(
                    d,"get_container_health",return_value="healthy"),patch.object(
                    d,"command") as cmd,patch.object(
                    d,"docker") as docker:
                d.save_manifest({"status":"installed"})
                with self.assertRaises(d.DeployRefusal) as cm:
                    d.apply()
                self.assertEqual(str(cm.exception),"previous_transaction_exists")
                cmd.assert_not_called()
                docker.assert_not_called()

    def test_nonhealthy_gateway_never_runs_installation(self):
        with patch.object(d,"get_container_health",return_value="starting"),patch.object(
                d,"git_source") as git:
            with self.assertRaises(d.DeployRefusal) as cm:
                d.apply()
            self.assertEqual(str(cm.exception),"gateway_not_healthy")
            git.assert_not_called()

    def test_restore_refuses_hash_conflict_or_missing_backup(self):
        with tempfile.TemporaryDirectory() as root:
            backup=Path(root)/"private.py"
            backup.write_bytes(b"untouched custom realtime gateway")
            state={"backup":str(backup),"before":d.sha(backup.read_bytes()),
                   "after":d.sha(b"patched"),"created":[],
                   "helper_hashes":{}}
            with patch.object(d,"target_status",return_value=d.sha(b"newer third-party edit")),patch.object(
                    d,"docker") as docker:
                with self.assertRaises(d.DeployRefusal) as cm:
                    d.restore(state,strict=True)
                self.assertEqual(str(cm.exception),"rollback_conflict")
                docker.assert_not_called()

    def test_docker_calls_have_fixed_container_and_workdir(self):
        with patch.object(d,"docker",return_value=b"ok") as docker:
            self.assertEqual(d.docker_exec("print('safe')"),b"ok")
            argv=docker.call_args.args
            self.assertEqual(argv[:5],
                             ("exec","-w","/app/backend","open-webui","python3"))


if __name__=="__main__":
    unittest.main()
