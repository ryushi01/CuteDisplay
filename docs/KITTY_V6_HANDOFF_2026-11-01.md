# Kitty V6 — New-chat engineering handoff (2026-11-01 JST)

**Repository:** `ryushi01/CuteDisplay`
**Active branch:** `feature/kitty-semantic-v6-cpu`
**Source baseline verified before handoff:** `ce9020065e1fffd77ab5268efc783dad5db0aa07`.
**Do not merge or claim all end-to-end goals complete.** This handoff itself is a documentation-only follow-up commit.

## Product and safety priorities
Kitty is a two-board conversational companion: Freenove ESP32-S3 Brain (I2S microphone and speaker, Wi-Fi, microSD and AI gateway) and LILYGO T-Display-C5 (landscape display/expressions/BLE/buttons), connected through UART. C5 firmware is **v38**, working. Preserve responsive full-duplex audio, caption/face animations, Wi-Fi, privacy boundaries and existing provider protocol. No unnecessary firmware flashing or repeated long idle waits.

MicroSD is the authoritative archive. Ubuntu receives authenticated TLS snapshots and builds optional semantic retrieval. **A probabilistic X-vector speaker match is NOT owner authentication** and must never unlock private facts; no historical unknown records should be retroactively assigned to a person.

## Verified observations (not aspirational)
- **Realtime voice and display work**, with face expression calls observed. Microphone drops remain an issue under concurrent sync; they are a metric, not proven sole cause.
- **Public profile exists:** `/app/backend/data/kitty-public-profile.json` inside Docker `open-webui` was checked with `docker exec -i`: `enabled=True, name=Shana`. The initial-session public-profile injection anchor `KITTY_INITIAL_PUBLIC_PROFILE_V6` was found in `/app/backend/open_webui/routers/audio/realtime.py`. **Actual provider receipt and model use not yet confirmed**; Kitty has said she does not know the user's name. Do not introduce risk-prone realtime `session.update` or `conversation.item.create` experiments; previous ones disrupted audio.
- **Live synchronization demonstrated:** S3 `[MEMSYNC] snapshot finalized`, HTTP 200, success counter reached 2 in earlier logs, even during calls. A finalized Ubuntu snapshot `snapshot-s3_1793516633_5c97e536` contained 169 conversation records: 166 `unknown/unverified`, three `person:shana/explicit_introduction`, **zero `voice_probable`**. Snapshot validation covered that specific snapshot, not every later attempt.
- **X-vector candidate path partly verified** in earlier Ubuntu logs: candidate `person:shana` (e.g. 0.968), `[KITTY_CANDIDATE_TRANSPORT] sent=true authorization=disabled`; that proves server-side sending, NOT S3 archival of `voice_probable`.
- **Previous live-sync build** produced 97 cumulative `mic_drops` in a test, with 2 completed and 4 failed snapshots in the captured log. **Audio-protected build** reduced the observed cumulative `mic_drops` to 22 in a different call, but had 0 finalized / 2 failed snapshots during that log. The tests are not controlled or normalized; do not claim a reliable percentage improvement.
- Most recent attached test log included two S3 boots (reset reasons 11 and 1), C5 v38, and then a call with `mic_drops` rising from 0 to 22 while Kitty spoke; `dropped_ms=0`. Failures `stage=1 file=4 http=200` around `conversations.tsv`, with `bytes=10752` and `completed=0 failures=2` after that boot. One earlier upload success occurred before a boot in the same log. Do not assert the S3 reset cause or the exact SD failure cause.
- The live-sync regression test `python3 -m unittest discover -s server -p 'test_kitty_live_sync_contract_v6.py' -v` was **run by user from clean worktree at `ce902006` and passed 2 tests**. These are static source tests; **not hardware compilation or a continuous-load validation**.
- GitHub remote branch source was re-read through the GitHub connector during handoff. It includes `setSpeechActive`, `pauseForSpeech()`, 750 ms pacing during a call and 15 s retry; source `BrainRealtimeDirect.h` still uses **one pending speaker item and 1100 ms timeout**. No queued speaker-result fix committed yet.

