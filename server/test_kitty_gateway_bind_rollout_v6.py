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

    def test_root_metadata_fallback_reveals_no_source_data(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/"gateway.py"
            target.write_bytes(b"private = 'do not print'\n")
            expected=d.host_file_stat(str(target))
            fake_output=json.dumps(expected).encode()
            with patch.object(d,"host_file_stat",
                              side_effect=d.Refusal("host_source_read_denied")),patch.object(
                              d,"cmd",return_value=fake_output) as command:
                result=d.verified_host_stat(str(target))
            self.assertEqual(result,expected)
            self.assertNotIn("private",str(result))
            self.assertEqual(command.call_args.args[0][:3],
                             ["sudo","python3","-c"])

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

    def _exercise_transaction(self, fail_start=False):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            p=folder/"source.py"
            p.write_bytes(b"print('working gateway')\n")
            base=d.host_file_stat(str(p))
            store=folder/"private_state"
            active={"running":True,"stops":0,"starts":0}
            copies={n:b"# safe observer dependency\n" for n in d.HELPERS}
            def fake_docker(*args,**kwargs):
                if args[0]=="stop":
                    active["running"]=False
                    active["stops"]+=1
                elif args[0]=="start":
                    active["running"]=True
                    active["starts"]+=1
                return b""
            def fake_root(path,data,expected,meta):
                d.overwrite_same_inode(path,data,expected,meta)
            def fake_inventory():
                return {n:d.sha(data) for n,data in copies.items()}
            wellness=iter([False,True]) if fail_start else iter([True])
            with patch.object(d,"STORE",store),patch.object(
                    d,"MANIFEST",store/"transaction.json"),patch.object(
                    d,"health",return_value="healthy"),patch.object(
                    d,"state",side_effect=lambda:
                    "running" if active["running"] else "exited"),patch.object(
                    d,"mounted_host_source",return_value=str(p)),patch.object(
                    d,"source_in_container",side_effect=lambda:p.read_bytes()),patch.object(
                    d,"github_file",side_effect=lambda ref,name:copies[name]),patch.object(
                    d,"git_sha",return_value="a"*40),patch.object(
                    d,"patcher_from_git",return_value=SimpleNamespace(
                    patch=lambda src:src+"# passive observation only\n")),patch.object(
                    d,"helper_inventory",side_effect=fake_inventory),patch.object(
                    d,"root_write",side_effect=fake_root),patch.object(
                    d,"docker",side_effect=fake_docker),patch.object(
                    d,"wait_healthy",side_effect=lambda:next(wellness)),patch.object(
                    d,"remove_created"):
                if fail_start:
                    with self.assertRaises(d.Refusal) as err:
                        d.apply()
                    self.assertEqual(str(err.exception),"deployment_failed:start")
                    self.assertEqual(p.read_bytes(),b"print('working gateway')\n")
                    self.assertEqual(active["stops"],2)
                    self.assertEqual(active["starts"],2)
                    self.assertEqual(json.loads(d.MANIFEST.read_text())[
                        "status"],"rolled_back")
                else:
                    d.apply()
                    self.assertIn(b"passive observation only",p.read_bytes())
                    self.assertEqual(active["stops"],1)
                    self.assertEqual(active["starts"],1)
                    self.assertEqual(json.loads(d.MANIFEST.read_text())[
                        "status"],"installed")
                after=d.host_file_stat(str(p))
                for key in ("ino","dev","uid","gid","mode"):
                    self.assertEqual(after[key],base[key])
                self.assertTrue(active["running"])

    def test_complete_transaction_stops_once_and_preserves_inode(self):
        self._exercise_transaction(fail_start=False)

    def test_unhealthy_restart_rolls_back_original_in_same_inode(self):
        self._exercise_transaction(fail_start=True)

    def test_source_helpers_are_observer_only(self):
        self.assertEqual(len(d.HELPERS),8)
        self.assertNotIn("kitty_voice_learning_v6.py",d.HELPERS)
        self.assertNotIn("kitty_memory_service.py",d.HELPERS)
        self.assertIn("kitty_passive_turn_bridge_v6.py",d.HELPERS)


if __name__=="__main__":
    unittest.main()
