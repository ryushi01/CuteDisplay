# Kitty V6 — Current checkpoint and next-chat handoff (2026-11-01)

## Intent
Preserve the **working** voice-first Kitty companion and improve reliability of long conversations **without** allowing an unrecognized voice to disclose another person's private facts. iPhone app is for setup/settings/management only, not calls or automatic memory approvals.

## Verified from physical S3/C5 and Ubuntu logs
- S3 realtime audio calls and C5 v38 face/UI run. Existing call audio occasionally experiences buffered speaker pressure; do not casually alter I²S or realtime timing.
- S3 SD memory mounted; nine-file snapshots finalized to Ubuntu, including `shareable_memories_v6.tsv`.
- Multiple finalized snapshots include the explicitly approved `kitty_test\tshared\t...Mochi Planet` entry.
- Authenticated Open WebUI shared-context client returned `Mochi Planet found: True`, length 159.
- After session-instruction persistence gateway patch, Kitty **said Mochi Planet correctly** in a voice call.
- X-vector speaker recognition produced a mixed series of scores: 0.9522, 0.9613, 0.9544, 0.9703, 0.9695, 0.9423, 0.9617, 0.9544; at 0.965 threshold only two were candidate matches. User also heard Kitty use their name in a follow-up call, **not proof of owner authentication**.
- `KITTY_XVECTOR_SHADOW_ENABLED=1`, `KITTY_XVECTOR_CANDIDATE_ONLY=1` confirmed in private Ubuntu env. A conversation candidate does not authorize owner memories.

## Source and deployed runtime
Repository: `ryushi01/CuteDisplay`. Previous active feature branch: `feature/kitty-semantic-v6-cpu`. This checkpoint is intended to be merged to `main`. Main contains the **tracked source**, not an image of the live server.

Ubuntu active source:
- `~/kitty-v6/CuteDisplay/server/` for `kitty-memory-v6.service`
- `~/kitty-v6/private/semantic-gateway/realtime.py` bind-mounted into Open WebUI
- `~/kitty-v6/private/kitty-sync-deployment/live-sync-build` previously used to track the feature branch
- private env `~/kitty-v6/private/memory-service.env` — do not commit or print secrets

Working gateway source was patched on host using tracked scripts:
- `server/patch_kitty_realtime_shared_v6.py`
- `server/patch_kitty_realtime_shared_persistence_v6.py`
- `server/patch_kitty_candidate_hint_v6.py`
- `server/patch_kitty_candidate_hint_stability_v6.py`
- `server/patch_kitty_candidate_response_wait_v6.py`

Each script patches an existing mounted route and keeps a backup. **Do not blindly reapply** scripts to a different route or assume GitHub contains the mutated runtime `realtime.py`.

### Ubuntu deployment audit — 2026-11-01

User ran a **read-only audit** of the working Ubuntu machine. Observed:
- `kitty-memory-v6.service`: `active`; Open WebUI container: `healthy`.
- Deployed `kitty_memory_service.py`, `kitty_sd_snapshot_v6.py`, `kitty_shareable_memory_v6.py` matched the then-checked-out feature-branch source.
- The active `kitty_speaker_cpu_v6.py` had **one line** different: `recognize_candidate(raw, threshold=0.960)` instead of 0.965.
- The active `kitty_xvector_shadow_worker_v6.py` also had **one line** different: minimum accepted threshold 0.960 instead of 0.965. This **local-only** change couples the conversational and experimental-identity minimums.
- GitHub **main source is safer and already contains the equivalent conversational behavior**: `recognize_candidate(raw, threshold=0.960, conversational_hint=True)`, with `minimum = 0.960 if conversational_hint is True else 0.965`. Do **not** copy the live worker's globally relaxed validation into GitHub or automatically deploy from GitHub to the live Ubuntu instance. Future Ubuntu alignment should be explicit, one small code update with tests, with no change in candidate-only privacy policy.
- Gateway Open WebUI bind mounts were confirmed:
  - route: `~/kitty-v6/private/semantic-gateway/realtime.py`
  - client: `~/kitty-v6/private/semantic-gateway/kitty_semantic_async_client_v6.py`.
