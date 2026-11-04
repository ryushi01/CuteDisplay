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

## Ubuntu speaker-safety stage — DEPLOYED SUCCESSFULLY (operator-confirmed)

The new `server/kitty_v6_voice_stage_deploy.py` is a **single transaction**, not a wholesale overwrite. It finds the actual running user memory service source, requires the already-installed owner guard, checks the exact live CPU-speaker branch structure, backs up the speaker module, copies only missing matching opt-in helper modules, restarts **only** `kitty-memory-v6.service` and checks health and both private semantic denial statuses. On failure it attempts a source rollback + service recovery. It refuses unknown source layouts, modified existing helpers or a partially installed prior transaction. It does not change the live Docker gateway, Mac AI/TTS, S3/C5 firmware, SD archive, voice-profile files, owner secrets or feature flags. All new learning functionality stays **off** pending proper trusted-session binding.

**Actual live result from the Ubuntu operator on 2026-11-04 (this supersedes the run instructions below):**

```text
KITTY_V6_VOICE_SAFETY_STAGE
backup=created
candidate_identity_guard=patched
optional_helpers_staged=14
memory_service=healthy
private_403=verified
candidate_only_safety=staged
live_owner_auto_learning=off
open_webui_audio=untouched
esp32_firmware=untouched
```

**No re-run needed.** The transaction successfully backed up and patched the compatible live X-vector identity branch, staged 14 optional modules, restarted the user memory service and verified that private semantic requests without owner proof still get HTTP 403. The rollback transaction remains private on the Ubuntu machine. **Gateway/audio and all ESP32 firmware remain unchanged; no genuine speaker verifier, automatic voice learning, or owner-private automatic recall is activated.**

The previous one-command installer instructions below are retained for disaster recovery documentation only. **Do not repeat the installer on this live host**, where it intentionally rejects an existing installed transaction.

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
5. **S3 performance under one consolidated acceptance session:** check internal heap minimum, loop stack high-water mark, mic/speaker drops, UART ACK timeouts and network reconnection. S3 flash only if an actual firmware fix is justified. C5 v39 is source-ready as a separately requested display-only change, but still awaits a verified build and operator-controlled test; avoid unrelated S3 flashes.
6. **Release gate:** all relevant server tests green, desired source revision recorded, no private files in GitHub, one recoverable Ubuntu deployment and a single meaningful real-hardware acceptance report.

**Current state, after operator-confirmed deployment:** The Ubuntu memory-service owner-grant guard and candidate-only X-vector safety stage are both installed, health-checked and verified. The 14 optional voice modules are staged but NOT activated. The live gateway is still customized and unchanged; progressive voice training, trusted per-turn identity, owner-private live recall, and uninterrupted long-call memory still need end-to-end integration and hardware acceptance. **V6 is not finished end-to-end.** Never elevate a mere speaker candidate to human authentication.

## Display-only C5 v39 release candidate and gateway compatibility gate

C5 version 39 is committed on GitHub: transparent, pure-black two-line conversation captions over the live full-screen Kitty-chan artwork at y=40 and y=56 (no opaque bottom caption panel), plus a transparent status label. The full face renderer, UTF-8 wrapping, 16 moods and lip sync remain unchanged. The active hardware is still C5 v38 until an operator tests v39. CI targeted C5 caption and earlier display-contract checks passed; the full C5/S3 build must separately complete. Prefer C5 USB-only testing when available. If using S3-packaged C5 UART OTA, preserve the Ubuntu/S3 private sync configuration by using a local trusted build rather than flashing public CI binaries without credentials.

Passive memory gateway bridge source and tests: `kitty_passive_turn_bridge_v6.py`, `kitty_gateway_provider_scope_v6.py`. Exact upstream provider event scope in the private live `realtime.py` has not yet been checked, and no live Open WebUI changes were made. The bridge cannot authorize private history from a probable X-vector score and remains gated on an independent trusted per-turn attestation. One read-only gateway check and complete isolated test steps are in [KITTY_V6_C5_V39_AND_GATEWAY_TEST_PLAN_2026-11-04.md](KITTY_V6_C5_V39_AND_GATEWAY_TEST_PLAN_2026-11-04.md).

## Confirmed read-only single-file gateway bind and inode-safe deployment

Live read-only Docker check: `mount_layout=file_bind`, `mount_write_mode=ro`, `target_is_mountpoint=yes`, `target_is_regular_file=yes`, `parent_writable_for_root=yes`, `filesystem_readonly=no`, `known_staging_candidate=no`. This definitively explains why the **old** gateway installer fails at `atomic_replace`. Do not rerun `kitty_gateway_passive_rollout_v6.py --apply` or force Docker file replacement.

Replacement on GitHub: `server/kitty_gateway_bind_rollout_v6.py`. It verifies the exact single-file RO mount and host/container matching SHA-256; tests host source write access without modifying bytes; saves the unmodified gateway in an invoking-user 0700/0600 private host backup; offline patches exactly the unique upstream provider event decode; pre-imports only absent exact-matched helper modules; STOPS the existing `open-webui` container; writes only the host bind SOURCE **in place, preserving device/inode, owner, group, mode**; STARTS that same container; checks health and both host/container checksums. Failures with a verifiable original/candidate SHA restore the original bytes in the same inode and restart. Bounded partial prefix writes are recognized and restored when verifiably from this transaction. Unknown external edits stop for manual recovery rather than risk overwriting user work. No existing Compose configuration, mounted volume, memory service, S3/C5 firmware, SD archive, model/TTS or voice profiles are altered.

The targeted offline test `server/test_kitty_gateway_bind_rollout_v6.py` passed, including root-writer actual local file operations, RO source selection, write-open with no byte change, inode+owner+permissions, private backup creation, full simulated Docker stop/start deployment, failed-health rollback, partial-write recovery, and unrelated external-edit refusal. This CI test does not certify operation on the actual private host source; success is confirmed only by running the guarded installer.

One **new** command, when Kitty is idle (it briefly stops/starts Open WebUI, not the memory service):

```bash
cd ~/kitty-v6/private/kitty-sync-deployment/live-sync-build
git fetch origin main
git show FETCH_HEAD:server/kitty_gateway_bind_rollout_v6.py | python3 - --apply
```

Expected labels: `KITTY_V6_READONLY_BIND_GATEWAY_ROLLOUT`, `backup=verified`, `gateway_hook=installed`, `gateway_health=healthy`, `host_inode=preserved`, `provider_forwarding=unchanged`, `private_recall=disabled`, `automatic_voice_learning=disabled`, `firmware_and_SD=unchanged`. On `rollout_error` or `failed_phase`, **do not rerun**; share the short statuses and rollback result. The script also has `--rollback` for intentional return to the exact saved original when installed and content checks still match.

**This rollout installs passive provider-event observation, not secure owner speaker verification, private historical memory release or hands-free persistent adaptive learning.** Those V6 acceptance gates remain. C5 v39 black captions over Kitty's unobscured face are compiled but physically untested; C5 hardware still runs v38.
