# Kitty V6: private owner proof enrollment (source only)

## Verified starting state (Nov 5, 2026)

A read-only Ubuntu check confirmed:

- `kitty-memory-v6.service=active`
- `KITTY_OWNER_PUBLIC_KEY_PEM` is not configured
- `KITTY_OWNER_GRANT_SECRET_HEX` is not configured
- No trusted speaker-attestation issuer is installed
- The SD-derived semantic index had 373 records, **0 verified owner records**

Ordinary voice calls and approved shared cross-call recall work. Owner-private
cross-call voice recall is **not available**. Do not bypass this by treating
voice-probable matches, "I am the owner" or phone BLE pairing as proof.

## One-time *owner identity* enrollment

This change adds a button under CuteDisplay iPhone app **Settings**:

**Copy Owner Public Key** — requires a rebuilt and installed iPhone app with
the Secure Enclave helper available. The action uses the hardware Secure
Enclave P-256 signing key and copies its **public DER key, Base64 encoded**
to the clipboard. No private key, SD contents or API credentials are copied.
The public key must be enrolled locally by the administrator.

The local Ubuntu helper is `server/kitty_owner_enroll_setup_v6.py`.
It is **not** a remote API or an auto-enroll listener.

Run once on Ubuntu, after the updated iPhone app is installed and its
public key has been copied. No firmware flash is needed:

```bash
(
  set -euo pipefail
  cd "$HOME/kitty-v6/private/kitty-sync-deployment/live-sync-build"
  git fetch -q origin main
  git show FETCH_HEAD:server/kitty_owner_enroll_setup_v6.py | python3 - --check
)
```

When `owner_enrollment_preflight=ready` and Kitty is idle:

```bash
(
  set -euo pipefail
  cd "$HOME/kitty-v6/private/kitty-sync-deployment/live-sync-build"
  git fetch -q origin main
  git show FETCH_HEAD:server/kitty_owner_enroll_setup_v6.py | python3 - --install
)
```

The hidden input prompt accepts ONLY the copied iPhone **public** key;
do not type the iPhone password, private key or any existing API token.
The script validates a genuine DER P-256 public key, writes a new 0600 PEM
file under the already-private Kitty service directory, generates a 32-byte
random HMAC grant key locally, appends only the two owner verification
variables to the **existing** private `memory-service.env`, and restarts
`kitty-memory-v6.service`. It refuses existing owner configuration rather
than rotating keys. A private 0600 backup is retained. If the service
cannot restart or become active, the original environment is restored.

The output never contains the public key, server grant secret, bearer token,
memory contents, or transcript. Never run this as root / sudo.

## Limits / next step

**This is enrollment only.** The registered key lets an explicitly
authenticated owner obtain a short-lived, session-bound grant using the
already existing `/owner/challenge` and `/owner/verify` service endpoints.
The phone helper is not wired into automatic realtime call setup yet,
and the memory service has no independent, trusted turn-level speaker
issuer. A valid owner grant alone must NOT release private voice memories.

A later gateway update must require BOTH a short-lived owner grant AND an
independently signed, matching upstream provider item/transcript attestation,
use the already present `AttestedLiveCall`, preserve cancellation/guest
boundaries, and use a read-only S3-derived memory index. It must also support
explicitly verified provenance: the current indexed historical records have
no verified-owner rows and must not be silently promoted.

Minimal future validation: one authenticated owner turn and one
unknown/guest turn, both with the same secret in the underlying S3 store;
only the owner can retrieve private information. Never print a secret to
prove the feature works.

No SD, C5/S3 firmware, Open WebUI gateway, default voice model or audio
hot path is changed by the enrollment source files.