- Active route patch markers (line numbers at the time of audit): `KITTY_APPROVED_SHARED_INITIAL_CONTEXT_V6` (602), `KITTY_CANDIDATE_STABLE_V6` (702), `KITTY_SHARED_CONTEXT_PERSIST_SESSION_V6` (779), `KITTY_SHARED_CONTEXT_PERSIST_RESPONSE_V6` (890), `KITTY_CANDIDATE_RESPONSE_WAIT_V6` (903).
- GitHub tracks the **sanitized gateway patch scripts**, not the fully mutated host-mount `realtime.py`. The private environment file, voice models/profile, audio samples, API secrets, and SD archive are intentionally excluded. Never publish these.
- The developer's detached worktree displayed `?? server/__pycache__/`; these Python cache files are ephemeral, **not part of the project**. Their `origin/main` tracking ref was absent despite `git fetch origin main` returning FETCH_HEAD; use `git fetch origin main:refs/remotes/origin/main` if local main tracking is needed. Do not blindly switch this live deployment checkout or run `git add .`.

This audit confirms **what is deployed versus what is tracked**. It does not establish complete byte-for-byte identity across all host files or reproduce private runtime configuration from GitHub alone.

## Why private identity and long memory still fail
- Voice candidate-only mode deliberately reports `speaker_id=unknown`, even on a candidate X-vector match; private recall is protected.
- `[MEMORY V6] unverified turn archived; owner fact writes skipped` is common.
- Crucial S3 source: `firmware/CuteDisplayBrain/KittyMemory.h` around lines 1335–1427. The SD worker appends to `conversations.tsv` then, on `!e.ownerVerified`, calls `updateStorage(); continue;` before reaching the batching of `SummaryCandidate` and `ConsolidationCandidate`. Therefore unknown-speaker conversations are archived but **not summarized/consolidated by this path**.
- Do not simply delete the guard: owner facts must remain protected and globally shareable notes must continue to require explicit approval.

## Next implementation plan (new chat)
1. Design **conversation-scoped** continuity independent of speaker identity: append every turn, summarize unknown turns in a non-owner channel, keep current active-call context in bounded RAM and durable SD history as appropriate.
2. Retain strict separation of `ownerVerified` fact writes and voice-candidate claims. Avoid reclassifying unknown turns as Shana and avoid globalizing private summaries.
3. Use speaker/call scope to avoid leaking summaries to the next speaker or across unrelated sessions; no global session-wide insertion of private notes. Validate actual retrieval and truncation behavior.
4. Add Python/static tests and compile S3 firmware with existing partition layout; only request flash when a targeted hardware test is needed.
5. GitHub main already separates the 0.960 conversational hint from the 0.965 experimental identity minimum; consider aligning the active Ubuntu worker explicitly later, without changing the working deployment during memory-continuity development.
6. Preserve S3 microSD archive, working audio, C5 v38, all private settings, and the verified Mochi Planet shared-memory flow.
7. Avoid repeated diagnostics; user prefers a minimal test plan and direct verified updates.

## Minimal safety checklist
Do not erase all flash or format SD; do not flash C5 sketch to S3; do not merge credentials or memory snapshots into public Git; do not claim a successful GitHub build proves deployed firmware parity; distinguish **source** from separately patched **live runtime**.

## Session-scoped summary batching increment — 2026-11-01 (not deployed)

Added to GitHub `main` in commits `8c6393d1`, `92c41d82`, `28f37a64`:
- S3's realtime call toggle assigns a monotonically increasing in-process conversation identifier, carried by each archived turn into the SD summary batching path. Reconnects during the same requested call keep that scope.
- Summary batches do not mix different conversation IDs or verified/unverified records. End-of-call queues a non-blocking summary flush marker after any pending turns, allowing fewer than six turns to produce a summary when the queue has capacity.
- The idle AI summarizer returns the conversation ID with its result. The separate `unverified_summaries_v6.tsv` rows now contain `timestamp<TAB>conversation_id<TAB>summary`. The legacy verified-owner `summaries.tsv` format remains unchanged.
- No new scope is injected into Open WebUI globally; candidate voice recognition still cannot authorize owner facts, and the microSD remains authoritative.

**Limitations / next steps:** conversation IDs are volatile and reset on S3 reboot; a marker can be dropped when the existing bounded writes queue is full; summary queues can discard old candidates under load; idle inference requires configured service and connectivity. Call-scoped retrieval, safe intra-call speaker changes, persistent call ID semantics, and validation on physical S3 remain outstanding. These changes do **not** prove complete turn delivery when the write queue overflows or when SD writes fail. Preserve microSD, private settings, C5 v38 and gateway bind mounts. Do not flash automatically.

