#!/usr/bin/env python3
"""No-leak, read-only compatibility checks for deployed on-disk memory code."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from kitty_owner_sd_runtime_preflight_v6 import analyze, main, TARGETS

HERE=Path(__file__).resolve().parent


class OwnerSdRuntimeReadinessTests(unittest.TestCase):
    def test_git_repo_source_is_structurally_ready_but_never_deployment_ready(self):
        report=analyze(HERE)
        self.assertEqual(report["deployed_source_files"],"present")
        self.assertEqual(report["deployed_python_syntax"],"valid")
        for name in (
                "snapshot_owner_tenth_file", "memory_snapshot_endpoint",
                "signed_owner_receipt_verifier",
                "semantic_owner_attribution", "semantic_index_receipt_binding"):
            self.assertIn(report[name],("supported_on_disk","present_on_disk"),name)
        self.assertEqual(report["running_process_module_revision"],"not_verified")
        self.assertEqual(report["owner_receipt_signing_keys"],"not_checked")
        self.assertEqual(report["owner_sd_receipt_written"],"not_verified")
        self.assertEqual(report["deployment_ready"],"no")
        self.assertEqual(report["live_owner_private_recall"],"no")

    def _copy(self, directory):
        for name in TARGETS:
            shutil.copyfile(HERE/name,Path(directory)/name)

    def test_missing_or_broken_deployed_modules_are_not_promoted(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(analyze(t)["deployed_source_files"],"incomplete")
            self._copy(t)
            owner=Path(t)/"kitty_owner_sd_receipts_v6.py"
            text=owner.read_text()
            owner.write_text(text.replace(
                "hmac.compare_digest(signature, _mac",
                "hmac.rejected_digest(signature, _mac",1))
            report=analyze(t)
            self.assertEqual(report["signed_owner_receipt_verifier"],"not_verified")
            owner.write_text("invalid syntax !")
            report=analyze(t)
            self.assertEqual(report["deployed_python_syntax"],"not_verified")
            self.assertEqual(report["deployment_ready"],"no")

    def test_old_nine_file_snapshot_receiver_does_not_claim_tenth_support(self):
        with tempfile.TemporaryDirectory() as t:
            self._copy(t)
            file=Path(t)/"kitty_sd_snapshot_v6.py"
            original=file.read_text()
            # Remove only the tenth entry; retain valid source to simulate
            # the old deployed snapshot receiver.
            patched=original.replace(
                ', "owner_turn_receipts_v6.tsv"}', '}',1)
            self.assertNotEqual(original,patched)
            file.write_text(patched)
            report=analyze(t)
            self.assertEqual(report["deployed_python_syntax"],"valid")
            self.assertEqual(report["snapshot_owner_tenth_file"],"not_verified")
            self.assertEqual(report["deployment_ready"],"no")

    def test_diagnostic_prints_only_closed_labels(self):
        with tempfile.TemporaryDirectory() as t:
            self._copy(t)
            secret="DO_NOT_EXPOSE_USER_PRIVATE_GATEWAY_KEY_001"
            with (Path(t)/"kitty_memory_service.py").open("a") as file:
                file.write("\n# "+secret+"\n")
            output=io.StringIO()
            with patch("kitty_owner_sd_runtime_preflight_v6.service_status",
                       return_value="active"):
                with redirect_stdout(output):
                    main(["--server-dir",t])
            rendered=output.getvalue()
            self.assertIn("KITTY_V6_OWNER_SD_RUNTIME_READ_ONLY",rendered)
            self.assertIn("kitty_memory_user_service=active",rendered)
            self.assertIn("deployment_ready=no",rendered)
            self.assertNotIn(secret,rendered)
            self.assertNotIn(t,rendered)
            self.assertNotIn("async def",rendered)
            self.assertNotIn("source code",rendered)


if __name__=="__main__":
    unittest.main()
