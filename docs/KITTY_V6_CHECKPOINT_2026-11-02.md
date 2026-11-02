# Kitty V6 — Frozen checkpoint before other projects (2026-11-02)

**Repository:** [ryushi01/CuteDisplay](https://github.com/ryushi01/CuteDisplay)  
**Canonical development branch:** `main`  
**Checkpoint intent:** Stop the current Kitty V6 memory / S3 resource / UART investigation and resume **much later** without losing decisions or confusing proposed source with deployed code. Other development projects may now proceed independently.  
**Scope:** This is a source and evidence checkpoint. It does NOT deploy anything, patch the live Ubuntu gateway, reflash S3 or C5, erase SD, create an iPhone enrollment, or authorize private recall.

## 1. What was consolidated onto main

- All commits produced during the Nov 2 Kitty memory/privacy/stack work were written **directly to `main`**: idle SSE summary parser diagnostics, UTF-8 clipping, SD acknowledgement/retry/journal recovery, S3 loop stack 10 KiB, memory isolation on unverified realtime calls, read-only UART ACK diagnostics, private semantic owner-grant endpoint, local-only semantic HTTP transport, and opt-in Python extractive long-call continuity prototypes.
- The **last checked full CI for the active code before consolidation was green**: [GitHub Actions run 41407448975](https://github.com/ryushi01/CuteDisplay/actions/runs/41407448975) at `2a5018e8d6a0635f6ebc0bd105bc8cf17b70b715`, including C5/S3 firmware compile, S3-only artifact and offline privacy tests. Source changes after that successful run in this consolidation consist of documentation and historical file imports, not firmware behavior.
- The only open PR at checkpoint was [#3, cross-AI voice and identity test](https://github.com/ryushi01/CuteDisplay/pull/3). **Merged**, commit `7b75d268550281f784f6d9afbfea83461742f912`. No other open PRs after the merge.
- Four historical, previously branch-only documents were copied into `main` with explicit **historical, not deployable** banners:
  - `docs/hardware/SPI_UART_MIGRATION_2026-10-28.md` (unimplemented SPI design, no pinout deployment)
  - `docs/REALTIME_VOICE_IMPLEMENTATION_PLAN_2026-10-28.md` (older voice design gate)
  - `docs/handoff/2026-10-29-realtime-voice-hardware-validated.md` (old validated rollback record)
  - `docs/KITTY_CALENDAR_AWARENESS_2026-10-29.md` (older calendar design checkpoint)
- README updated to this checkpoint. The long-running detailed investigation log remains [KITTY_V6_CURRENT_HANDOFF_2026-11-01.md](KITTY_V6_CURRENT_HANDOFF_2026-11-01.md).

**Important branch policy:** Many old feature/recovery/stable branches are already ancestors of current `main` (`ahead_by=0`), or preserve **diverged, obsolete firmware** dating to Oct 27–29. We intentionally did **not** merge divergent old firmware again, because that could undo tested C5/S3 behavior or reintroduce old resource/privacy bugs. The original remote branches remain available intact as historical recovery points; the active Nov 2 work and useful outstanding documentation are consolidated to `main`. Do not mistake old branch tips for newer unfinished current work.

A **pre-consolidation rollback branch** was created:
`checkpoint/2026-11-02-memory-project-pre-final-merge` at `2a5018e8d6a0635f6ebc0bd105bc8cf17b70b715`.

A final immutable-intent checkpoint branch will point to the completed documentation commit. See the branch name `checkpoint/2026-11-02-kitty-v6-frozen-main`.

## 2. Accepted deployed hardware / infrastructure

| Component | Baseline to preserve |
| --- | --- |
| ESP32-S3 brain | Freenove ESP32-S3-WROOM CAM N16R8; Wi-Fi/realtime, INMP441 mic, MAX98357A amp, SD, camera |
| ESP32-C5 face | LILYGO T-Display-C5 **firmware v38**; display/animations/buttons/BLE configuration. **No additional C5 flash** during this phase |
| Audio | Working 24 kHz realtime mic/speaker; do not change I²S pins, timing or frame buffers speculatively |
| S3 ↔ C5 | Existing UART and ACK protocol; **do not** apply experimental SPI proposal |
| SD memory | S3 microSD is canonical durable archive; never erase/format to fix a recall issue |
| Ubuntu | Working Open WebUI / memory-service / snapshot/index support. The private live `realtime.py` and environment are **not** a public-repo copy |
| Mac | Existing AI/TTS inference server; do not run simultaneous memory-summary GPU inference during live calls |
| iPhone | App setup / device management, primarily Bluetooth via **C5**, not S3 |

GitHub source `main` is ahead of some physically tested behavior: **a successful CI build is not the same as a flash, runtime verification, or Ubuntu deployment**. The latest source-only server authorization and live-continuity changes have **not** been deployed to Ubuntu.

### Actual physical S3 hardware evidence (2026-11-02)

The owner performed **one S3-only firmware flash** before this later source work. Observed:

- Normal conversation automatically archived five turns and started background summarization after the call, with **no** `memory ai on`.
- `[MEMORY AI] result HTTP=200 ... format=3 stream_done=1 accepted=1 summary_stage=6 summary_bytes=125 clipped=0 output_limit=0`. Idle SSE parser works on that captured request.
- `[MEMORY V6] summary persisted ack_offset=2878`; previous cursor `2578`: **300-byte advancement**, then `awaiting=0`, no pending queue, `ai_http_paused=0`. This verifies one successful SD write and journal ACK, **not** reboot/readback durability or later-call private recall.
- S3 `loop_stack_highwater_bytes=2596` (previous worst about **548** bytes), `internal_min=52148` bytes, `internal_largest=31732` bytes, `psram_min=4485364` bytes. The 2 KiB loop-stack increase helps; internal heap pressure remains.
- `mic_dropped=0`, speaker dropped samples zero in the observed call. Speaker underrun counter accumulated **6166** and there were **three AI UART ACK timeout** entries; these counters do not alone establish audible loss.
- One unexpected realtime WebSocket disconnect was recorded while Wi-Fi remained connected (`rssi=-54`). Root cause **not established**.
- A probable `person:shana` match remained **unverified**; owner fact writes were skipped. The isolated unverified summary is **not** safe to insert into global owner context.

Earlier physical testing also established recall of an **explicitly approved, shareable** “Mochi Planet” memory across calls; this is different from private owner recall.

## 3. Completed source engineering, separated from hardware proof

1. **Idle summaries and journal recovery:** SSE-aware parser, precise failure-stage diagnostics, UTF-8 length clamp, exact-byte SD append/ACK checks, retain accepted result while retrying SD open failures, reject torn job/ACK lines after reset. Hardware verified successful one-session ACK; power-fail/restart and repeated-session persistence still need tests.
2. **Loop stack / memory:** S3 loop task raised from 8 KiB to 10 KiB; hardware minimum 2,596 bytes. S3 Bluetooth has no active application duty (phone BLE is C5); controller-memory release is guarded. No proof of complete heap-pressure resolution.
3. **Realtime memory privacy:** unverified realtime auth and live refresh now use public-only calendar + approved shared-note context, not owner facts or isolated guest summaries. This is in source and CI, **not yet confirmed on hardware after the change**.
4. **UART diagnostics:** S3-only read-only counters `[SYS UART AI] ack_ok=... ignored_ack=... retransmits=... timeouts=... pending=...` in `system status`; existing retry/ACK timing and C5 firmware unchanged. Hardware readings **not yet captured** for this latest source.
5. **Owner-only private semantic search:** Ubuntu `/semantic` and `/semantic/context` source handlers now require both device bearer and **signed, short-lived, matching session owner grant**, validated on the memory service itself before accessing the search index. Separate opt-in local client verifies hostname/port or private Unix socket, rejects redirects and proxies, and requires owner grant. Unit/handler tests passed. **Current deployed Ubuntu code not updated**, iPhone proof not wired end-to-end, and unverified SD rows do not become verified owner rows.
6. **Extractive live continuity prototype:** new `server/kitty_live_rolling_context_v6.py` stores a bounded set of explicit decisions and latest turns **only for an independently trusted, same-session, same-speaker, same-item flow**; clears on identity change / unknown turn / disconnect. Simulated 120-turn test retained an early C5 decision, Japanese UTF-8 cap, speaker-isolation tests passed. Integrated into optional `kitty_turn_context_v6.py` but **NOT connected to live gateway**; this is NOT a model-generated rolling summary.

## 4. Six unfinished priorities — resume when requested

| Priority | Exact next step | Guardrail |
| --- | --- | --- |
| 1. Private cross-call recall | Integrate real iPhone owner proof and trusted gateway **turn/session** issuer; test signed owner grants against actual SD-sourced indexed owner rows, verify restart/readback | Voice match / spoken name / device token **never** owner proof. Keep unverified summaries separate |
| 2. Very long uninterrupted calls | Stage the bounded live-turn helper against real gateway turn IDs and verified speaker changes; confirm early explicit decisions survive long calls; eventually implement true rolling summary if needed | No global guest memory, concurrent Mac inference, or realtime latency penalty |
| 3. Internal S3 RAM | Repeat TLS stress with latest counters/fragmentation and internal-largest-block, measure real improvement before optimizing | Preserve realtime audio and PSRAM allocation bounds |
| 4. Loop stack | Run longer real call; compare high-water headroom to 2,596 B and monitor reset behavior | Avoid removing the 10 KiB stack protection prematurely |
| 5. UART/audio stability | After one consolidated **S3-only** flash, collect new ACK ignored/retry/timeouts, dropped PCM, underrun and disconnect timestamps; investigate cause before changing UART/C5 | Do not treat underruns as proof of speaker drops; keep C5 v38 |
| 6. Privacy / source-of-truth | Audit deployed private Open WebUI gateway and legacy nondelegated `BrainAI` path, verify owner-vs-guest trust boundary and SD-only durable authority | Do not log secrets or private transcripts in commits/tests |

The optional client-server owner grant is **session scoped**, not yet one authenticated human speech turn. An owner login grant is not equivalent to a reliable multi-person voice diarization result. Do not promise automatic personal recall until this gap is closed and tested.

## 5. Source locations and resume instructions

- S3 firmware: `firmware/CuteDisplayBrain/{CuteDisplayBrain.ino,BrainMemoryAI.h,BrainAI.h,BrainRealtimeDirect.h,BrainRealtimeAudio.h,KittyMemory.h,KittyMemoryContextV6.h}`.
- C5 firmware (unchanged physically): `firmware/CuteDisplay/lcd.ino`, `C5FirmwareVersion.h`.
- Ubuntu service/authorization: `server/kitty_memory_service.py`, `kitty_semantic_authorization_v6.py`, `kitty_owner_session_v6.py`, `kitty_owner_proof_v6.py`, `kitty_semantic_async_client_v6.py`.
- Live call prototype: `server/kitty_live_rolling_context_v6.py`, `kitty_turn_context_v6.py`.
- Source tests: `server/test_kitty_semantic_authorization_v6.py`, `test_kitty_semantic_async_client_v6.py`, `test_kitty_live_rolling_context_v6.py`, `test_kitty_turn_context_v6.py`, `test_kitty_sd_summary_journal_contract_v6.py`, `test_kitty_realtime_public_memory_contract_v6.py`, `test_kitty_s3_memory_stability_contract_v6.py`.
- CI: `.github/workflows/build-s3-with-c5-update.yml`; successful build reference [#41407448975](https://github.com/ryushi01/CuteDisplay/actions/runs/41407448975). It publishes `KittyV6-S3Only-NoC5OTA` as a no-C5-payload build artifact.
- If a future flash is justified: use **only S3-only application image** and preserve NVS, microSD, C5. Do not use `CombinedFirmwareImage` to overwrite C5.
- On Ubuntu, inspect the **actual active private gateway** and `kitty-memory-v6.service` source/env through a read-only diff before deploying; do not assume the GitHub scripts match the live files or copy private credentials into commits.
- Diagnostic commands after a later flash: `system status`, `memory summary status`, normal long conversation; look for `accepted=1`, persisted `ack_offset`, `[SYS UART AI]` and internal heap/stack logs. Do not enable memory with a manual switch.

### Prompt when continuing much later

> Resume Kitty V6 from `docs/KITTY_V6_CHECKPOINT_2026-11-02.md` on `ryushi01/CuteDisplay` `main`. Preserve physically working S3/C5 v38 and deployed Ubuntu/Mac audio, verify current GitHub HEAD/CI and actual live-server state before changes, and continue the six unfinished priorities. The last hardware proof was automatic SSE summary `accepted=1` with SD ACK `2578→2878`; owner-private recall and long-call rolling memory are source foundations but **not deployed**. Do not merge stale diverged firmware or flash C5. Use one consolidated S3-only flash only after CI and a specific hardware-validation need.

## 6. Checkpoint safety rules

- Keep the most recent user-accepted physically working firmware; do not claim this source-only batch has been hardware tested.
- S3 microSD, credentials, private gateway env, voiceprints and personal transcripts are **not** in public GitHub. Do not request broad dumps if a bounded log suffices.
- No automatic owner verification from `person:shana`, voice score, self-introduction or iPhone Bluetooth pairing.
- New unrelated projects can proceed on independent branches from this frozen `main`; this checkpoint is for eventual memory-work resumption.