## Incremental source patch — 2026-11-01 (not deployed)

GitHub `main` now includes the initial S3 summarization safety patch (commits `5082a958`, `d048a289`). The SD worker submits **both verified and unverified** archived turn batches to the existing idle-only AI summarizer, with a trust flag propagated to the result. The SD worker writes unverified results to `/kitty/unverified_summaries_v6.tsv`, **not** the globally injected `/kitty/summaries.tsv`. The owner-fact and AI consolidation gates remain restricted to `ownerVerified`. Mixed verification-status batches reset at the boundary instead of combining identities.

**Limitations:** This is only the first safe increment. The new unverified summary file is local to S3 and is **not** one of the nine exported snapshot files; its entries are **not** injected into conversation context or used for cross-call recall. The existing summary/owner-fact context injection policy also needs a separate end-to-end security review before exposing more unverified content. Durable call/session identifiers, same-call rolling retrieval, partial-batch flushing, and a hardware build/flash remain to be implemented/validated. No deployed Ubuntu files, private secrets, C5 v38, or existing SD contents were changed. Do not describe the full long-conversation reliability goal as complete.

## Fast privacy hardening follow-up — 2026-11-01 (source only)

Commit `f67bd78` guards the idle AI parser: a model response to a **summary** request can never propose personal `facts` into the verified owner catalog, even if the model unexpectedly returns a `facts` array alongside its summary. Eight focused source invariants checked on GitHub `main`; no firmware compile, flash, active-call retrieval or hardware test was performed. **Active-call summary reinjection remains disabled**: there is no trustworthy mechanism to distinguish two unknown human voices inside the same open call, so exposing unverified prior speech to a new speaker would risk private-memory leakage. Next safe path is a speaker-transition-boundary mechanism with session-scoped retrieval and strict reset, verified on hardware.

## Summary flush backpressure fix — 2026-11-01 (source only)

Commit `11d5a3c3` adds a fallback to the existing end-of-call marker: if the bounded write queue is full, the SD worker records the pending end and flushes the matching summary batch after the queue drains. It never drops archived turns to enqueue a marker. This is a best-effort, single-pending-boundary fallback, not a guarantee across multiple overlapping queued call endings or resets. No SD formatting, live deployment changes, or gateway modification. Same-call injection of unverified summaries remains disabled for speaker privacy. Compilation and physical testing are still required before flashing.

## Idle summary queue backpressure — 2026-11-01 (source only)

Commit `3fdb5dbd` expands the PSRAM-backed summary-candidate FIFO from 2 to 8 batches (about 6 KiB of queue payload). When full, it now preserves the oldest queued batches instead of silently evicting them, emits `[MEMORY V6] summary queue full; archived turns retained on SD`, and increments `summaryBackpressure` for diagnostics. Complete conversation-turn archiving still precedes summarization. This lowers transient pressure but does **not** guarantee that every summary is generated: new batches can still be skipped during prolonged inference outages, and the AI runs only after the conversation finishes/is idle. No live-call memory injection or speaker authorization change; hardware not flashed or compiled.

## Idle inference interruption retry — 2026-11-01 (source only)

Commits `781c2f22` and `f17a8d3c` retain an in-flight summary candidate in RAM until the idle model returns an accepted summary or an explicit empty summary. A call interruption, HTTP failure, malformed response, or failed summary-result enqueue does not immediately discard this candidate; existing idle/retry timing governs subsequent attempts. An undersized candidate completes without infinite retry. The existing verified-owner fact isolation remains unchanged. **This is RAM retry only, not durable reboot recovery**. Pending work and unsummarized queue entries can still be lost on restart, so durable SD journal/replay is the next task. Neither firmware compilation nor hardware flashing was performed.

## Durable microSD summary job replay — source checkpoint (2026-11-01)

