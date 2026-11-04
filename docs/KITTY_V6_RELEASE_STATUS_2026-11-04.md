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


## Operator-verified single-file gateway rollout — November 4 (live Ubuntu)

The Ubuntu operator confirmed the `server/kitty_gateway_bind_rollout_v6.py` transaction on the live host. This is a **successful installed deployment**, not an unfinished transaction. The subsequent `--apply` attempt intentionally refused with `rollout_error=previous_installation_or_unfinished_transaction`; **do not rerun** or clear the manifest. The operator ran a read-only check of `~/.local/state/kitty-v6-gateway-bind/transaction.json` with these results:

```text
status=installed
pinned_ref=8bf4fedb5108
backup_verified=true
candidate_verified=true
container_state=running healthy
live_gateway=candidate
```

These values confirm the running gateway bytes match the saved patched candidate and the container is healthy; they do not alone prove event execution during a call. The original private backup is intact. No rollback is indicated. The hook observes a limited set of upstream provider events while leaving voice forwarding unchanged; no private owner-history release, independent per-turn issuer, biometric learning, or C5 firmware change is enabled.

**Next operator check, read-only:** inspect the installed source for exactly one passive hook marker and call, confirm helper import/instance creation from `/app/backend`, and compare source SHA to the saved `after` digest. Then have one short real Kitty call and confirm ordinary realtime voice, healthy Open WebUI and unchanged private-history denial. Passive observation produces no persistent counters/logs by default; a healthy call alone cannot demonstrate the hook received events. Design opt-in, non-content event-count diagnostics if needed, without logging transcript/audio or enabling owner-grant paths.

**Remain gated:** trusted microphone-to-provider-item provenance, independently verified turn tickets, owner-grant-bound recall, consent-based learning and uninterrupted long-call memory acceptance. Preserve S3 SD memory authority, verified Ubuntu guards, v38 hardware, and private service settings. C5 v39 display release remains a separate physical acceptance task.


## Operator-confirmed live passive hook checksum and initialization

The Ubuntu operator ran the read-only validation against the active Open WebUI container after the installed candidate check. The actual outputs were:

```text
KITTY_V6_LIVE_HOOK_CHECK
gateway_sha=matched
passive_hook=present
helper_initialization=passed
```

This establishes that the mounted live gateway matches the recorded candidate, has exactly one marker and one observer call, compiles, and the passive helper can be constructed with a session ID and closed in the current container environment. The validation did **not** send an actual provider event or establish end-to-end observation, live memory retrieval, independent speaker verification, or long-call persistence.

**Next:** one normal, short realtime Kitty call on the currently running S3 and C5 v38 to verify audio, conversational response, and normal end/return to idle. Optional second turn with an interruption; no memory enrollment or private-history test until an independent speaker issuer is connected. After the call, read-only Open WebUI health check; report voice/call behavior. Do not reinstall gateway or reflash either board. If successful, plan an opt-in privacy-safe provider event observation diagnostic and separately integrate the trusted server-issued speaker attestation before authorizing any owner memory.


## After-call outcome: live audio healthy; historical recall still pending

The Ubuntu operator confirmed the passive gateway source matched its transaction candidate, the hook marker and call were present once, and helper initialization passed. After a normal Kitty conversation, Open WebUI reported `running healthy` and `kitty-memory-v6.service` was `active`. The operator reported that the call itself works normally but Kitty does not appear to recall conversations from earlier days. This is **expected while private cross-call owner history remains gated**, but it does not establish whether S3 still contains specific memories. The passive provider observer does not perform semantic retrieval, context injection, trusted voice attestation or automatic voice learning.

**Read-only next step:** `server/kitty_v6_memory_readiness_probe.py` inspects the running user service's selected configuration, the newest finalized S3-derived snapshot's five memory-file presence states, and metadata-only row counts of the derived semantic SQLite cache. It does not print secrets, paths, memory texts, voice IDs or transcripts; does not call the memory API, restart services or write files. Its SQLite inspection uses an immutable read-only view (counts may lag an active WAL writer). Operator command:

