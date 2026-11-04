#!/usr/bin/env python3
"""No Docker/network: verify safe inode-preserving read-only bind deployment."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import kitty_gateway_bind_rollout_v6 as d


class BindRolloutTests(unittest.TestCase):
    def test_read_only_file_bind_is_required_and_source_not_exposed(self):
        secret="/host/private/kitty-gateway-live-realtime.py"
        fixture=[{"Destination":d.LIVE,"Type":"bind","RW":False,
                  "Source":secret},
                 {"Destination":"/app/backend/data","Type":"volume",
                  "RW":True,"Source":"secret_volume_name"}]
        with patch.object(d,"docker",
                          return_value=json.dumps(fixture).encode()):
            self.assertEqual(d.mounted_host_source(),secret)
        for bad in (
            [{"Destination":d.LIVE,"Type":"bind","RW":True,"Source":secret}],
            [{"Destination":"/app/backend","Type":"bind","RW":False,"Source":secret}],
            [{"Destination":d.LIVE,"Type":"volume","RW":False,"Source":secret}],
            [{"Destination":d.LIVE,"Type":"bind","RW":False,"Source":"relative"}],
            fixture[:1]*2):
            with patch.object(d,"docker",return_value=json.dumps(bad).encode()):
                with self.assertRaises(d.Refusal):
                    d.mounted_host_source()

    def test_same_inode_and_owner_after_exact_in_place_update(self):
        with tempfile.TemporaryDirectory() as folder:
            original=Path(folder)/"realtime.py"
            original.write_bytes(b"old source content")
            before=d.host_file_stat(str(original))
            self.assertTrue(d.overwrite_same_inode(str(original),
                            b"new source code",before["sha"],before))
            after=d.host_file_stat(str(original))
            self.assertEqual(after["sha"],d.sha(b"new source code"))
            for key in ("ino","dev","mode","uid","gid"):
                self.assertEqual(after[key],before[key])
            self.assertTrue(d.overwrite_same_inode(str(original),
                            b"old source content",after["sha"],before))
            self.assertEqual(original.read_bytes(),b"old source content")

    def test_cannot_overwrite_modified_gateway_without_exact_sha(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/"realtime.py"
            target.write_bytes(b"original")
            before=d.host_file_stat(str(target))
            target.write_bytes(b"third-party change")
            with self.assertRaises(d.Refusal):
                d.overwrite_same_inode(str(target),b"patched",before["sha"],before)
            self.assertEqual(target.read_bytes(),b"third-party change")

    def test_python_host_root_writer_does_not_replace_target_inode(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/"realtime.py"
            target.write_bytes(b"before")
            meta=d.host_file_stat(str(target))
            result=subprocess.run(
                [sys.executable,"-c",d.ROOT_HELPER,str(target),meta["sha"],
                 json.dumps(meta)],input=b"after",
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
            self.assertEqual(result.returncode,0,
                             result.stderr.decode(errors="replace")[:250])
            self.assertEqual(result.stdout,b"verified\n")
            after=d.host_file_stat(str(target))
            self.assertEqual(after["ino"],meta["ino"])
            self.assertEqual(after["sha"],d.sha(b"after"))
            self.assertEqual(after["uid"],meta["uid"])
            self.assertEqual(after["mode"],meta["mode"])

    def test_root_writer_rejects_wrong_expected_hash_without_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/"realtime.py"
            target.write_bytes(b"live file")
            meta=d.host_file_stat(str(target))
            p=subprocess.run([sys.executable,"-c",d.ROOT_HELPER,str(target),
                              d.sha(b"outdated file"),json.dumps(meta)],
                             input=b"malicious replacement",
                             stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            self.assertNotEqual(p.returncode,0)
            self.assertEqual(target.read_bytes(),b"live file")

    def test_private_backup_mode_and_integrity(self):
        with tempfile.TemporaryDirectory() as folder:
            backup=Path(folder)/"original.py"
            d.file_copy_private(backup,b"private source")
            self.assertEqual(backup.stat().st_mode & 0o777,0o600)
            self.assertEqual(backup.read_bytes(),b"private source")
            with self.assertRaises(d.Refusal):
                d.file_copy_private(backup,b"altered source")

    def test_existing_transaction_never_reapplied(self):
        with tempfile.TemporaryDirectory() as folder:
            state=Path(folder)/"private"
            with patch.object(d,"STORE",state),patch.object(
                    d,"MANIFEST",state/"transaction.json"),patch.object(
                    d,"health",return_value="healthy"),patch.object(
                    d,"git_sha") as git:
                d.save({"status":"installed"})
                with self.assertRaises(d.Refusal) as e:
                    d.apply()
                self.assertEqual(str(e.exception),
                                 "previous_installation_or_unfinished_transaction")
                git.assert_not_called()

    def test_source_helpers_are_observer_only(self):
        self.assertEqual(len(d.HELPERS),8)
        self.assertNotIn("kitty_voice_learning_v6.py",d.HELPERS)
        self.assertNotIn("kitty_memory_service.py",d.HELPERS)
        self.assertIn("kitty_passive_turn_bridge_v6.py",d.HELPERS)


if __name__=="__main__":
    unittest.main()