GitHub commits `58aab01a`, `c039d4c0`, `c85f5af4` implement an S3-only, append-only `/kitty/summary_jobs_v6.tsv` job journal and `/kitty/summary_jobs_ack_v6.tsv` completed-byte-offset cursor. Summary batches are journaled by the SD worker before idle inference, with verified flag and conversation number. The SD worker replays the first unacknowledged job after restart, with at most one in flight, writes its summary to the original verified/unverified destination, then appends the completion cursor. Explicit empty summaries also acknowledge a job. The S3 idle worker passes the journal's byte-offset identifier back with its result. No new journal or private summary file is added to the nine-file Ubuntu export; no global injection of unverified context. Original turns remain preserved in conversations.tsv.

**Remaining cautions:** This is a source-only checkpoint. No Arduino compilation, serial log, hardware run, flash, or crash-consistency test has been completed. Interrupted writes can leave a partial trailing journal row; replay deliberately pauses on invalid rows instead of deleting or rewriting history. A summary write that succeeds before a failed acknowledgement may be repeated on reboot (at-least-once processing). If an acknowledgment write itself fails during a running session, job dispatch remains paused until reboot or future error handling. A job resulting in a nonempty but too-short summary may retry. Existing historical conversations before this journal are not automatically backfilled. Do not format the SD or change existing private credentials or gateway bind mounts.

## Firmware-build regression checkpoint — 2026-11-01

Added `server/test_kitty_sd_summary_journal_contract_v6.py` and wired it into `.github/workflows/build-s3-with-c5-update.yml`, ahead of Arduino setup and the combined firmware compile. This checks journal append/replay/ack contracts, UTF-8 TSV delimiter literals, unverified versus verified storage separation, and absence from the existing nine-file export. The workflow already triggers on pushes to `main` affecting `server/**` or S3 source. The current assistant environment has no Arduino CLI/toolchain and cannot clone GitHub directly; therefore **an actual Arduino compile or CI pass has not been independently verified here**. Inspect the Actions workflow result before flashing; avoid automatic deployment of S3/C5 or private Ubuntu files.

## Post-flash hardware checkpoint and read-only diagnostic (2026-11-01)

The user reports successfully flashing the previous S3 firmware; this confirms flashing succeeded, **not yet** long-conversation recall or SD journal replay. A new source commit `f00bc818` adds a USB console command `memory summary status`, reporting only SD readiness, active call id, last acknowledged journal byte offset, pending-job flag, candidate/result queue counts, summary backpressure and idle AI status. It does not read SD files on the console path or print memory text, secrets, or credentials. This command requires **another S3 build and flash** before it becomes available on the physical device. Do not flash C5 or reformat SD. The journal and summary pipeline remain post-call/idle; safe same-call retrieval is still unimplemented.

## Hardware observation: idle summary timeout — 2026-11-01

User hardware log after normal conversation: `awaiting=1 summary_queue=0 ai_pending=1 job_ack_offset=0` with `[MEMORY AI] skipped HTTP=-1 err=28679`. Espressif error 28679 (`0x7007`) means `ESP_ERR_HTTP_EAGAIN`, indicating timeout waiting for response; the idle worker used `cfg.timeout_ms=2500`. Source commit `ade44e97` increases **idle-only** summary HTTP timeout to 10000 ms; it does not touch realtime WebSocket/voice or C5. The in-flight durable job remains unacknowledged and eligible for retry. This patch requires S3 rebuild/flash and has not yet been compiled or hardware-tested. If still failing, check host availability, TLS and model latency; do not print API keys.

## USB idle AI endpoint diagnostics — 2026-11-01

Added `memory ai config` to the S3 physical USB console (commits `4e9f6100` / `ac549026`). It reads `brain-ai` Preferences and outputs whether settings can be read, URL scheme, redacted host:port (never path, query or URL credentials), model name and a boolean key-present flag. No actual API key is printed, and no configuration is modified. This does not affect realtime voice or TTS. The command is only available **after rebuilding and flashing S3**. Use it to diagnose idle memory summary HTTP error `28679` and distinguish a TLS/HTTPS misconfiguration from Mac-hosted model routing. The previously queued job remains in the SD journal; do not format SD or change C5.

## Idle memory HTTPS diagnostics checkpoint — 2026-11-01

GitHub commit `1a497b2f` changes only `BrainMemoryAI.h`: the idle-only inference HTTP client timeout is 15 seconds (previously 10), and failed requests log elapsed milliseconds, whether a transport connection callback occurred, whether response data arrived, and received byte count. Existing HTTP status and error code remain visible. No URLs, headers, tokens, response bodies, or private memories are logged. The existing SD-journal pending job is retained for retries. Ubuntu GET to the configured public HTTPS endpoint returned 200 quickly and an unauthenticated POST returned 401 quickly; these do not prove the S3 or the Mac-hosted model response works. Firmware compilation and device flash of this patch are not yet confirmed. Avoid changing the realtime voice/TTS path, C5 v38, or microSD contents.

