# Kitty V6 owner identity security gate — 2026-10-30

Status: **source-only feature branch; not deployed or hardware-tested**.

## Current safety behavior
- The S3 SD worker continues to archive each conversational exchange in legacy `conversations.tsv` and writes an `unknown` source annotation.
- New `Entry.ownerVerified` defaults to **false**; unverified turns skip owner-specific fact extraction, preference merging, correction writes, and summary/consolidation enqueue.
- This means deploying this code **before** connecting a trusted verified-owner event would intentionally stop owner fact learning. Do not flash it as-is. The historical owner facts on microSD are not erased.
- The current path cannot identify a human from a voice. Merely using the S3 microphone, saying “I am Shana,” or authenticating the physical device is insufficient.
- `server/kitty_owner_session_v6.py` creates/verifies short-lived signed grants *only if* a caller supplies already independently verified owner status. Grant is bound to a session and expires; it does not authenticate a login by itself.
- Neither the iOS app nor the S3 has yet been connected to that grant verifier. The S3 has no trusted grant-validation input at present. Treat all such turns as unknown.
- The V6 sidecar remains intentionally `unknown` (even if future code sets `ownerVerified`) until signed attribution is explicitly wired to archive records.

## Next wiring, required before deployment
1. Authenticate owner through the existing iPhone app with an independent owner login/passkey or equivalent verifiable account credential. iPhone pairing alone does not prove which human is speaking.
2. A trusted endpoint validates the user's authenticated session and issues a short-lived HMAC grant; never accept `authenticated_owner=true` straight from a phone JSON request.
3. Bind grant to a realtime call session, pass it only over TLS, validate freshness, issuer and session ID at the trusted boundary. Propagate only a verified, bounded attribution flag to the S3 SD worker, not raw guest self-claims.
4. Scope the flag to each turn, prevent replay, expire on disconnect/timeout, and preserve non-owner notes as claims. Do not allow a guest to modify the owner's profile.
5. Revise the archive sidecar to store verified provenance only after the trusted verification completes, and ensure old unknown archive rows remain unchanged.
6. Compile, test with actual iOS/S3/realtime protocol and verify both owner learning and guest isolation before promoting main.

## Acceptance cases
- Unknown microphone speaker: archived, no owner profile mutation.
- Guest says “I am Shana” in English/Japanese/French: remains an unverified claim.
- ChatGPT introduces itself: not the owner, may be described as a remote AI claim.
- Authenticated owner with valid session grant: can update owner facts **only once the verification is wired into a live per-turn path**.
- An expired or wrong-session grant: not authorized.
- A guest discussing Shana's hobbies: does not overwrite Shana's preferences.
- SD retention and realtime audio: no SD I/O on audio loop, no additional network RTT on mic/speaker tasks.

Do not claim this branch has completed real-world speaker identification; it implements a safe boundary and the cryptographic grant primitive, not voice biometrics or production authorization.
