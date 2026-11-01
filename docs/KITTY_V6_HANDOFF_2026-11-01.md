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