## Mac CPU protection: idle AI HTTP circuit breaker (2026-11-01)

Commits `a13d782f` and `d47fac90`: the S3 idle-only memory inference worker now stops automatically after **one non-interrupted HTTP failure** for the remainder of the boot. No further background requests can overload the Mac inference host until a deliberate S3 reboot. The persistent SD summary journal and its unacknowledged job remain untouched. USB `memory summary status` now exposes `ai_http_paused=1` after such a failure. Does not alter realtime voice, C5, Mac services, credentials, or SD schema. If the first request succeeds, processing continues normally. This is intentionally conservative: even transient HTTP failures pause background consolidation until reboot; not a long-term retry-policy replacement. Build and flash S3 firmware before relying on this behavior. Source contract checks only; hardware behavior not yet validated.

## Controlled Mac GPU idle-inference batch (2026-11-01)

Current source already has a default-disabled (per boot) background memory AI switch, USB-only `memory ai on` / `memory ai off`, `ai_enabled` in `memory summary status`, a 30-second elapsed-budget flag, and a one-error circuit breaker. **The elapsed-budget check is cooperative, not a guaranteed hard interruption of a blocked TLS call or Mac-side inference.** No automatic enabling at reboot; archived turns and pending summary journal survive. Commit `79ecd861` additionally reduces idle inference output max_tokens from 160 to 96 to limit generation work. High Mac GPU can result from the Mac model processing summaries (potentially overlapping late/stuck inference), but the logs do not establish whether it is this job versus another Mac process. Do not assume an S3 HTTP timeout cancels Mac inference. Do not flash for each micro-patch: build a single consolidated firmware, flash S3 only, and first leave idle AI disabled. For controlled opt-in, use physical S3 USB `memory ai on`, observe Mac GPU, then `memory ai off`. The latter requests cancellation; it does not forcibly terminate remote inference. Do not modify working realtime voice, Mac TTS, private secrets, C5 v38, or SD contents.

## One-request GPU budget per USB opt-in (source checkpoint)

Commit `26e439d1` makes `memory ai on` a **single-inference authorization**: on any completed worker path (success, rejection, timeout, interruption), the worker resets `operatorEnabled=false`. This avoids multiple queued summary jobs automatically running in sequence on the Mac, even if the first succeeds. It keeps SD job replay, pending summaries, privacy gates, and realtime voice unchanged. Requests already executing on Mac are not forcibly terminated by this S3 flag; the 30-second budget remains cooperative. No new flash is required until the user elects to deploy a consolidated build; static code review only, not compiled or hardware-validated.

## Consolidated one-shot memory AI regression (2026-11-02)

GitHub commits `53d08c8f` and `79347031` ensure a failed idle-worker task allocation clears the USB one-shot authorization, and add five source regression assertions to the existing journal CI contract: default off, authorization gate, one-request finish, task allocation failure, and cooperative 30-second budget. CI workflow already runs this test before compiling S3/C5. These are source updates only, not a confirmed build or hardware test. Do not flash another micro-update until ready for consolidated validation. A 30-second local elapsed budget does not guarantee terminating Mac-side model inference; monitor GPU/actual model process separately. The backlog remains on SD, and no voice/audio, TTS, or C5 firmware behavior was modified.

## Bounded model input — consolidated batch (2026-11-02)

Commit `7e83ad8a` bounds the text sent to Mac-hosted idle inference to 440 UTF-8 bytes for a summary job or 220 for an optional fact extraction, reducing the model's input workload. The original complete archived turns and durable journal remain unchanged; truncation can omit later details, so this is a latency/cost tradeoff. Commit `2943b7ce` adds source contract assertions. Existing USB-only `memory ai on` remains one request per opt-in and disabled at boot, with cooperative timeout; a remote model may continue computing after local cancellation. Nothing modifies the realtime pipeline, Mac/TTS, C5, private config, or SD. Await one consolidated S3 build/flash; no physical validation of this patch.

