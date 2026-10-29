> **October 29 update:** See [current validated system checkpoint](VALIDATED_SYSTEM_CHECKPOINT_2026-10-29.md) for the latest v35 notification, cross-topic consolidation, performance bounds, hardware verification status, and limitations. Sections below retain the v1 design history.

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

## Realtime transcript / structured fact repair
- Realtime voice input is queued from `conversation.item.input_audio_transcription.completed` even if the audio item ID is missing. Serial prints `[MEMORY] Realtime user transcript received` and `[MEMORY] transcript queued=1`.
- The SD-only `/kitty/facts.tsv` file holds simple updated key/value facts extracted from explicit statements, initially names and likes. This is deterministic extraction, not an unrestricted model memory agent.
- `memory status` shows `profile_facts` and the current keys, in addition to mount/index counters.
- `memory probe` queues a harmless diagnostic record, separating SD write faults from voice-transcript delivery faults.
- On connection, the S3 includes a bounded memory profile in authenticated realtime session context. The matching custom Open WebUI realtime patch must be redeployed for this to influence direct realtime speech.
- The profile is only transmitted as temporary model context. No long-term memory is stored in Open WebUI or on the Mac.
- If `memory probe` increases saved/indexed but speaking does not, inspect the transcription event path, not the SD filesystem.

## SD information card and episodic memories (C5 v34)
- C5 right-button short press retains the existing battery, Wi-Fi, Bluetooth and IP readout and adds SD usage: approximate fill percent, used MB/KB and card capacity MB/KB.
- The Brain samples SD_MMC size and used bytes on the low-priority SD worker every ~30 seconds or following writes; sends cached KB via SD_USAGE UART roughly every 15 seconds. C5 does **not** read the card directly.
- The information card is also available during fullscreen realtime calls.
- Long-term event extraction captures simple explicit future plans, dates, purchases, projects, past events and requests to remember (not restricted to food). For example, "the day after tomorrow I will eat Belgian moules" remains an episodic note rather than attempting to classify the dish into a food preference.
- Most important: event extraction is currently pattern based. This does not equal full open-ended, reasoning-driven memory; ambiguous paraphrases may still be missed.
- Structured facts are persisted in full in /kitty/facts.tsv. AI receives only a bounded contextual slice.

## Bounded, cross-topic memory capture
- Explicit "remember this" commands and personal declarative statements may become short stored notes regardless of food, travel, work or other categories. The rule is intentionally conservative about routine questions and greetings.
- Single note text is truncated safely to at most 112 UTF-8 bytes; long prose is not added to the realtime model context.
- The indexed conversation archive remains on the S3 microSD. A fixed 24-entry in-RAM fact/note cache feeds an at-most-700-byte summary for realtime calls; only a bounded excerpt is sent over the WebSocket, so model prompt size does not grow with historical archive size.
- The separate historical search remains capped at 40 ms and three selected archive matches with an at-most-850-byte context budget.
- This heuristic capture is **not** equivalent to true semantic extraction or consolidation. It can save incomplete, redundant or irrelevant notes and does not yet guarantee robust correction/merging across arbitrary topics. Please test before trusting it as a complete memory system.

## Memory consolidation v2
- Durable name, home, and work slots update on explicit correction.
- English 'my SUBJECT is VALUE' uses a normalized subject-specific slot; a later value replaces the previous one.
- Multiple preference subjects coexist. Exact normalized 'like / dislike' corrections supersede the earlier preference for that subject.
- Identical recent notes are deduplicated in the 24-slot RAM cache, and brief episodic notes rotate; original conversation history remains on SD.
- Each new note is at most 112 UTF-8 bytes, realtime fact summary at most 700 bytes; relevant historical search remains capped at 40 ms. Stable facts have priority over newest notes.
- LIMITATION: rule-based matching is not true semantic similarity. Paraphrases, implicit corrections, and references to the same subject under different names may not consolidate. No persistent server storage is introduced.