```bash
cd ~/kitty-v6/private/kitty-sync-deployment/live-sync-build
git fetch origin main
git show FETCH_HEAD:server/kitty_v6_memory_readiness_probe.py | python3 -
```

Inspect `snapshot`, `summaries`, `conversations`, `index`, `indexed_rows`, `attributed_rows`, and `auto_refresh_enabled` before changing any code. If environment is unreadable, do **not** copy or print memory-service environment variables or tokens; use a separate minimal diagnostic. Six local contract tests passed including absence of private data in output, symlink refusal and non-writing SQLite access. These checks diagnose archive and indexing readiness, not end-to-end speaker-bound recall.

**Release constraint remains unchanged:** Keep the S3 microSD as authority, preserve private histories and voice profiles, do not disable the owner-grant 403 rule, and do not reinstall or flash firmware as part of this diagnostic.


## Read-only archive/index diagnostic: 66-hour-old snapshot

The operator executed the GitHub `kitty_v6_memory_readiness_probe.py` on Ubuntu. The outputs: `service_environment=readable`, `snapshot_configured=true`, `semantic_index_configured=true`, `auto_refresh_enabled=true`, `snapshot=present`, `snapshot_age_hours=66`, `facts=empty`, `dated_plans=empty`, `summaries=empty`, `conversations=nonempty`, `shareable_memories_v6=nonempty`, `index=active`, `indexed_rows=259`, `attributed_rows=259`, `changes=none`.

**Interpretation:** Open WebUI and `kitty-memory-v6.service` remain healthy. The latest *finalized Ubuntu snapshot* is 66 hours old, which is not proof the live S3 card is stale. The CPU-derived index contains 259 rows, but `attributed_rows` means attribution metadata exists, NOT trusted/verified owner identity. Enabled auto-refresh is not evidence that newer S3 snapshots are arriving.

**Critical privacy-specific nuance:** In `firmware/CuteDisplayBrain/KittyMemory.h`, successful unverified summaries append to `/kitty/unverified_summaries_v6.tsv`, not `/kitty/summaries.tsv`; the former is intentionally NOT among `KittyMemory::EXPORT_NAMES`' nine authorized upload files. The prior hardware result `accepted=1` / `ack_offset=2878` is consistent with a successfully stored *unverified* local SD summary. Empty exported summaries/facts/plans therefore must NOT be interpreted as automatic-SSE summarization failure, and these unverified rows must not be copied into owner-private memory to make recall pass.

The S3 sync worker in `firmware/CuteDisplayBrain/KittyMemorySyncV6.h` retries failed exports after roughly 15 seconds and, once a previous export succeeds, attempts a periodic refresh after roughly 60 seconds when eligible. It pauses network chunks during speaking/AI playback, exports through the SD worker, and leaves private source files untouched on failure. A 66-hour-old latest finalized snapshot merits checking the *device's* existing status counters before any code change.

**Next zero-change S3 USB serial commands:** `memory sync status` followed by `memory summary status`. Do not run `memory ai on`, `memory format`, OTA, firmware flash, restart, or manual sync upload. Relevant labels: configured, running, completed, failures, sd_ready, wifi, eligible, stage, file, http, bytes, job_ack_offset, awaiting, ai_pending, ai_http_paused, ai_enabled. `stage` 1=export, 2=chunk, 3=finalize, 4=concurrent-change. Status lines contain no memory text or secrets. On Ubuntu, optionally verify `systemctl --user is-active kitty-sync-gateway-v6.service` without dumping environment. If device reports `configured=0`, inspect whether the running firmware was built with the private header without disclosing credentials; do not reflash unless necessary.

**Separate unfinished features:** trusted speaker-to-provider-item attestation, owner-grant-bound private recall, and real same-call rolling context remain disabled. Continue preserving S3 SD authority, private archive, C5 v38 baseline and normal realtime audio.