## Reproduced idle summary HTTP reply truncation — 2026-11-02

On hardware, one authorized idle summary returned `[MEMORY AI] result HTTP=200 elapsed_ms=13509 rx_bytes=8607 json=0 choices=0 content=0 accepted=0`; journal stayed `job_ack_offset=0 awaiting=1 ai_pending=1` and the Mac GPU returned to normal when work ended. Root cause in firmware: the HTTP callback discarded response chunks when buffered text would exceed 2048 bytes, leaving malformed JSON. Commits `4e00c43d` and `95bdd688` increase bounded reply accumulation to 16384 bytes, reserve 12288, report `truncated`, and add CI source assertions. The complete archived turns, SD journal, one-request-per-USB-opt-in restriction and C5/audio paths are unchanged. Source checks verified against GitHub content; full Actions build and hardware test remain unconfirmed. Next: flash latest successful S3-only firmware and run *one* `memory ai on`, then inspect `result HTTP=200 ... truncated=0 json=1 choices=1 content=1 accepted=1` and advancing `job_ack_offset`. If parsing succeeds but accepted=0, inspect schema instead of increasing timeouts. Do not log API tokens or memory contents.

## Accepted working baseline for next chat — 2026-11-02

User explicitly accepts the **current deployed Kitty V6 behavior as the working baseline** and requests no further firmware modifications in this chat. Code is already committed directly to `main` at `59ec0ce1027307a7cca7b194c632180cbafc2321`; no feature branch merge is needed. Do not merge unrelated open PR #3 without separate review. Keep S3 Freenove and C5 v38, Mac-hosted AI/TTS, Ubuntu Open WebUI gateway, SD archives, UART and current audio pathways intact. Phone Bluetooth belongs **exclusively to C5**; S3 legacy BLE initialization is compiled out by `KITTY_C5_BLE_MIGRATION_ENABLED=1`. Latest code additionally requests BLE controller memory release at S3 startup, and reduces legacy AI HTTP transport buffers. User regards current experience as tested/working for baseline purposes; this is a **user acceptance statement**, not independent proof that every newly committed optimization was flashed and hardware-tested. Latest Actions run 41374720214 was still in progress when inspected; last observed successful build was run 41323907333 for commit `6fd2bad6`.

**Defer to a new chat** (do not make changes now): (1) S3 heap/stack stability and measurement under simultaneous realtime AI/TLS, including loop high-water ~548 bytes, internal minimum ~57 KB, and reset_reason=11; (2) automatic memory summary acceptance and durable journal acknowledgement, especially verifying SSE parsing `accepted=1` and `job_ack_offset>0`; (3) sustained single-call context continuity with on-the-fly archives / memory refresh without parallel GPU inference; (4) strict owner vs probabilistic-speaker separation and memory-privacy gates. Previously observed SSE format=3 with HTTP=200, not parsed by older firmware; current main contains SSE delta parsing and automatic post-call idle summarization with cooldown. Do not claim these four deferred validations passed until observed. No need for manual `memory ai on` in current main. No secrets, user memory text or API keys in diagnostic logs. Keep a single consolidated S3-only flash after next-chat work; do not flash C5.

## S3 physical hardware verification — 2026-11-02, automatic summary accepted

User-provided S3 USB log from normal multi-turn realtime conversation **after a consolidated S3-only flash**, with C5 unchanged. This supersedes the earlier `accepted=0` *as the latest observed result*, not as a guarantee against all future parser failures.

