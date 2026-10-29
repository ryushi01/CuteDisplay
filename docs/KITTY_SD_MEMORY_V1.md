# Kitty SD-only Memory v1 (S3)

## Source of truth and privacy
- Long-term conversations and their compact retrieval index live **only on the S3 microSD**:
  - `/kitty/conversations.tsv` (UTF-8, timestamp<TAB>user<TAB>assistant).
  - `/kitty/memory.idx` (fixed-width record offset + topical/term fingerprint).
- No database or persistent memory service is created on Open WebUI, the ai-server, or the Mac. Relevant excerpts still pass through the existing Open WebUI generation request in memory, as any normal prompt does.
- Existing four-turn/24-hour S3 Preferences context is left intact for backward compatibility; the new long-term archive is SD-only.
- Audio recordings are **not** written to SD.
- **The raw archive can contain sensitive user conversation data**. The card is not encrypted. Protect it and back it up.

## Memory search
- RAM-resident index of up to 150,000 recent archived exchanges (~2.4 MB of S3 PSRAM); the SD archive itself is never truncated.
- Search runs on a low-priority task, using topical synonyms and hashed character trigrams; three best matches become a bounded context excerpt (up to 850 bytes).
- Each AI request waits at most 40 ms for indexed recall. If the card is slow, the ongoing model request proceeds with the fast, recent cache.
- Query search is skipped when no matching topic is detected; relevant years-old information may therefore be missed.
- **This is approximate topical/lexical retrieval, not neural embedding semantic search.** No embedding model is installed or invoked. Conceptual paraphrases outside the configured topic synonyms may not match.
- Successful turns are queued and written asynchronously. Missing/broken cards never prevent normal conversation.
- If an index file is absent, the low-priority worker can rebuild it from the full conversation archive after mounting.

## Hardware
- S3 SD_MMC 1-bit: GPIO39 clock, GPIO38 command, GPIO40 D0. No new external wires.
- A FAT-formatted microSD card is required. The firmware does not format it, so existing files are not erased.
- Verify using Arduino Serial Monitor at 115200:
  - `[MEMORY] SD mounted: ...`
  - `[MEMORY] indexed=... entries`
  - USB command `memory status`.
- Only upload the S3 combined firmware. Keep `Erase All Flash` **disabled**. C5 is unaffected.

## Limits and next steps
- A years-deep archive is available, but only the latest 150,000 index records are directly searchable; older archived records remain available on the card for export/reindexing.
- Search quality is much lower than true neural embedding retrieval. For full semantic long-term recall, an asynchronous embedding pipeline and a vector index stored **on this same SD card** are needed. Embeddings could be computed transiently by a model while the system is idle; the computed vectors and metadata must be returned to S3 for storage, never retained on the server.
- No user-facing memory deletion/export controls are included yet. Until then, the card can be mounted on a computer for manual backup or removal.
- No promise of zero extra latency: the memory path is capped at 40 ms plus small prompt-processing overhead, and audio tasks are never made to wait on SD I/O.

## microSD initial setup and C5 notifications (C5 v33)
- On boot the S3 attempts a non-destructive 1-bit SD_MMC mount.
- When successful, C5 briefly shows **SD CARD READY**.
- When mount fails, C5 shows **SD CARD NOT READY**. The card may be unformatted, absent, damaged or incorrectly connected. The firmware cannot safely distinguish these conditions from a failed mount and **will not erase data automatically**.
- When the user has confirmed the card contains no data they wish to keep, Arduino Serial Monitor (115200 baud, line ending Newline) accepts the exact command:
  `memory format CONFIRM`
- The command is accepted only following an unsuccessful mount. The SD worker changes state to FORMATTING and the C5 shows **SD CARD FORMATTING / DO NOT REMOVE CARD**.
- The worker requests FAT formatting using Arduino-ESP32 SD_MMC's explicit format-on-failed-mount option. Success produces **SD CARD READY**; failure produces **SD CARD ERROR**. No live audio tasks wait for SD operations.
- **Formatting destroys card data.** If there is anything valuable on the card, back it up or repair it on a computer instead.
- Run `memory status` afterwards to check mount/index/save status.
