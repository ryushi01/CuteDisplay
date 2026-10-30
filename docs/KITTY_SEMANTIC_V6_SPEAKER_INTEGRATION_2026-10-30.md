# Kitty Semantic V6 — speaker-aware SD integration checkpoint (2026-10-30)

**Status:** code committed on `feature/kitty-semantic-v6-cpu`; **not deployed** to running ESP32-S3, Open WebUI container or MS-01. Stable `main` unchanged. CI workflow added; check its latest run before declaring tests passed.

## Implemented in source
1. **ESP32-S3 archive:** `KittyMemory.h` continues writing `/kitty/conversations.tsv` in its original `timestamp<TAB>question<TAB>answer` format. After a successful append, the low-priority SD worker *also* writes `/kitty/turn_sources.tsv`, keyed by `timestamp<TAB>archive_byte_offset`, with `unknown<TAB>unknown<TAB>unverified`. This preserves backwards compatibility; missing/failed sidecar writes never block realtime audio or archive persistence.
2. **Ubuntu attribution reader:** `server/kitty_semantic_attribution_v6.py` joins archived turns with the sidecar using exact byte offsets. Older records and missing sidecar rows are *unknown*; they are **not automatically attributed to Shana**. Unauthenticated owner claims in an exported sidecar are not considered proof of verified owner identity.
3. **Semantic index:** the CPU-only indexer stores binary float32 vectors and separately stores speaker metadata by record and active generation. A query may optionally filter by `speaker_id`. A generation-safe composite primary key protects the active index while another generation is being rebuilt.
4. **Optional memory API:** the already-existing authenticated `/semantic` endpoint accepts optional JSON `speaker_id`, returning source metadata alongside semantic results. It is not wired into live Kitty realtime replies.
5. **Tests:** regression cases cover ChatGPT vs owner identity, missing legacy speaker, owner-memory write protection primitives, revised/removed memories and generation reuse. GitHub Actions offline tests install only NumPy; real embeddings and device hardware are not tested by the workflow.

## Why this first stage is deliberately conservative
- **A microphone recording does not identify the human or AI speaking.** Actual S3 production metadata starts as unknown. The unit-test example with claimed `remote_ai:chatgpt` is a *synthetic fixture* demonstrating index and filter behavior, not a deployed speaker-recognition feature.
- Do not write guesses about guest statements to the owner's verified profile. Existing legacy fact extraction still needs integration with an authenticated speaker-session source before it can enforce this end to end; do not claim protection is deployed.
- Existing timestamps, SD data, working dates, AI persona, voice, and realtime audio behavior remain unchanged.
- The server index contains sensitive personal transcript text and needs access control, encrypted storage or filesystem protection appropriate to the deployment; it is rebuildable from microSD.
- In the current staged code the memory service embeds and searches synchronously, which may be CPU-intensive. **Do not connect directly to realtime audio** until a bounded asynchronous retrieval path and benchmarked timeout/fallback are implemented.

## Still required before rollout
- Trustworthy speaker-session and explicit claimed-identity events, with clear distinction between speaker and person discussed. Source must originate in a verified app/session channel, not only untrusted transcript text.
- Integrate speaker/source metadata into S3 fact extraction and correction handling safely; do not break existing name recall.
- Add incremental authenticated SD export with checksums, proper deletion/correction replay and backpressure. No automatic export exists now.
- Add a bounded, non-blocking retrieval bridge from MS-01 to realtime Kitty with S3 local fallback and no added microphone/speaker queue latency.
- Run GitHub CI, device compile, firmware on-device retention/reboot testing, and end-to-end EN/FR/JA ChatGPT-vs-Shana attribution before promotion to `main`.

## Validation examples
A known separate ChatGPT participant must remain distinct from Shana. The question “Who created you?” refers to Shana (subject), but “Who is talking now?” must be unknown until trustworthy or explicitly *claimed* identity information is available. A guest preference must not overwrite the owner's. Old SD conversations must remain retrievable even without a sidecar.