## Relevant deployment and local paths
- Ubuntu user/server: `ryushi@ai-server`; LAN IP `10.5.5.245`; checkout `~/kitty-v6-validation` is locally divergent, **do not pull fast-forward into it**.
- Clean build worktree: `~/kitty-v6/private/kitty-sync-deployment/live-sync-build`. User fetched and switched this worktree to remote `ce902006` and ran passing contract tests.
- Private header **never commit or log contents**: `~/kitty-v6/private/kitty-sync-deployment/KittySyncPrivateConfig.h` (`KITTY_SYNC_V6_URL`, device token, CA PEM). Build script deliberately strips it from release; restore only to the PRIVATE exported Mac Arduino sketch after a build.
- Output example: `~/kitty-v6/private/kitty-sync-deployment/release-audio-protected/CuteDisplayBrain/CuteDisplayBrain.ino`. Verify exact directory exists; **do not assume flash happened based on test output**. User later sent logs consistent with the audio-protection version; formal firmware build identity isn't shown in boot version string, so treat deployed-code lineage carefully.
- HTTPS ingress `https://ragnarok-project.com/kitty-v6/sync`; Ubuntu `kitty-memory-v6.service` port 8766, `kitty-sync-gateway-v6.service` TLS port 8843, private snapshot root `~/kitty-v6/private/snapshots`. Open WebUI container `open-webui`.
- Current `memory sync status` shows `[MEMSYNC]` with `completed/failures` and `[MEMSYNC DIAG]` with `eligible`, `realtime`, `audio`, `ai`, `stt`, `tts`, `ota`, `stage`, `file`, `http`, cumulative `bytes`.
- `KittyMemorySyncV6.h` source: separate low-priority worker, SD reads via `KittyMemory::requestExport/takeExport`, CA-validated TLS, SHA256 manifest, 8 files: `facts.tsv`, `factsmeta.tsv`, `dated_plans.tsv`, `summaries.tsv`, `conversations.tsv`, `turn_sources.tsv`, `voice_profiles_v6.json`, `speaker_claims_v6.tsv`. 0-based file 4 = conversations, 5 = turn_sources, 7 = speaker_claims. Failed in-flight snapshots can remain in staging. Never mistake staging for finalized.
- `BrainRealtimeDirect.h`: `pendingSpeakerItem`, `pendingSpeakerTranscript`, `pendingSpeakerAt`, `flushPendingSpeaker` 1100ms, per-item `kitty.speaker.result`. `explicit_introduction` is a self-declared identity, not an authenticated owner. Candidate-only `voice_probable` must not unlock protected memory.
- Ubuntu observer `server/kitty_realtime_gateway_observer_v6.py` sends `candidate_speaker_id` and `candidate_provenance=voice_probable` alongside unknown authorization. Provider audio changes are risky.

## Work to continue (do not claim done)
1. **Audio-first live sync:** investigate source of microphone drops with objective metrics; avoid running HTTPS/SD reads in audio tasks and avoid busy repeated snapshot retries. Existing audio-protection pauses *between* uploads while thinking/speaking and paces chunks at 750ms during calls; already in remote source. Determine whether active HTTP requests overlap speech and whether memory/heap contention drives mic drops. Further fixes should be minimal and testable.
2. **Snapshot consistency/progress:** frequent conversation archive writes abort uploads (observed stage=1 file=4 or 5, HTTP 200). Need stable snapshot/export approach or resumable incremental sync with revision/version boundaries, not just repeatedly restart from byte 0. Preserve SD as authority, finalize SHA256-verified complete manifests only, never expose credentials or memory in logs.
3. **Per-turn speaker-result matching:** replace one 1100ms pending slot with bounded multi-item pending turns and safe id-keyed delayed results, with independent expiry and no realtime audio blocking. Instrument safe counts/match/timeout; implement regression tests covering late and out-of-order results, call reset, queue overflow, unknown fallback, and no candidate elevation. Do not retroactively rewrite archived unknown turns without separate verified design.
4. **Name awareness:** public profile is stored and patch is present; instrument/verify outgoing initial provider instructions using only safe metadata or unit tests (never log full prompts/credentials). The assistant may know the *primary user's public name* Shana without asserting live speaker identity; no private recall from this.
5. **Semantic refresh and conversational recall:** validate latest snapshot ingestion, attribution, indexing, scoped retrieval, authorized memory use, cross-call remembered facts, and multi-speaker isolation. `profile_facts=0` and `unverified turn archived; owner fact writes skipped` indicate owner fact persistence is **not** solved. Do not disable auth gate to make test pass.
6. Build/test from clean worktree. Static tests do not substitute for Arduino compile and hardware test. Preserve C5 v38. Prefer one combined flash after changes are tested.

