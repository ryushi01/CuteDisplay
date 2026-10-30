# Kitty V6 — iPhone owner proof implementation checkpoint (2026-10-30)

**Source-only, not deployed. NOT YET an end-to-end owner authorization feature.**

## Implemented
- `ios/CuteDisplay/KittyOwnerProofV6.swift`: opt-in Secure Enclave P-256 signing key protected by device user presence; public-key enrollment export; HTTPS challenge and verification helper. The Swift file must be added to the user's actual Xcode target manually because the repo does not carry the full signed project.
- `server/kitty_owner_proof_v6.py`: Ubuntu verifies an enrolled public key, single-use random challenge, per-session signature and expiration. Uses the optional `cryptography` Python library.
- `server/kitty_memory_service.py`: disabled-by-default `POST /owner/challenge` and `POST /owner/verify` routes, enabled only by `KITTY_OWNER_PUBLIC_KEY_PEM` plus `KITTY_OWNER_GRANT_SECRET_HEX`. They inherit the existing bearer authentication requirement. Never expose port 8766 directly to the internet; use a dedicated authenticated HTTPS gateway if exposing to iPhone.
- `server/kitty_owner_session_v6.py`: HMAC grant bound to a realtime session, valid for at most 120s in this flow.
- `server/test_kitty_owner_proof_v6.py`: session binding, expiry, replay and invalid-signature tests. CI now installs cryptography for offline tests.

## Security and deployment blockers
- The app's BLE pairing is encrypted but uses Just Works and is not authenticated human identity. Speaking “I'm Shana” must never grant authorization.
- A Secure Enclave key proves possession of an **enrolled device key after user presence**, not absolute biometric identity. The owner must inspect/approve enrollment out-of-band and revoke/rotate on loss.
- Current iOS source is an explicit helper, **not yet connected to the app's UI/BluetoothManager**. The app must receive a genuine gateway-created session ID, a separate authorization credential, and a trusted HTTPS URL. No such flow is wired.
- **S3 does not verify these grants yet.** Its V6 firmware `ownerVerified` flag defaults false; this intentionally prevents protected owner fact learning. DO NOT FLASH this branch before secure per-turn authorization is wired and tested.
- Avoid sending HMAC signing secret to iPhone or S3. Instead the trusted Ubuntu verifier should return a narrowly scoped per-turn claim over a mutually authenticated channel, or S3 should use an asymmetric server-signature scheme with a pinned public key and replay protection. Existing HMAC grants must not be marked trusted solely because they arrive over BLE.
- The S3 device key is not a personal login credential. For deployment, use separate owner-proof and device API access policies; add rate limiting and request logging without storing raw transcripts or secrets.
- A turn attributed to ChatGPT or a guest remains unverified unless independently authenticated. Never overwrite protected owner memories from that turn.

## Validation before deployment
1. Admin enrolls owner public key through a trusted out-of-band workflow.
2. On a real iPhone, explicit user-presence prompt signs a nonce.
3. Incorrect signature, expired nonce, wrong session and replay are rejected.
4. Valid grant reaches the *trusted gateway* and is enforced for **one specific turn**; expiry, disconnect, and speaker change revoke authorization.
5. Only then does S3 mark that specific enqueued `Entry` as verified; guest and unknown statements may be archived without owner-profile changes.
6. Demonstrate normal learning for owner and isolation for guest in Japanese/English/French, with no extra mic/TTS latency.
7. Run actual CI, Xcode build and hardware firmware tests. Do not merge to stable `main` before acceptance.
