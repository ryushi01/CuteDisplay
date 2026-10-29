# Semantic SD memory and 256-fact catalog (experimental, 2026-10-29)

Base checkpoint: `checkpoint/2026-10-29-memory-psram` at `806c5df24008b341e6bce1689222dfa22ead86c9`. Validated `main` remains unchanged.

## Scope
- Replace the 24-entry internal RAM fact array with a fixed 256-entry PSRAM catalog (~56 KiB).
- Preserve on-card `/kitty/facts.tsv` with `facts.next` + `facts.bak` snapshot recovery. Restore the catalog from SD at boot. Never format SD automatically.
- Expand lexical intent into common language-neutral topics for Japanese, French, and English prompts. Retrieve topic-matched structured facts without reading SD on the audio thread, and expand indexed SD conversation search on the low-priority worker.
- Continue bounded AI prompt injection. Keep the existing Open WebUI realtime audio code unchanged. No new server dependencies.

## Important limits
- Retrieval uses multilingual topic aliases, not vector embeddings or a separate local LLM. It will not infer arbitrary semantic similarity, and uncommon terms may still miss.
- 256 is the current PSRAM cache and snapshot ceiling, not unbounded fact storage. At full capacity existing eviction logic remains.
- The realtime WebSocket gateway still receives a compact memory snapshot on connect; dynamic refresh within an active call is not implemented in this change.
- Loading facts requires PSRAM; on allocation failure the SD archive remains on card but structured fact cache is unavailable.
- The full catalog is *not* sent to models. Compact identity and context summaries plus relevant excerpts are sent.
- Hardware latency, recall accuracy, SD corruption resilience and CI compilation need verification before merging.

## Acceptance checklist
1. Compile combined S3/C5 firmware on this branch; do not overwrite the validated recovery firmware.
2. Start with existing SD card: confirm `memory status` includes existing facts, with no reformat.
3. Teach at least 30 distinct stable preferences and check facts survive reset. Do not assume all utterances are auto-extracted; use logs to verify.
4. Ask in English, Japanese, and French about known food preferences, identity and work; inspect `[AI MEMORY]` and realtime answers.
5. Run `system status` idle and during realtime audio; compare stack low water, internal RAM, speaker underruns and latency with the checkpoint.
6. If a problem occurs, flash the previous checkpoint firmware without erase-all-flash.
