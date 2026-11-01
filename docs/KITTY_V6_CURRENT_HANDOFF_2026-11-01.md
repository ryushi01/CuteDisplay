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
