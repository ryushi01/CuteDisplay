# Kitty Memory v2 experimental implementation — 2026-10-29

## Safety and checkpoints
- Production baseline: main commit `5458dd4d3f0e6a9744729ff1312e72898cf85b3d`.
- Rollback: `checkpoint/2026-10-29-main-before-memory-v2`.
- Feature: `feature/memory-v2-lifecycle`. Do not merge until the final combined firmware CI and real S3 regression tests succeed.
- Existing `/kitty/facts.tsv` retains its **two-column** legacy format. Added metadata is stored separately in `/kitty/factsmeta.tsv`, with temporary/backup rename recovery. No SD format is required.

## Implemented
- Fact timestamps and confidence in a fixed, PSRAM-backed sidecar. Direct facts use confidence 100 and AI-suggested facts 70; these are heuristic source grades, not calibrated probabilities.
- Explicit English/French/Japanese weekday-work assertions use stable keys such as `routine_work_monday`. A later correction replaces the current value; old versions go to `/kitty/corrections.tsv`.
- Stable facts have no expiry. Only explicitly time-qualified upcoming plans for today/tomorrow receive a bounded 24–48-hour expiry. Historical archive data remains on SD, and old schedule matches are downranked/excluded from upcoming recall.
- Every six saved user utterances, the SD worker queues a bounded, user-only batch. The existing low-priority analysis worker may summarize it after 20 seconds idle. Accepted summaries are appended to `/kitty/summaries.tsv`; only a recent bounded summary is sent as memory context on subsequent AI requests or new realtime connections. No inference occurs on I2S or WebSocket callbacks.

## Known limitations and incomplete features
- General contradiction resolution (arbitrary topics, sophisticated date schedules, indirect negation) is **not** complete. The explicit workday example and previously supported same-key facts are handled.
- Time-specific expiry currently handles basic today/tomorrow phrases in EN/FR/JA; other future dates remain until corrected. Do not present this as a full calendar or natural-language date resolver.
- Summaries are asynchronous and best-effort; model timeout/idle requirements may skip them. They are not automatically injected mid-call.
- **In-session realtime provider memory refresh is not yet implemented.** The existing server-side gateway only accepts `kitty_sd_memory` during WebSocket authentication. A version-checked authenticated update event, server acknowledgment, and live provider prompt update must be implemented and verified together on the actual Open WebUI image. Do not send a speculative update event or restart calls. Delegated S3 AI requests already assemble fresh memory on each request.
- No changes have been deployed to Ubuntu, Mac, or iPhone.

## Required validation before promoting
1. Combined CI S3/C5 compilation from the exact latest commit.
2. Existing SD card loads legacy facts unchanged; `factsmeta.tsv` is created after new writes; reboot persists timestamp/expiry/confidence.
3. Try: `I work on Mondays`; `Actually I no longer work on Mondays`; then reboot and ask in Japanese/French. Verify corrections.tsv contains prior value.
4. Test today's/tomorrow's plan expiry with a clock that has synchronized; old user memories remain in archive, but not active future plans.
5. Say six meaningful project decisions. After idle, verify summaries.tsv and new-session recall. Confirm no audio dropout, memory pressure, or extra latency.
6. `system status` throughout realtime calls; keep validated main if any regressions.
