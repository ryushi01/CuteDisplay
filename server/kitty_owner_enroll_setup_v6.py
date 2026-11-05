#!/usr/bin/env python3
"""One-time local, fail-closed owner PUBLIC-key enrollment on Ubuntu.

Does NOT issue private-recall access or trust a voice. A Secure Enclave
public key is copied from the Kitty iPhone Settings screen and pasted locally
at a hidden terminal prompt; private signing key remains on the phone.
The Ubuntu grant MAC secret is created locally and NEVER printed.

Only changes the existing private memory-service environment and a public
key file. On failed restart the original environment is restored. No device,
gateway, SD, profiles, archive, Compose or C5/S3 firmware changes.
"""
import argparse
import base64
import getpass
import os
from pathlib import Path
import secrets
import stat
import subprocess
import tempfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

SERVICE = "kitty-memory-v6.service"
ENV = Path.home() / "kitty-v6/private/memory-service.env"
OWNER_PEM = ENV.parent / "kitty-owner-public-v6.pem"
BACKUP = ENV.with_name(ENV.name + ".pre-owner-enroll-v6.bak")
KEYS = ("KITTY_OWNER_PUBLIC_KEY_PEM", "KITTY_OWNER_GRANT_SECRET_HEX")


class EnrollmentRefusal(RuntimeError):
    pass


def command(*args):
    try:
        result = subprocess.run(
            ["systemctl", "--user", *args],
            capture_output=True, timeout=35, check=False
        )
    except (OSError, subprocess.SubprocessError):
        raise EnrollmentRefusal("systemctl_failed") from None
    if result.returncode != 0:
        raise EnrollmentRefusal("systemctl_failed")
    return result.stdout.decode("utf-8", "replace").strip()


def protected_file(path):
    if path.is_symlink() or not path.is_file():
        raise EnrollmentRefusal("private_env_invalid")
    st = path.stat()
    if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1
            or st.st_uid != os.getuid() or (st.st_mode & 0o077)):
        raise EnrollmentRefusal("private_env_permissions")
    return st


def parse_configuration(raw):
    # Require no prior owner variables, including even blank keys. Never
    # overwrite a legitimate manual enrollment or a conflicting config.
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeError:
        raise EnrollmentRefusal("private_env_invalid") from None
    if not lines or len(raw) > 131072:
        raise EnrollmentRefusal("private_env_invalid")
    for line in lines:
        head = line.strip().split("=", 1)[0].strip()
        if head in KEYS:
            raise EnrollmentRefusal("owner_enrollment_already_configured")
    return raw


def validate_der(encoded):
    if not isinstance(encoded, str) or not 100 <= len(encoded) <= 1200:
        raise EnrollmentRefusal("public_key_invalid")
    try:
        der = base64.b64decode(encoded, validate=True)
        key = serialization.load_der_public_key(der)
    except (ValueError, TypeError):
        raise EnrollmentRefusal("public_key_invalid") from None
    if (not isinstance(key, ec.EllipticCurvePublicKey)
            or not isinstance(key.curve, ec.SECP256R1)):
        raise EnrollmentRefusal("public_key_must_be_secure_enclave_p256")
    return key.public_bytes(serialization.Encoding.PEM,
                            serialization.PublicFormat.SubjectPublicKeyInfo)


def atomic_restore(path, content, mode):
    fd, temp = tempfile.mkstemp(prefix=".kitty-owner-restore-", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def install(pem, *, env=ENV, public_file=OWNER_PEM, backup=BACKUP,
            restart=command):
    # This script runs as the owning Linux user, never sudo/root.
    if os.geteuid() == 0:
        raise EnrollmentRefusal("do_not_run_as_root")
    st = protected_file(env)
    original = env.read_bytes()
    parse_configuration(original)
    if public_file.exists() or public_file.is_symlink():
        raise EnrollmentRefusal("owner_key_file_already_exists")
    if backup.exists() or backup.is_symlink():
        raise EnrollmentRefusal("enrollment_backup_already_exists")
    if public_file.parent != env.parent or backup.parent != env.parent:
        raise EnrollmentRefusal("owner_paths_unexpected")
    if command("is-active", SERVICE) != "active":
        raise EnrollmentRefusal("memory_service_not_active")

    # Back up exact pre-existing env with O_EXCL so it can never be silently
    # clobbered, even on a second enrollment attempt.
    mode = stat.S_IMODE(st.st_mode)
    backup_created = False
    key_created = False
    env_updated = False
    try:
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        backup_created = True
        with os.fdopen(fd, "wb") as handle:
            handle.write(original)
            handle.flush()
            os.fsync(handle.fileno())
        fd = os.open(public_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        key_created = True
        with os.fdopen(fd, "wb") as handle:
            handle.write(pem)
            handle.flush()
            os.fsync(handle.fileno())
        # No separate database. The only new local secret is a random HMAC
        # key referenced by the existing private service config.
        mac_secret = secrets.token_hex(32)
        suffix = (f"\nKITTY_OWNER_PUBLIC_KEY_PEM={public_file}\n"
                  f"KITTY_OWNER_GRANT_SECRET_HEX={mac_secret}\n").encode()
        if not original.endswith(b"\n"):
            suffix = b"\n" + suffix
        # Atomic replacement instead of truncating the env while it is live.
        if env.read_bytes() != original:
            raise EnrollmentRefusal("env_changed_during_enrollment")
        atomic_restore(env, original + suffix, mode)
        env_updated = True
        restart("restart", SERVICE)
        if restart("is-active", SERVICE) != "active":
            raise EnrollmentRefusal("service_unhealthy")
        # Do not print key, grant or private configuration.
        return "installed"
    except Exception:
        if env_updated and env.read_bytes() == original + suffix:
            atomic_restore(env, original, mode)
            try:
                restart("restart", SERVICE)
            except EnrollmentRefusal:
                pass
        if key_created and public_file.is_file() and not public_file.is_symlink():
            if public_file.read_bytes() == pem:
                public_file.unlink()
        if backup_created:
            # Retain an exact private backup for manual recovery if needed.
            pass
        raise


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--install", action="store_true")
    args = parser.parse_args()
    try:
        if args.check:
            protected_file(ENV)
            parse_configuration(ENV.read_bytes())
            if OWNER_PEM.exists() or OWNER_PEM.is_symlink() or BACKUP.exists():
                raise EnrollmentRefusal("owner_enrollment_files_already_exist")
            if command("is-active", SERVICE) != "active":
                raise EnrollmentRefusal("memory_service_not_active")
            print("owner_enrollment_preflight=ready")
            print("changes=none")
        else:
            # git show ... | python3 - --install leaves stdin occupied by
            # script source, so read the PUBLIC key from the controlling TTY.
            encoded = getpass.getpass(
                "Paste iPhone PUBLIC key (Base64, input hidden): ")
            pem = validate_der(encoded)
            install(pem)
            print("owner_public_key=enrolled")
            print("owner_grant_secret=generated_locally")
            print("memory_service=active")
            print("trusted_spoken_turn_issuer=not_installed")
            print("private_voice_recall=still_disabled")
            print("firmware_sd_gateway=unchanged")
    except EnrollmentRefusal as exc:
        print("owner_enrollment=refused")
        print("reason=" + str(exc))
        raise SystemExit(1) from None
    except (OSError, ValueError, EOFError, KeyboardInterrupt):
        print("owner_enrollment=cancelled_or_unavailable")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
