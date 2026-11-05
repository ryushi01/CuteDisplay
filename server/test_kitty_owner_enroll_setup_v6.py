#!/usr/bin/env python3
"""Offline tests for the one-time owner PUBLIC key enrollment; no real service."""
import base64
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
import kitty_owner_enroll_setup_v6 as setup


class EnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = self.root / "memory-service.env"
        self.pub = self.root / "kitty-owner-public-v6.pem"
        self.backup = self.root / "memory-service.env.pre-owner-enroll-v6.bak"
        self.env.write_text("KITTY_MEMORY_TOKEN=existing-test-placeholder\n")
        self.env.chmod(0o600)
        private = ec.generate_private_key(ec.SECP256R1())
        der = private.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)
        self.encoded = base64.b64encode(der).decode()
        self.pem = setup.validate_der(self.encoded)

    def run_install(self, restart=None):
        if restart is None:
            restart = lambda *args: "active"
        with patch.object(setup.os, "geteuid", return_value=1001), \
             patch.object(setup, "command", return_value="active"), \
             patch.object(setup, "running_service_has_enrollment", return_value=True):
            return setup.install(
                self.pem, env=self.env, public_file=self.pub,
                backup=self.backup, restart=restart)

    def test_accept_only_p256_public_der(self):
        self.assertIn(b"BEGIN PUBLIC KEY", self.pem)
        for malformed in ("bad", "", "Not a key " * 20, self.encoded + "!"):
            with self.assertRaises(setup.EnrollmentRefusal):
                setup.validate_der(malformed)
        private = ec.generate_private_key(ec.SECP384R1())
        der = private.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)
        with self.assertRaises(setup.EnrollmentRefusal):
            setup.validate_der(base64.b64encode(der).decode())

    def test_local_install_preserves_all_existing_env(self):
        before = self.env.read_bytes()
        self.assertEqual(self.run_install(), "installed")
        result = self.env.read_text()
        self.assertTrue(result.startswith(before.decode()))
        self.assertEqual(result.count("KITTY_OWNER_GRANT_SECRET_HEX="), 1)
        self.assertIn(str(self.pub), result)
        self.assertEqual(self.pub.read_bytes(), self.pem)
        self.assertEqual(self.backup.read_bytes(), before)
        self.assertEqual(self.pub.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.backup.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.env.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(setup.EnrollmentRefusal):
            self.run_install()  # no silent key rotation

    def test_failed_service_health_restores_original(self):
        original = self.env.read_bytes()
        attempts = []
        def restart(*argv):
            attempts.append(argv)
            if argv == ("is-active", setup.SERVICE):
                return "inactive"
            return "active"
        with self.assertRaises(setup.EnrollmentRefusal):
            self.run_install(restart=restart)
        self.assertEqual(self.env.read_bytes(), original)
        self.assertFalse(self.pub.exists())
        self.assertEqual(self.backup.read_bytes(), original)
        self.assertEqual(attempts.count(("restart", setup.SERVICE)), 2)

    def test_live_service_env_not_loaded_rolls_back(self):
        original = self.env.read_bytes()
        with patch.object(setup.os, "geteuid", return_value=1001), \
             patch.object(setup, "command", return_value="active"), \
             patch.object(setup, "running_service_has_enrollment", return_value=False):
            with self.assertRaisesRegex(
                setup.EnrollmentRefusal, "owner_env_not_loaded_by_service"
            ):
                setup.install(
                    self.pem, env=self.env, public_file=self.pub, backup=self.backup,
                    restart=lambda *args: "active"
                )
        self.assertEqual(self.env.read_bytes(), original)
        self.assertFalse(self.pub.exists())
        self.assertTrue(self.backup.is_file())

    def test_bearer_config_never_printed_or_overwritten(self):
        self.env.write_text(
            "KITTY_MEMORY_TOKEN=keep-secret\nKITTY_OWNER_GRANT_SECRET_HEX=\n")
        self.env.chmod(0o600)
        with self.assertRaisesRegex(setup.EnrollmentRefusal, "already_configured"):
            self.run_install()
        self.assertFalse(self.pub.exists())
        self.assertFalse(self.backup.exists())

    def test_permissions_fail_closed(self):
        self.env.chmod(0o644)
        with self.assertRaises(setup.EnrollmentRefusal):
            self.run_install()
        self.assertFalse(self.pub.exists())

    def test_iphone_ui_exports_public_der_only(self):
        ui = (Path(__file__).resolve().parents[1] /
              "ios/CuteDisplay/ContentView.swift").read_text()
        key = (Path(__file__).resolve().parents[1] /
               "ios/CuteDisplay/KittyOwnerProofV6.swift").read_text()
        self.assertIn("ownerEnrollmentSection", ui)
        self.assertIn("enrollmentPublicKeyDER()", ui)
        self.assertIn("UIPasteboard.general.string", ui)
        self.assertIn("publicKey.derRepresentation", key)
        self.assertNotIn("privateKey().dataRepresentation", ui)


if __name__ == "__main__":
    unittest.main()
