# Kitty V6 — SD synchronization + semantic-recall integration (2026-10-30)

## Scope/status
**Implemented and committed in the V6 feature branch, not deployed.** Live S3 firmware, Mac Ollama/TTS, and Ubuntu Open WebUI remain unchanged. This is a staged implementation, not a claim of completed production integration.

## New code
- `server/kitty_sd_snapshot_v6.py`: strictly allowlisted SD-memory filenames, resumable sequential byte chunks, replay verification, per-file SHA-256 finalization, atomic snapshot directory publish. Complete exports include deletions by rebuilding the derived index from a full snapshot; never mutate S3 microSD.
- `server/kitty_memory_service.py`: opt-in `POST /snapshot/chunk` and `POST /snapshot/finalize` behind the existing `KITTY_MEMORY_TOKEN` authorization. Disabled unless `KITTY_SD_SNAPSHOT_ROOT` is configured. JSON chunk payload: `{"snapshot":"some_safe_id","name":"facts.tsv","offset":0,"data":"<base64 up to 8192 bytes>"}`. Reply `next_offset`. Finalize JSON: `{"snapshot":"same_id","manifest":{"facts.tsv":{"size":N,"sha256":"64 hexadecimal chars"},...}}`. A snapshot is a private cache copy, never the permanent memory authority. Use TLS, private networking and a dedicated token; no public exposure.
- `server/kitty_semantic_bridge_v6.py`: an **opt-in integration helper** that performs a semantic request on an asyncio worker thread with a default 180 ms wall-clock budget (max 500 ms), merges small source-marked results with existing local memory context, and returns local context unchanged on any failure/timeout. No GPU required. This does NOT yet patch/restart the running Open WebUI realtime route.
- `server/test_kitty_sync_bridge_v6.py`: isolated tests for replay, checksums, invalid paths, speaker provenance and timeout fallback.

## Identity trust model
A bearer-authenticated S3 device is *a device*, not biometric proof of the current human. Existing realtime microphone audio may belong to owner, guest or a different AI. Before owner facts can be updated, we require a trusted verified speaker session with explicit authorization, distinct from self-introduction in speech. Current firmware still uses legacy owner-centric extraction; **do not treat new attribution sidecar as evidence that legacy fact misattribution is fixed in production**. Recorded source remains unknown unless explicitly attributed by a trusted upstream protocol.

## Not yet wired; required before live release
1. Implement S3 low-priority SD-worker export queue plus authenticated HTTPS client, incremental resumability and checkpoint recovery (current server receiver already accepts resumable chunks, but **no live S3 uploader exists**).
2. Add trusted identity event/path from authenticated iOS session and unverified/claimed speaker transitions; prevent legacy owner-fact writes from unverified speakers **without losing existing validated name recall**.
3. Build an independent Ubuntu indexing scheduler on *finalized* snapshots, with CPU/RAM limits and bounded iSCSI I/O. Test EN/FR/JA cross-language retrieval and corrected/deleted fact propagation.
4. Call `bounded_semantic_context()` from a version-compatible Open WebUI realtime gateway injection point **before** response generation, not in the I2S callback; preserve existing model prompt, tool calls, memory refresh, and audible first-token behavior. Existing gateway uses provider-specific events, so patch requires staged compatibility validation; the helper alone does not change answers.
5. Set explicit payload limits/rate limits, secure file permissions, disk quota, retention/cleanup of stale snapshot folders, and auth before exposing upload routes beyond loopback. Do not publish personal microSD archives.
6. Run offline tests, combined S3+C5 CI, and real device/server hardware integration tests; verify failures and rollbacks. Never erase SD or recreate current Open WebUI volumes.

## Suggested isolated Ubuntu checkout verification
```bash
python3 -m venv ~/kitty-v6-venv
~/kitty-v6-venv/bin/pip install 'numpy>=1.26,<3'
~/kitty-v6-venv/bin/python -m unittest discover -s server -p 'test_kitty_*v6.py' -v
```
The identity and network tests do **not** need downloaded embedding weights. Realtime quality and memory correctness still require real-world testing.

## Safeguards
- CPU embedding model is warm, but processing can consume CPU/RAM and use disk (SQLite/model downloads); iSCSI storage is appropriate for a rebuildable derived index with normal filesystem semantics.
- S3 microSD is the canonical durable memory store, no primary personal-memory database on Ubuntu.
- Mac stays on qwen3.5:9b with the validated 16K Open WebUI context; no TTS or model changes.
- All new network features should be feature-flagged off by default and fail open into the **existing local memory path**, never stall the audio pipeline.