- Boot/idle `memory summary status`: `sd=1 ai_enabled=1 ai_http_paused=0`, `job_ack_offset=2578`. No `memory ai on` command was necessary.
- Conversation archived five turns: `indexed=272` to `277`, `saved=5 failed=0`. Speaker-related turns remained **unverified** and explicitly skipped owner-fact writes. Some probabilistic/introduced speaker claims used `person:shana` in a **separate untrusted speaker-claims file**; no verified owner identity was established.
- After the call ended, one idle background HTTP request completed: `HTTP=200 elapsed_ms=12008 rx_bytes=8140 truncated=0 format=3 stream_done=1 stream_chars=139 accepted=1 summary_stage=6 summary_bytes=125 clipped=0 output_limit=0`.
- SD worker confirmed `[MEMORY V6] summary persisted ack_offset=2878`, advancing the job cursor **300 bytes**. A later status showed `awaiting=0 summary_queue=0 results_queue=0 backpressure=0 ai_running=0 ai_pending=0 ai_http_paused=0 ai_enabled=1`. This verifies a successful append and ACK in this session; no reboot/SD readback verification is yet available.
- Under concurrent AI/TLS the snapshot showed `internal_min=52148` bytes, `internal_largest=31732` bytes, `psram_min=4485364` bytes, and `loop_stack_highwater_bytes=2596` (previously ~548 bytes). Do not characterize memory pressure as solved: internal minimum is below the previously observed ~57KB; available largest internal block remains ~31KB.
- Realtime mic and speaker dropped-sample counts remained zero; audio-task stack headroom was 6116 bytes. Speaker underruns accumulated to 6166, and three `[AI] UART ACK timeout` entries appeared alongside successful C5 `ACK AI` messages. Source counters can increase while remote reply is awaited, so do not equate underrun count with measured lost samples. C5 ACK handling draws the AI text before acknowledgement; cause of timeouts remains unverified.
- One unrequested realtime WebSocket disconnect was observed (`requested=0 wifi=1 rssi=-54`). Wi-Fi remained connected; no established cause from this log.
- `reset_reason=11` was reported repeatedly within the **same continuously increasing uptime**; these repeated status prints do not imply additional resets during this test.
- `[CALL MEMORY] live_refresh=1` and several `context refresh accepted` lines prove gateway negotiation/ACK, **not** successful same-call early-detail recall or later-call private-memory access.

**Remaining six-priority scope:** (1) confirm actual later-call recall through an authorized, privacy-safe route; existing unverified summaries are intentionally not injected into global owner context; (2) safely test/implement continuous-call rolling history without a concurrent Mac inference job or accidental cross-speaker disclosure; (3) monitor internal heap fragmentation under TLS and reserve PSRAM for eligible allocations only; (4) verify the 2596-byte loop stack headroom in longer calls; (5) investigate UART ACK timeouts, underrun semantics, and unrequested WebSocket disconnect without changing functional audio timings speculatively; (6) enforce that probable voice identity / self-introduction never authorizes owner memories. Avoid repeat flashing until a consolidated, CI-passing S3-only change needs hardware validation. No C5 changes.

## Follow-on privacy-safe recall and S3 UART diagnostics — 2026-11-02 (source only)

Follow-on work from the **hardware-proven** summary checkpoint at `8724c9e`. The previously validated S3/C5 physical firmware was **not** reflashed or modified during this source increment; the Ubuntu private gateway, memory service process, Mac inference/TTS and C5 v38 remain unchanged.

- Realtime WebSocket auth and `kitty.memory.refresh` previously called `KittyMemoryContextV6::snapshot()`, which exposes verified-owner fact/summary caches without an independently authenticated human speaker. Current S3 source now calls `unverifiedCallSnapshot()` at both points, exposing only clock/calendar and **explicitly approved shared SD notes**. `sharedRevision` also schedules a safe refresh if an approved note changes. Commit series `763b943b`, `55fc309a`, `68a85beb`, `7375d34c`; privacy source tests are in main firmware CI. This does **not** automatically expose `unverified_summaries_v6.tsv`.
- Optional Ubuntu per-turn semantic retrieval previously accepted `voice_probable` and `explicit_introduction` attribution for guest-history lookup. New tracked helper requires `provenance=session_verified`, a **separately supplied trusted same-item reference**, and guest role; default requests remain fail-closed. Related source and tests `2c5a4e70`, `e72341b2`, `44b08a4b`. No issuer of trusted item-bound identity is wired into the live candidate-only gateway, and the active Ubuntu server has **not** been deployed from GitHub. This is a private-memory safety foundation, not completed automatic owner recall.
- Add boot-lifetime read-only S3 UART AI counters `ack_ok`, `ignored_ack`, `retransmits`, `timeouts`, and `pending` to `system status`. No retry periods, payloads, I²S processing, C5 firmware or UART timing changed. Source commits `5b82d8ab`, `7c3f3f54`, `1fcd0c7d`. Values require future consolidated S3-only firmware flash for physical measurement.
- **Remaining privacy audit:** legacy nondelegated S3 `BrainAI` still has access to owner fact/history search without per-human authorization, and the Ubuntu semantic service's token-authenticated `/semantic/context` endpoint still relies on a caller-provided speaker ID. Neither path should be described as a complete owner-proof mechanism. The deployed gateway has separate private patches; review its live trust boundary before enabling private recalls. Never equate an enrolled speaker candidate with an owner grant.
- **Long uninterrupted calls:** no automatic summary reinjection of unverified speech is enabled; unknown-speaker transitions cannot be trusted. Future work needs a server-trusted, item-bound speaker session and bounded, speaker-transition-safe rolling context. Keep the background Mac summarizer idle-only; do not add concurrent inference to preserve long conversations.