## Commands for the next chat
```bash
cd ~/kitty-v6/private/kitty-sync-deployment/live-sync-build
git fetch origin feature/kitty-semantic-v6-cpu
git switch --detach origin/feature/kitty-semantic-v6-cpu
python3 -m unittest discover -s server -p 'test_kitty_live_sync_contract_v6.py' -v
# Before building confirm private header exists without displaying its contents.
test -s ~/kitty-v6/private/kitty-sync-deployment/KittySyncPrivateConfig.h
```
Build with `KITTY_SYNC_PRIVATE_HEADER` and a NEW `KITTY_RELEASE_OUT`, run `bash tools/build_s3_with_c5_update.sh`, restore private header with `install -m 600` into local release `CuteDisplayBrain`, securely scp privately to Mac and **flash S3 only** after successful Arduino verify. Never commit private header or reveal token.

## New chat starting instruction
> Continue Kitty V6 on GitHub `ryushi01/CuteDisplay` branch `feature/kitty-semantic-v6-cpu`. Read `docs/KITTY_V6_HANDOFF_2026-11-01.md`. Preserve current voice, full-screen Kitty face, C5 v38, and TLS/private memory. User wants minimal command/test loops and responsive live conversations. Latest tests show 22 mic drops in a call and incomplete sync while archive is written. Fix consistent audio-first live sync and delayed per-turn probable-speaker attribution safely; then validate persisted semantic recall. Update GitHub and tests; distinguish code-only checks from real hardware validation.

## Continuation update — 2026-11-01 (speaker queue source patch)

Commits on this branch:
- `a9e108ecada4e9de93e36a690e65585c43f71e74` — replace the single 1100 ms speaker pending slot with six item-ID-keyed pending turns and a five-second independent expiry. Late/out-of-order results can match their original turn rather than being forcibly flushed when a new transcript arrives. Expired and overflowed turns are archived as unknown/unverified unless the **same turn** contains a self-introduction claim. The code clears pending turns on stop, local failure and WebSocket disconnect; no firmware flash was performed.
- `3d315f9c1721703a88175370189a2fb04c1d5865` — add `server/test_kitty_speaker_queue_contract_v6.py` with static safety and queue-contract checks.

**Verification scope:** the updated GitHub source and test file were re-fetched successfully and checked against nine source invariants. No local Arduino toolchain or live Ubuntu container was accessible from this chat, so the new Python tests and Arduino compile have **not** been executed. The pre-existing two passing live-sync tests apply to the *previous* baseline, not these commits. No C5 change, no private config change, no Open WebUI protocol/session-update change. This is a source-only patch pending compilation and one combined real-world test.

**Still open:** sync export file 4/5 failures during writes, in-call mic drops, provider receipt of public profile, complete semantic ingestion and private authorized recall. Do not claim resolved. Do not merge until compile/hardware validation and memory isolation review.

One compact validation pass before deciding on a single S3-only flash:
```bash
cd ~/kitty-v6/private/kitty-sync-deployment/live-sync-build
git fetch origin feature/kitty-semantic-v6-cpu
git switch --detach origin/feature/kitty-semantic-v6-cpu
python3 -m unittest discover -s server -p 'test_kitty_*contract_v6.py' -v
test -s ~/kitty-v6/private/kitty-sync-deployment/KittySyncPrivateConfig.h
```
Do not print the private header or include it in a commit. Build from this clean worktree and verify the S3 sketch before the single flash. C5 stays v38.

## Continuation — sync write-churn mitigation (2026-11-01)

Previous Ubuntu validation at `b1c3de97` passed **16/16 static contract tests**, not an Arduino build.

New S3-only source changes:
- `0e05f5f`: wait for a 3-second quiet archive revision window before starting snapshot upload. Check the saved/fact/summary revisions before each file and chunk; fail with stage=4 before more network traffic if the archive changes. Never finalize a mixed-revision manifest; SD remains authoritative. This is a mitigation, **not** a frozen SD snapshot or resumable upload.
- `e5e250c` and `457253e`: count HTTPS POSTs made during a call, requests overlapping speech, maximum POST duration, and revision-change aborts in privacy-safe `[MEMSYNC]` logs. These counts do **not** directly measure mic drops or prove causality.
- `420e880`: add static regression for early abort, quiet-window, TLS, and diagnostics. New baseline has **17 contract tests expected** (previously 16); not executed on Ubuntu yet.

