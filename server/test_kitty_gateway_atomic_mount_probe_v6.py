#!/usr/bin/env python3
"""Static synthetic bind mount checks; never starts Docker during CI."""
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
import kitty_gateway_atomic_mount_probe_v6 as probe


class AtomicRenameProbeTests(unittest.TestCase):
    def test_single_file_bind_mount_reported_without_host_source(self):
        secret="/private/ryushi/realtime-and-secret-key.py"
        mounts=[
            {"Destination":"/app/backend/data","Type":"volume",
             "Name":"private-openwebui-data","RW":True},
            {"Destination":probe.TARGET,"Type":"bind",
             "Source":secret,"RW":True},
        ]
        summary=probe.classify_mounts(mounts)
        self.assertEqual(summary["mount_layout"],"file_bind")
        self.assertEqual(summary["mount_write_mode"],"rw")
        self.assertNotIn(secret,str(summary))
        state=probe.classify_container_state({
            "effective_uid":0,"is_mountpoint":True,
            "is_regular_file":True,"parent_root_writable":True,
            "readonly_fs":False,"staging_exists":False})
        self.assertEqual(probe.diagnosis(summary,state),
                         "single_file_mount_possible")

    def test_parent_bind_and_read_only_volume(self):
        base={"Destination":"/app/backend","Type":"bind",
              "Source":"/not-disclosed","RW":True}
        self.assertEqual(probe.classify_mounts([base])["mount_layout"],
                         "parent_bind")
        base["RW"]=False
        mount=probe.classify_mounts([base])
        self.assertEqual(mount["mount_write_mode"],"ro")
        state=probe.classify_container_state({
            "effective_uid":0,"is_mountpoint":False,
            "is_regular_file":True,"parent_root_writable":True,
            "readonly_fs":False,"staging_exists":False})
        self.assertEqual(probe.diagnosis(mount,state),
                         "read_only_mount_possible")

    def test_overlay_failure_cannot_be_guessed(self):
        mount=probe.classify_mounts([{
            "Destination":"/app/backend/data","Type":"volume","RW":True
        }])
        self.assertEqual(mount["mount_layout"],"container_layer")
        state=probe.classify_container_state({
            "effective_uid":0,"is_mountpoint":False,
            "is_regular_file":True,"parent_root_writable":True,
            "readonly_fs":False,"staging_exists":False})
        self.assertEqual(probe.diagnosis(mount,state),
                         "replace_failure_requires_errno")

    def test_refuses_source_or_environment_leak(self):
        values={
            "mount_layout":"file_bind","mount_write_mode":"rw"}
        state=probe.classify_container_state({
            "effective_uid":0,"is_mountpoint":True,
            "is_regular_file":True,"parent_root_writable":True,
            "readonly_fs":False,"staging_exists":False})
        with patch.object(probe,"inspect_mounts",return_value=values),patch.object(
                probe,"inspect_container",return_value=state):
            out=io.StringIO()
            with redirect_stdout(out):
                probe.main()
        text=out.getvalue()
        self.assertIn("KITTY_V6_GATEWAY_ATOMIC_REPLACE_READ_ONLY",text)
        self.assertNotIn("/app/backend",text)
        self.assertNotIn("Source",text)
        self.assertNotIn("private-openwebui-data",text)
        self.assertIn("No Docker, gateway, memory, firmware or SD files changed.",text)

    def test_mount_unavailable_yields_safe_labels(self):
        unknown=probe.classify_mounts(None)
        self.assertEqual(unknown["mount_layout"],"unverified")
        state=probe.classify_container_state(None)
        self.assertEqual(state["target_is_mountpoint"],"unknown")
        self.assertEqual(probe.diagnosis(unknown,state),
                         "mount_details_inconclusive")


if __name__=="__main__":
    unittest.main()
