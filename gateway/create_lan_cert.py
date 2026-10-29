#!/usr/bin/env python3
"""Create a self-signed, hostname-scoped LAN WSS trust anchor for a prototype.

The *public* cert is copied to iPhone -> S3 as the trusted CA. NEVER copy the
private key to the phone, S3, GitHub or a chat. Use DNS hostname reachable
from S3. Requires 'pip install cryptography'.
"""
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import re

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
except ImportError:
    raise SystemExit("Install certificate helper: python -m pip install cryptography")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--hostname", required=True, help="DNS name the S3 can resolve on the same Wi-Fi")
    p.add_argument("--directory", default="~/.config/cutedisplay-gateway")
    args = p.parse_args()
    host = args.hostname.lower().strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,249}[a-z0-9]", host):
        p.error("Use a DNS name, not an IP address or URL; no wildcards")
    folder = Path(args.directory).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    key_path = folder / "gateway-server.key"
    cert_path = folder / "gateway-server.crt"
    if key_path.exists() or cert_path.exists():
        p.error("Certificate/key already exist; refusing to overwrite. Preserve existing paired S3 CA.")
    now = datetime.now(timezone.utc)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=730))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=False, key_encipherment=True,
            data_encipherment=False, key_agreement=False,
            key_cert_sign=True, crl_sign=False, encipher_only=False, decipher_only=False,
        ), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(private_key, hashes.SHA256())
    )
    key_bytes = private_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    cert_bytes = cert.public_bytes(serialization.Encoding.PEM)
    fd = os.open(str(key_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key_bytes)
    fd = os.open(str(cert_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "wb") as f:
        f.write(cert_bytes)
    print("Public CA/certificate (copy ONLY this file into the iPhone app):", cert_path)
    print("PRIVATE server key (gateway Mac only, never copy to iPhone):", key_path)
    print("Certificate expires (UTC):", cert.not_valid_after_utc.isoformat())
    print("Both files are generated. The S3 must resolve the exact configured hostname:", host)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
