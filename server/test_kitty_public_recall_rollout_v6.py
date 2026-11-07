#!/usr/bin/env python3
"""Offline transaction tests, no Docker/service/SD/network operations."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import kitty_public_recall_rollout_v6 as d


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.host = self.root / "host"
        self.host.mkdir()
        self.state_dir = self.root / "rollback"
        self.host_old = {name: ("# initial " + name + "\n").encode()
                         for name in d.HOST_FILES}
        self.host_new = {name: ("# approved update " + name + "\n").encode()
                         for name in d.HOST_FILES}
        for name, data in self.host_old.items():
            (self.host / name).write_bytes(data)
            (self.host / name).chmod(0o600)
        self.previous = b"# existing working call notes\n"
        self.container = {d.CONTAINER_FILES[0]: self.previous,
                          d.CONTAINER_FILES[1]: None}
        self.new_container = {
            d.CONTAINER_FILES[0]: b"# new working call notes\n",
            d.CONTAINER_FILES[1]: b"# approved public query\n",
        }
        self.health_checks = 0
        self.fail_first_health = False
        self.restart_count = 0
        self.docker_restarts = 0
        self.command_log = []

    def fake_command(self, args, **kwargs):
        if args == ["systemctl", "--user", "restart", d.SERVICE]:
            self.restart_count += 1
            return b""
        raise AssertionError("unrecognized command: " + str(args))

    def fake_docker(self, *args, **kwargs):
        self.command_log.append(args)
        if args[0] == "cp":
            name = Path(args[2].split(":")[-1]).name
            self.container[name] = Path(args[1]).read_bytes()
            return b""
        if args[0] == "restart":
            self.docker_restarts += 1
            return b""
        if args[0] == "exec":
            self.container[d.CONTAINER_FILES[1]] = None
            return b""
        raise AssertionError("unexpected Docker action")

    def fake_health(self):
        self.health_checks += 1
        if self.fail_first_health and self.health_checks == 1:
            return False
        return True

    def exercise(self, fail=False):
        self.fail_first_health = fail
        import contextlib
        with contextlib.ExitStack() as stack:
            for name, val in (("HOST_ROOT", self.host),
                              ("STORE", self.state_dir),
                              ("MANIFEST", self.state_dir / "state.json")):
                stack.enter_context(patch.object(d, name, val))
            stack.enter_context(patch.object(
                d, "preflight", return_value=(
                    "a" * 40, self.host_old, self.host_new,
                    {name: 0o600 for name in d.HOST_FILES},
                    self.previous, self.new_container)))
            stack.enter_context(patch.object(d, "command", side_effect=self.fake_command))
            stack.enter_context(patch.object(d, "docker", side_effect=self.fake_docker))
            stack.enter_context(patch.object(
                d, "container_bytes",
                side_effect=lambda name, **kw: self.container[name]))
            for name in ("service_active", "service_source_verified",
                         "gateway_ok", "public_endpoint_ok"):
                stack.enter_context(patch.object(d, name, return_value=True))
            stack.enter_context(patch.object(d, "container_health", return_value="healthy"))
            stack.enter_context(patch.object(d, "wait_health", side_effect=self.fake_health))
            if fail:
                with self.assertRaises(d.Refusal):
                    d.apply()
                self.assertEqual(json.loads(d.MANIFEST.read_text())["status"],
                                 "rolled_back")
                self.assertEqual(self.restart_count, 2)
                self.assertEqual(self.docker_restarts, 2)
            else:
                d.apply()
                self.assertEqual(json.loads(d.MANIFEST.read_text())["status"],
                                 "installed")
                self.assertEqual(self.restart_count, 1)
                self.assertEqual(self.docker_restarts, 1)
                for name, data in self.host_new.items():
                    self.assertEqual((self.host / name).read_bytes(), data)
                for name, data in self.new_container.items():
                    self.assertEqual(self.container[name], data)
                # Restore old modules from private backups with exact checks.
                d.rollback()
                self.assertEqual(json.loads(d.MANIFEST.read_text())["status"],
                                 "rolled_back")
                self.assertEqual(self.restart_count, 2)
                self.assertEqual(self.docker_restarts, 2)
            for name, data in self.host_old.items():
                self.assertEqual((self.host / name).read_bytes(), data)
            self.assertEqual(self.container[d.CONTAINER_FILES[0]], self.previous)
            self.assertIsNone(self.container[d.CONTAINER_FILES[1]])
            for name in list(d.HOST_FILES) + [d.CONTAINER_FILES[0]]:
                self.assertEqual((self.state_dir / (name + ".before")).stat().st_mode
                                 & 0o777, 0o600)

    def test_install_and_manual_rollback(self):
        self.exercise()

    def test_failed_health_automatically_restores_both_services(self):
        self.exercise(fail=True)

    def test_custom_live_host_source_refused_without_write(self):
        with patch.object(d, "MANIFEST", self.root / "state.json"), \
             patch.object(d, "pinned_sha", return_value="a" * 40), \
             patch.object(d, "service_active", return_value=True), \
             patch.object(d, "service_source_verified", return_value=True), \
             patch.object(d, "container_health", return_value="healthy"), \
             patch.object(d, "gateway_ok", return_value=True), \
             patch.object(d, "public_endpoint_ok", return_value=True), \
             patch.object(d, "host_bytes", return_value=(b"custom source", 0o600)), \
             patch.object(d, "git_file", return_value=b"tracked old source"):
            with self.assertRaisesRegex(d.Refusal, "custom_host_module_refused"):
                d.preflight()
        self.assertFalse((self.root / "state.json").exists())

    def test_no_private_memory_or_realtime_route_modified(self):
        src = Path(d.__file__).read_text()
        self.assertNotIn("KITTY_OWNER_GRANT_SECRET_HEX=", src)
        self.assertNotIn("owner_proof=enabled", src)
        self.assertNotIn("SD_MMC.open(", src)
        self.assertIn("gateway_bind=unchanged", src)
        self.assertIn("owner_private_recall=disabled", src)
        self.assertEqual(len(d.HOST_FILES), 2)
        self.assertEqual(len(d.CONTAINER_FILES), 2)


if __name__ == "__main__":
    unittest.main()