**Unresolved:** continuous conversation writes can still starve full-snapshot completion; true consistency will ultimately require immutable on-SD export versions or a server-verified incremental protocol. Mic-drop root cause unproven. Do not weaken owner memory authentication, change realtime provider events, modify C5 v38, or flash S3 until after Arduino verification. Preserve private header outside GitHub.

One combined next Ubuntu check:
```bash
cd ~/kitty-v6/private/kitty-sync-deployment/live-sync-build
git fetch origin feature/kitty-semantic-v6-cpu
git switch --detach origin/feature/kitty-semantic-v6-cpu
python3 -m unittest discover -s server -p 'test_kitty_*contract_v6.py' -v
test -s ~/kitty-v6/private/kitty-sync-deployment/KittySyncPrivateConfig.h
```
Run build script from this clean worktree using private environment variables as described earlier in this handoff. Arduino verify S3; one S3 flash only if build succeeds. Collect one synchronized call with `[CALL AUDIO DIAG]` and `[MEMSYNC]` counters. Avoid repeated long tests.


### 2026-11-01: Fixed-boundary live SD sync candidate (not yet hardware-validated)
- Branch commit 569a0f7: the SD owner captures all eight export file lengths in one task pass. The network uploader transfers only the captured byte prefixes, so append-only conversation turns can accumulate while a snapshot is in flight.
- Changing fact/summary revisions still aborts the export rather than finalizing a potentially mixed rewrite. Existing SHA-256 manifest verification, TLS, bearer-token separation, speaker authorization guard, speaker/microphone audio and C5 v38 remain untouched.
- This is a candidate requiring the Ubuntu Python contract suite and Arduino S3 compile before upload; do not report hardware success from static checks alone. No server redeploy is required for the fixed-boundary protocol; the deployed 8s gateway and 12s S3 timeout baseline remains in place.
- The latest pre-change hardware run successfully finalized a snapshot after the realtime call, with 0 mic drops, 0 speaker dropped ms, and 0 observed HTTP 502; active-call archive changes still caused stage=4/1 interruptions.


### 2026-11-01: semantic-refresh rollout pending
- Latest source commit 147d75d: opt-in memory-service automatic semantic index refresh is debounced by 90 seconds across bursty finalized SD snapshots, and queues a startup refresh to index existing snapshots. Queue is bounded and HTTP uploads never wait on embedding. Contract test added. Not yet deployed or runtime-tested.
- Ubuntu observation: 160 finalized snapshots with eight files each, a semantic SQLite index with 49 indexed/attributed rows and active generation 1; `KITTY_SEMANTIC_AUTO_REFRESH` was false. Existing index freshness and cross-call recall unverified. Protect private data; never print env secrets or conversation contents.
- User clarified a single person's voice can vary across a long conversation: future speaker-continuity logic may retain a probable candidate through isolated low-confidence turns, but must never convert that into verified owner authentication or retroactively rewrite unknown transcripts.
- Latest frozen-boundary S3 firmware: two finalized snapshots, no sync failures and no dropped audio in test. User manually ended call; do not investigate UART ACK noise or change audio. Preserve C5 v38.


### 2026-11-01: SD-first memory authority and validated semantic index
- User explicitly requires Kitty memories to persist on the S3 brain's microSD, independently of Ubuntu. SD is the permanent source for facts, conversations, summaries and speaker attribution; Ubuntu holds authenticated snapshot copies and a **rebuildable, read-only derived semantic index**, not a write-back memory authority. Do not replace SD with Ubuntu or automatically delete SD memories after successful uploads.
- Ubuntu observed: automatic refresh enabled, semantic index advanced 49 -> 220 rows and active generation 1 -> 2; successful log `Kitty semantic index refreshed: 220`. This validates indexing but NOT that the realtime assistant retrieves memories across sessions.
- Regression contract `server/test_kitty_sd_memory_authority_contract_v6.py` guards source boundaries (static, requires Ubuntu test run). No S3 or C5 changes.
- Speaker continuity: vary-match samples of the same person may be lower confidence; preserve a *probable* session candidate across isolated low scores, but do not escalate to authenticated owner, rewrite historical unknown turns, or expose protected facts. Current count: 193 unknown/unverified, 24 person:shana/voice_probable, 3 person:shana/explicit_introduction.
- IMPORTANT LIMITATION: offline SD persistence works, but semantic embedding search still requires Ubuntu; true offline semantic recall would be a separate feature and must not compromise live audio.
