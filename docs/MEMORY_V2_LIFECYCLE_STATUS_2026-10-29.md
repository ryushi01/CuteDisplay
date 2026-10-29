# Memory v2 lifecycle prototype — 2026-10-29

## Rollback
Parent: `main` commit `5458dd4d3f0e6a9744729ff1312e72898cf85b3d`.
Checkpoint: `checkpoint/2026-10-29-main-before-memory-v2`.

## Implemented in this iteration
- Added PSRAM-resident timestamp and expiry metadata arrays for 256 cached facts.
- Fact insertion and changed-value updates record a timestamp; fact-summary retrieval can exclude expired entries.
- Existing fact snapshots remain backward-compatible, because the TSV schema was not modified.
- Combined S3+C5 CI enabled for this branch.

## Not yet implemented / requires follow-up
- Persistence and restoration of lifecycle metadata: timestamps are presently volatile; expiry values are not yet assigned by temporary-event classification.
- Language-aware contradiction extraction and explicit supersession history.
- Conversation summaries with durable SD persistence and background inference.
- Live memory refresh via realtime gateway: current gateway accepts `kitty_sd_memory` only in the initial authenticated WebSocket message. Do not send a speculative refresh event until the corresponding server handler is implemented and authenticated. Existing voice behavior is unchanged.

## Validation
Do not promote to main based only on this prototype. Confirm workflow compilation, then add metadata persistence, contradiction tests, and server protocol compatibility. Existing deployed firmware is the recovery baseline.
