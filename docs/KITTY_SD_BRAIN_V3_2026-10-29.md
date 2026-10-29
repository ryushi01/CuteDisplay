# Kitty SD Brain v3 — 2026-10-29

This experiment builds on `feature/kitty-temporal-awareness`. Recovery branch: `checkpoint/2026-10-29-temporal-v1`. Validated production `main` is untouched.

## Durable SD-first storage
- `/kitty/conversations.tsv`: complete archived text exchanges, with UTC epoch timestamp.
- `/kitty/memory.idx`: bounded PSRAM-loaded search index, with full index file on SD.
- `/kitty/facts.tsv` and `facts.bak`: current structured facts with recoverable swap, unchanged two-column schema for older firmware.
- `/kitty/factsmeta.tsv` with backup: fact update timestamps, confidence and expiration metadata.
- `/kitty/corrections.tsv`: append-only explicit weekday-work corrections.
- `/kitty/summaries.tsv`: append-only successful idle conversation summaries.
- **New:** `/kitty/dated_plans.tsv`: append-only dated plan history, including date and unique per-subject key, to preserve prior plans even if the 256-fact working cache rotates.
- All SD card writes remain owned by low-priority Core 0 worker. WebSocket/audio callback code never performs SD I/O. No formatting or destructive migration.

## Improved calendar interpretation
- SNTP-valid S3 local date and timezone is sent with AI and realtime context. No invented date when SNTP is not synchronized.
- Recognizes today, tomorrow, day after tomorrow, yesterday, day before yesterday in English, French and Japanese; ISO `YYYY-MM-DD`; weekday references including `next Monday`, `lundi prochain`, `来週の月曜` when a future-plan statement is extracted.
- Invalid ISO dates are rejected rather than normalized. Dates across DST boundaries use local calendar arithmetic.
- Multiple plans on the same date have distinct hash-suffixed keys. A rephrasing that produces a distinct canonical value may still be treated as a separate plan.
- An old plan stays historical with **outcome unconfirmed**. Neither a passed date nor silence confirms completion.

## Limits
- The full SD conversation/archive/history is not loaded into the realtime model. Compact RAM/PSRAM caches and bounded summaries are injected. Historical `dated_plans.tsv` is durable but does not yet have a full random-access date index or backfill into the 256-slot cache, so recalling very old plans may require later SD indexing work.
- This is a deterministic EN/FR/JA date-phrase parser, not a comprehensive calendar grammar. It does not reliably extract all spoken plans, dates, corrections, negated dates or non-English/Japanese/French expressions.
- `facts.tsv` remains limited to 256 current cached facts; the append-only dated-plan archive enables long-term persistence but **does not** make every historical entry immediately searchable.
- Memory refresh during live calls requires the separate guarded Open WebUI gateway extension from Memory v2 to be deployed and tested on the user's actual server.
- Server and Mac are not changed by GitHub commits.

## Acceptance
1. GitHub Actions combined S3/C5 compile must succeed at final branch commit.
2. Verify prior SD facts, snapshots, metadata and summaries remain readable.
3. Tell Kitty two different activities for the same day; ensure two distinct dated_plan keys and separate `dated_plans.tsv` rows.
4. Reboot, ask about tomorrow and the next day; check local-date/weekday response and that no past plan is described as confirmed completed.
5. Try EN, FR, JA relative and weekday dates, one invalid ISO date, and a DST boundary timezone. Compare timezone configured on S3.
6. Run `system status` during realtime audio and check SD write failures, RAM headroom and audio buffer drops. Do not promote until hardware verified.

No SD formatting is required for this update.