Tests: source privacy contracts and item-bound trust tests added to the combined firmware CI. Verify the latest Actions result before producing a candidate. One S3-only image **without an embedded C5 payload** must be used for a later consolidated flash, not a combined firmware image. The prior success `accepted=1 job_ack_offset=2878` remains the validated deployed baseline.

## Private semantic recall service authorization — 2026-11-02

**Scope:** Six-item Kitty V6 backlog, specifically later-conversation recall / memory privacy. Source-only changes on `main`, **not deployed** on the live Ubuntu gateway or S3. The hardware-validated `accepted=1` idle summarizer, C5 v38, Mac AI/TTS and audio pipeline remain unchanged.

**Security problem fixed in tracked source:** Ubuntu `POST /semantic/context` and `POST /semantic` formerly accepted a caller-supplied `person:...` speaker ID with only the shared device bearer. That key authenticates a device, not a human; a direct request to the memory service could bypass gateway speaker checks.

- New `server/kitty_semantic_authorization_v6.py` checks signed short-lived owner-session grant using existing `verify_grant`, `OWNER_PROOF.secret`, exact `session_id`, and the **fixed** speaker `person:owner`. Missing config/grant, guest or probable voice IDs, mismatched session and expired/forged signatures all fail closed. Both private semantic HTTP endpoints enforce the gate *before* opening the index or invoking semantic search. Commits `b41f4844`, `5d150cbb`.
- `server/test_kitty_semantic_authorization_v6.py` exercises real HTTP handler control flow offline for denied/valid owner requests without downloading embedding models or exposing source text. Added it to main CI in `22d09c20` (tests commit `84ff0fd8`).
- `server/kitty_semantic_async_client_v6.py` now has an opt-in `owner_semantic_context()` that transmits the owner grant and session ID **only** to the validated local service. Its URL guard parses the actual hostname/port or normalized private Unix-socket path rather than trusting string prefixes. It blocks HTTP redirects and disables environment proxies, avoiding accidental off-host forwarding of device token, grant or query. Commits `0a6abad1`, `2b5e816f`, `c2c120b0`, `527a5443` with tests in `736074e3`. **Existing guest helper without a signed owner grant now receives HTTP 403** (intended fail-closed behavior).
- For a future authenticated caller, API request fields are `query`, `speaker_id="person:owner"`, `session_id`, and `owner_grant`, alongside the existing service bearer. The server **must not trust a self-declared owner name, voice probability, Bluetooth pairing, or an S3 bearer key** as owner proof.

**Important limits:** This is the owner-search authorization *foundation*, not end-to-end remembered-owner conversation. iPhone Secure Enclave proof is not yet integrated into the working app/gateway, the deployed Ubuntu process remains unchanged, and S3 source still records realtime voice turns as `ownerVerified=0`. Older unverified summaries in `unverified_summaries_v6.tsv` are intentionally excluded from global owner cache and semantic snapshot export. Search of `person:owner` currently may return no results until trusted owner attribution and indexing exist. Session grants are short-lived but are **not yet one-specific-turn authorization**; do not call this complete speaker-bound privacy. Other unverified legacy AI history/fact context paths need a separate design before owner-private recall is enabled system-wide.

**Still open:** (1) authenticated private later-call memory, (2) stable per-speaker rolling context during long uninterrupted calls with no concurrent Mac inference, (3) internal heap/TLS pressure, (4) longer loop-stack margin validation, (5) UART retry/late-ACK metrics and WebSocket disconnect causes, (6) full privacy of legacy/manual AI and probable speaker paths.

No firmware flash required for this source-only server change. Before any Ubuntu deployment, diff the actual private `realtime.py` and active memory service against tracked source and test on a staging instance, since the repo cannot certify the live process. Preserve the existing working setup.
