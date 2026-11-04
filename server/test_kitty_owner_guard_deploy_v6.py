#!/usr/bin/env python3
"""Offline installer regression; no systemd, HTTP, Docker or real source mutation."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import kitty_owner_guard_deploy_v6 as deploy
import kitty_owner_guard_plan_v6 as plan
from test_kitty_owner_guard_plan_v6 import SOURCE, live_old


class OwnerGuardDeployTests(unittest.TestCase):
    def test_candidate_changes_only_split_semantic_route_branches(self):
        old = live_old()
        replacement = deploy.build_candidate(old, SOURCE, plan)
        self.assertEqual(replacement, SOURCE)
        self.assertEqual(plan._topology(replacement)[1], "combined")
        self.assertEqual(replacement.count("authorized_semantic_speaker(data,OWNER_PROOF)"), 1)

    def test_unexpected_or_partial_sources_refused(self):
        for old in (
                SOURCE, "invalid code !",
                live_old().replace('data.get("speaker_id")', 'data.get("id")'),
                live_old().replace('if self.path=="/semantic":',
                                   'if self.path=="/something_else":')):
            with self.assertRaises(deploy.DeploymentError):
                deploy.build_candidate(old, SOURCE, plan)

    def test_offline_403_routes_and_enrolled_owner_grant(self):
        self.assertTrue(deploy.offline_security_smoke(SOURCE, Path(__file__).parent))

    def test_atomic_backup_and_exact_rollback(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            module_dir = root / "live"
            module_dir.mkdir()
            service = module_dir / "kitty_memory_service.py"
            before = b"original service contents\n"
            after = b"patched service contents\n"
            service.write_bytes(before)
            modules = {"kitty_semantic_authorization_v6.py": "owner auth helper\n",
                       "kitty_memory_context_v6.py": "memory helper\n"}
            with mock.patch.object(deploy, "STATE_DIR", root/"state"):
                data = deploy.create_backup(service, before, list(modules),
                                            after, modules)
                self.assertTrue(Path(data["backup"]).is_file())
                self.assertEqual(deploy.state_file().stat().st_mode & 0o777, 0o600)
                for name, contents in modules.items():
                    deploy.atomic_write(module_dir/name, contents.encode())
                deploy.atomic_write(service, after)
                deploy.restore_original(data)
                self.assertEqual(service.read_bytes(), before)
                self.assertEqual(data["status"], "rolled_back")
                self.assertTrue(all(not (module_dir/name).exists() for name in modules))

    def test_manual_rollback_refuses_other_edits(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            service=root/"kitty_memory_service.py"
            service.write_bytes(b"older")
            with mock.patch.object(deploy,"STATE_DIR",root/"state"):
                data=deploy.create_backup(service,b"older",[],b"patched",{})
                service.write_bytes(b"someone's new code")
                with self.assertRaises(deploy.DeploymentError):
                    deploy.restore_original(data,strict=True)
                self.assertEqual(service.read_bytes(),b"someone's new code")

    def test_fails_closed_when_no_runtime_token(self):
        self.assertFalse(deploy.private_routes_deny_unverified(None))
        self.assertFalse(deploy.private_routes_deny_unverified(""))


if __name__ == "__main__":
    unittest.main()
