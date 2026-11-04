# Kitty V6 — Release status / next operator action
**Date:** 2026-11-04  
**Source checkpoint:** `main` after the gradual voice-learning and source-only ownership work.

## Verified working hardware / live Ubuntu (preserve)

- S3 Freenove brain realtime microphone/speaker/Wi-Fi/SD and C5 v38 BLE/display are the accepted hardware baseline. No flash in this iteration.
- Existing Open WebUI gateway on Ubuntu VM still carries working realtime conversation, public memory refresh and speaker observer. Model+TTS continue on Mac until the separately planned MS-A1 migration.
- The owner-guard security installer previously returned: `backup=created`, `offline_private_guard=passed`, `deployment=completed`, `memory_health=ok`, `private_semantic_403=verified`, `shared_audio_gateway=unchanged`. **Do not rerun it.**
- S3 SD remains the durable memory authority. Earlier hardware tests confirmed at least one accepted automatic SSE summary/ACK; continuous in-call memory across long provider sessions is *not yet confirmed live*.

## Source implemented and offline-tested (not yet live)

- Bound, extractive long-call decision history with exact item/session checks and no extra realtime model inference. Tested over 120 simulated turns, not a full model-generated summary.
- Signed turn attestations and owner-grant-protected history adapter, default-deny without independent speaker issuer.
- ECAPA and X-vector derived candidate cohorts with immutable enrollment anchors, six samples maximum, 24h spacing and 90-day expiry. Training requires reviewed audio bound to a trusted gateway item, explicit biometric-learning consent, separately verified owner grant, and a **learning-only** crypto audience, not an ordinary voice match.
- Optional per-call candidate familiarity hint that grows with repeated consistent matches, without elevating voice similarity to an authenticated owner. Guest/interruption/cancel resets.
- The older `KittySpeakerObserver.authorized_recall` now fails closed in GitHub source; currently deployed private gateway still uses its own customized source. The legacy X-vector experimental-identity branch is now candidate-only in GitHub source.
- Source-only voice-review Secure Enclave helper, server approval issuer, post-call learner and profile compare-and-swap store. No iPhone UI or real per-turn issuer yet.

## One guarded Ubuntu speaker-safety stage (operator action)

The new `server/kitty_v6_voice_stage_deploy.py` is a **single transaction**, not a wholesale overwrite. It finds the actual running user memory service source, requires the already-installed owner guard, checks the exact live CPU-speaker branch structure, backs up the speaker module, copies only missing matching opt-in helper modules, restarts **only** `kitty-memory-v6.service` and checks health and both private semantic denial statuses. On failure it attempts a source rollback + service recovery. It refuses unknown source layouts, modified existing helpers or a partially installed prior transaction. It does not change the live Docker gateway, Mac AI/TTS, S3/C5 firmware, SD archive, voice-profile files, owner secrets or feature flags. All new learning functionality stays **off** pending proper trusted-session binding.

When Kitty is idle:

```bash
cd ~/kitty-v6/private/kitty-sync-deployment/live-sync-build
git fetch origin main
git show FETCH_HEAD:server/kitty_v6_voice_stage_deploy.py | python3 - --apply
```

Safe success markers:

```text
KITTY_V6_VOICE_SAFETY_STAGE
backup=created
candidate_identity_guard=patched   # or already_safe
optional_helpers_staged=14
memory_service=healthy
private_403=verified
candidate_only_safety=staged
live_owner_auto_learning=off
open_webui_audio=untouched
esp32_firmware=untouched
```

If it returns `stage_error=...`, STOP and share only that fixed label. Do not retry or manually overwrite source. If the transaction completed but a later rollback is deliberately needed, in the same checkout:

```bash
git show FETCH_HEAD:server/kitty_v6_voice_stage_deploy.py | python3 - --rollback
```

Roll back only if required; preserve backup contents privately. The scripts and tests remain versioned on `main`. Synthetic code and unit tests do not establish live biometric authentication.

## Remaining must-pass tests before claiming V6 complete

1. **Independent owner proof is actually enrolled and wired:** live iPhone app target must include the owner key helper and a reviewed voice-learning UI, gateway must produce a trusted unique call+item identity and hold exact S3 microphone bytes. Avoid granting owner status from self-introduction, BLE pairing, probable X-vector score or an S3 bearer.
2. **Multiperson and playback isolation:** test owner voice, one guest voice, ChatGPT TTS, overlap, cancellation and wrong/late signed attestations. Evaluate false-positive and false-negative behavior on actual recordings; calibration against one guest is insufficient.
3. **One uninterrupted long call:** confirm earlier decisions are accessible later while the session is still active, and that late-context response cannot cross a speaker change.
4. **Cross-call owner memory:** a securely verified owner's fact is persisted on S3 and recalled on a later call only to verified owner turns. The deployed service's owner-grant 403 remains enforced.
5. **S3 performance under one consolidated acceptance session:** check internal heap minimum, loop stack high-water mark, mic/speaker drops, UART ACK timeouts and network reconnection. S3 flash only if an actual firmware fix is justified. C5 v38 never OTA for unrelated server work.
6. **Release gate:** all relevant server tests green, desired source revision recorded, no private files in GitHub, one recoverable Ubuntu deployment and a single meaningful real-hardware acceptance report.

**Current state:** Server owner-grant guard is installed and working; source-only adaptive learning and trust plumbing are tested. **V6 is not yet finished end-to-end.** Do not automatically enable owner-private recall or hands-free voice learning just to meet a schedule.
