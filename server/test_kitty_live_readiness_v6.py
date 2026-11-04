#!/usr/bin/env python3
"""Offline no-secret/no-mutation tests for the live Ubuntu readiness preflight."""
import io
import json
import os
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from kitty_live_readiness_v6 import (
    GATEWAY_MARKERS, MEMORY_MARKERS, gateway_markers, gateway_probe, live_source_for_pid,
    source_markers, probe, main, memory_health, user_unit_info,
)


class FakeRunner:
    def __init__(self, gateway=None, active=True):
        self.calls=[]
        self.gateway=gateway
        self.active=active

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[:3]==["systemctl","--user","show"]:
            result=("ActiveState=active"+chr(10)+"MainPID=123"+chr(10)) if self.active else None
        elif argv[:2]==["docker","inspect"]:
            result="true"
        elif argv[:3]==["docker","exec","open-webui"]:
            if len(argv)>3 and argv[3] in ("python","python3"):
                result=json.dumps(self.gateway) if self.gateway is not None else None
            else:
                result=None
        else:
            raise AssertionError("unexpected action")
        return types.SimpleNamespace(returncode=0 if result is not None else 1,
                                     stdout=result or "",stderr="SECRET MUST NOT PRINT")


class FakeResponse:
    status=200
    def __enter__(self):
        return self
    def __exit__(self,*args):
        return False
    def read(self,n):
        return b'{"ok":true,"pending":0}'


class FakeOpener:
    def __init__(self):
        self.calls=[]
    def open(self,url,timeout):
        self.calls.append((url,timeout))
        return FakeResponse()


class ReadinessTests(unittest.TestCase):
    def test_unit_queries_never_request_service_environment(self):
        runner=FakeRunner()
        self.assertEqual(user_unit_info(runner=runner),("active",123))
        self.assertTrue(all("Environment" not in arg and "ExecStart" not in arg
                            for command in runner.calls for arg in command))

    def test_live_source_resolves_only_named_service_file(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            pid=root/"123"
            pid.mkdir()
            source=root/"kitty_memory_service.py"
            source.write_text("AUTHORIZED SECRET VALUE"+chr(10),encoding="utf-8")
            (pid/"cmdline").write_bytes(
                b"python3"+bytes([0])+b"kitty_memory_service.py"+bytes([0])+b"--port"+bytes([0])+b"8766"+bytes([0]))
            (pid/"cwd").symlink_to(root)
            self.assertEqual(live_source_for_pid(123,proc_root=root),source)
            (pid/"cmdline").write_bytes(b"python3"+bytes([0])+b"other.py"+bytes([0]))
            self.assertIsNone(live_source_for_pid(123,proc_root=root))

    def test_marker_report_contains_only_allowlisted_keys(self):
        source='some token=PRIVATE_SECRET\\n'+MEMORY_MARKERS["owner_grant_gate"]
        report=source_markers(source,MEMORY_MARKERS)
        self.assertEqual(report["owner_grant_gate"],"present")
        self.assertNotIn("PRIVATE_SECRET",json.dumps(report))
        self.assertEqual(source_markers(None,MEMORY_MARKERS)["owner_grant_gate"],
                         "unknown")

    def test_gateway_does_not_return_private_gateway_source(self):
        markers={key:"present" for key in GATEWAY_MARKERS}
        runner=FakeRunner(gateway=markers)
        self.assertEqual(gateway_markers(runner=runner),markers)
        self.assertEqual(gateway_markers(runner=FakeRunner()),{
            key:"unknown" for key in GATEWAY_MARKERS})
        self.assertEqual(runner.calls[0][:2],["docker","inspect"])
        self.assertEqual(runner.calls[1][:3],["docker","exec","open-webui"])
        self.assertEqual(gateway_probe(runner=runner)[1],"inspected")

    def test_gateway_failure_has_fixed_reason_only(self):
        class NoDocker:
            def __call__(self, argv, **kwargs):
                return types.SimpleNamespace(returncode=1,stdout="",
                                             stderr="PASSWORD=DO_NOT_PRINT")
        markers,reason=gateway_probe(runner=NoDocker())
        self.assertEqual(reason,"docker_inaccessible_or_container_missing")
        self.assertEqual(set(markers.values()),{"unknown"})
        self.assertNotIn("PASSWORD",reason)

        unavailable=FakeRunner(gateway=None)
        markers,reason=gateway_probe(runner=unavailable)
        self.assertEqual(reason,"source_missing_or_unreadable")
        self.assertEqual(set(markers.values()),{"unknown"})

    def test_health_uses_only_localhost_without_bearer(self):
        opener=FakeOpener()
        self.assertEqual(memory_health(opener=opener),"ok")
        self.assertEqual(opener.calls,[("http://127.0.0.1:8766/health",2)])

    def test_unknown_is_not_reported_as_secure(self):
        with tempfile.TemporaryDirectory() as d:
            fake=FakeRunner()
            opener=FakeOpener()
            result=probe(runner=fake,proc_root=Path(d),opener=opener)
            self.assertEqual(result["memory_service_state"],"active")
            self.assertEqual(result["memory_owner_grant_gate"],"unknown")
            self.assertEqual(result["trusted_speaker_turn_issuer"],"not_verified")
            self.assertEqual(result["safe_to_enable_private_auto_recall"],"no")
            self.assertNotIn("SECRET",str(result))

    def test_no_private_data_logged(self):
        fake={"memory_service_state":"unknown",
              "safe_to_enable_private_auto_recall":"no"}
        with mock.patch("kitty_live_readiness_v6.probe",return_value=fake):
            out=io.StringIO()
            with redirect_stdout(out):
                main()
        self.assertIn("KITTY_V6_READ_ONLY_PREFLIGHT",out.getvalue())
        self.assertIn("safe_to_enable_private_auto_recall=no",out.getvalue())
        self.assertNotIn("token=",out.getvalue())


if __name__=="__main__":
    unittest.main()
