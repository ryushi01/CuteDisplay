# Idle-only Ollama memory consolidation (experimental, 2026-10-29)

## Purpose and guarantees
This feature extends S3 microSD-only memory without adding any Ollama inference to microphone capture, realtime Call Mode, live TTS, avatar expression rendering, or the regular chat generation path.

**Normal speaking/thinking latency:** The main AI request and the 40-ms maximum SD retrieval wait are unchanged. The memory network worker is separate and low priority, and **never starts while Call Mode, STT, chat inference, TTS, OTA, or audio testing are active**. It waits for 20 seconds of complete inactivity and spaces its own requests at least 10 seconds apart.

**Caveat:** All processes ultimately share the Mac's Ollama CPU and Open WebUI. If the user starts Call Mode during an idle memory request, the network callback aborts as soon as control returns to the HTTP client (network read timeout set to 1.6 s); the remote Ollama inference may not stop instantaneously. This reduces but does not mathematically guarantee zero contention. Device-level latency benchmarking remains required.

## Architecture
1. Existing `KittyMemory::queue()` captures voice transcript/normal chat. The original archive writer remains low-priority, CPU0, writing timestamped exchanges to `/kitty/conversations.tsv` and the compact index.
2. After a successful SD archive append, it offers an independent 256-byte sanitized utterance to an eight-slot nonblocking RAM queue. On overflow it drops the oldest unprocessed candidate, not the actual SD archive.
3. `BrainMemoryAI::tick()` stays idle throughout realtime and manual interactions. After 20s fully idle, it takes at most one candidate and starts a low-priority CPU0 HTTP client task. No background work occurs on audio, UART, or display callbacks.
4. The task reads the already-saved HTTPS Open WebUI URL/model/token from S3 Preferences. It asks the existing chat model for **JSON with no more than three concrete likes/dislikes**. It is not using any new cloud service; no API keys are stored in source.
5. A strict parser rejects malformed output, unsupported keys, more than 3 facts, and vague subjects such as `it`, `this`, `what I dislike`. The model task posts accepted proposals to a small second RAM queue; it never touches SD.
6. The original SD worker alone validates/merges these facts by normalized subject into `/kitty/facts.tsv`. Existing name, location, work and episodic extraction continue to work. Only a changed fact confirmed written to SD increments the C5 `FACT MEMORIZED` notification sequence.
7. A repeated identical fact does not update the revision or show a second notification.

## Intentionally limited first stage
- This version applies AI consolidation only to **explicit stable likes/dislikes**. Do not claim this version implements semantic resolution of jokes, arbitrary events, complex travel schedules, every language, or indirect cancellation. Existing heuristic extraction still handles names and many notes.
- Does not delete raw conversations, do long-running batch indexing, or migrate the microSD database.
- The old model/endpoint must support nonstreaming Open WebUI `/api/chat/completions`. If not, requests are skipped and the existing memory path remains operational.
- It is possible for some candidates to be skipped when the model is slow, the device is busy, or the 1.6 s read timeout expires. **We prefer missing an optional consolidation pass over a speech-latency regression.**
- The existing raw conversation archive is not encrypted. No permanent Open WebUI/Mac memory is added by this change; transient prompts and model processing on those hosts still occur.

## Build/deployment
- Branch: `feature/idle-ai-memory-consolidation`; do not merge until CI and at least one hardware latency acceptance session pass.
- GitHub Actions: `Build combined S3 + C5 firmware`, on the feature branch.
- Upload the S3 combined image with Arduino IDE and **Erase All Flash disabled**. C5 firmware version remains v35; no UI rebuild/OTA is needed if already v35.
- No Open WebUI server patch or new backend installation is required. Do not enable the legacy `server/kitty_memory_service.py` SQLite service; it would violate the SD-only storage goal.

## One simple acceptance session
1. With USB Serial at 115200, start a realtime Call Mode conversation. Ask Kitty a joke or other simple question; record realtime first-token and audio continuity. The new memory task must **not** log `[MEMORY AI]` while Call Mode is active.
2. Tell Kitty `I like chocolate and strawberries but I dislike olives`. End Call Mode and leave Kitty idle for >=20 seconds. If the chat model can respond within the strict timeout, the Serial log may display `[MEMORY AI] proposed=N (idle)` followed by `[MEMORY AI] consolidated likes/dislikes`. Otherwise existing deterministic extraction still applies.
3. Send `memory status`. Confirm meaningful, independent subjects; repeat a known fact and verify no second `FACT MEMORIZED` toast. Reboot S3, start a new call, and check recall.
4. If memory processing seems to affect voice, report the `[AI PERF]`, `[CALL AUDIO DIAG]` and `[MEMORY AI]` lines. Do not claim no-latency impact without comparing the same query before and after.

## Rollback
Reflash the last known good main-branch combined firmware with Erase All Flash disabled. SD archive and facts are unaffected. No server deployment or schema migration is required.

## 2026-10-29 — multilingual context and SD recovery update
- AI memory extraction accepts explicit English, French and Japanese user statements, and returns language-independent topic keys for `work_availability`, `upcoming_plan`, or `hobby`. Statements are stored under `context_work_availability`, `context_upcoming_plan`, etc., with brief descriptions. The current description is still limited by the model and 24-fact RAM cache; this is not a cross-language embedding search of the complete historical archive.
- This processing remains **idle only**, at least 20 seconds after interaction ends, with one small verified-TLS HTTPS request. The request uses the same ESP certificate authority bundle as normal BrainAI requests and aborts if Call Mode resumes. The short response timeout is deliberately conservative to favor responsiveness; slow CPU-only models may skip a background pass.
- Structured fact snapshot is now first written to `/kitty/facts.next` then renamed to `/kitty/facts.tsv`, retaining `/kitty/facts.bak`. On boot the SD worker tries the active snapshot and falls back to the backup. Conversation archive and index remain untouched. Recovery from a damaged SD filesystem is not guaranteed; no automatic formatting occurs.
- Before your next acceptance test, if you wish to **format the SD card**, first copy off any information you want to keep. Formatting **permanently erases existing conversation archive, facts, index, and saved personal preferences**. Use the USB Serial Monitor command `memory format CONFIRM` to format either a mounted or unmounted card; do not enable Arduino **Erase All Flash**. Record the old `memory status` first if you want a reference.
- Hardware acceptance: record time to first reply and audio drop counters before/after; tell Kitty in French `Je suis très occupé au travail, donc je ne peux pas prendre de vacances pour le moment.` Stop the call; leave the device fully idle at least 20 seconds; review `[MEMORY AI]` logs and `memory status`; restart Call Mode and ask in English what you said about work/holidays. Repeat with a plan correction. If the model takes longer than the configured timeout, extraction may be skipped without blocking conversation.

## Remote Open WebUI URL clarification
- The configured Open WebUI instance is reached over the public Internet at `https://ragnarok-project.com`, **not over a local HTTP LAN**. The background extractor must use the **saved** HTTPS URL, model, and API key from the device's existing `brain-ai` Preferences. Do not hardcode tokens or a separate endpoint.
- Require ESP32 certificate bundle verification (`esp_crt_bundle_attach`) for the memory HTTPS client. Plain `http://` is not supported by this feature. This ensures the API key and temporary conversation content are protected in transit.
- No persistent memory service or database is installed on that remote host. All durable facts and archive records remain on S3 microSD.

## Serial SD format (2026-10-29)
- With the S3 connected to Serial Monitor at **115200**, send exactly `memory format CONFIRM` with a newline. This destructive operation is explicitly opt-in and handled only by the SD worker.
- For mounted FAT cards, the SD worker uses FatFs `f_mkfs` to actually reformat the volume (not merely `format_if_mount_failed`, which would leave a healthy card unchanged). For unmounted cards, it attempts to initialize and format using the standard Arduino SD_MMC mount/format route.
- After success the SD archive index, recent RAM conversation snippets, structured facts, and queued pending memory operations are reset. **No automatic format on reboot.** Check `memory status` afterward; expected `mounted=1`, `indexed=0`, `profile_facts=0`.
- If the card is physically missing or damaged, the command cannot repair it. A format failure is logged and must not be interpreted as success.

## Low-latency memory while Call Mode stays connected
- Explicit English, French, and Japanese likes/dislikes are now extracted and persisted immediately by the existing low-priority SD worker, including Japanese subject prefixes such as `私は`. Neither a call disconnect nor a 20-second idle timer is required for these simple facts. Existing bounded archive queue and `FACT MEMORIZED` signal apply.
- **Important distinction:** the general-purpose background Ollama summarizer remains suspended whenever Call Mode is connected. Starting a second model inference while the user might resume talking could compete for the same remote model and delay voice responses. This change intentionally prioritizes live latency over deeper semantic consolidation.
- The realtime voice model receives its compact SD fact snapshot upon connection, not a live update after every newly stored fact. Newly saved facts are persistent across reboot and available at the **next** Call Mode connection; same-call recall still relies on the active conversation context. Full same-call semantic fact refresh would require explicit gateway/session support.
- Test: say `私はパスタが好きだよ` while connected; check `[MEMORY] saved fact` and `memory status` without ending Call Mode; restart the device and open a new Call Mode session, then ask in English what food you like. Verify actual behavior rather than assuming text normalization guarantees translation.

## Expanded live-call multilingual context capture
- The SD worker now captures explicit short **work constraints, upcoming plans, and hobbies** in English, French and Japanese with bounded rule matching; it preserves the original wording, including time qualifiers and negations. Canonical keys such as `context_work_availability` and `context_upcoming_plan` make these facts visible across languages in the next call's memory snapshot, without a second Ollama request during live audio.
- Example utterances: `I'm busy with work so I can't take holidays`; `Je suis très occupé au travail et je ne peux pas prendre de vacances`; `仕事が忙しいので休暇を取れない`; `Tonight I'm going to the gym`; `Ce soir je vais au cinéma`; `今夜は友達に会う予定`.
- **Limitations:** this is selective pattern matching, not complete multilingual semantic understanding. Complex wording not matching any supported phrase is preserved in conversation archives when captured, and deeper analysis remains deferred until Call Mode is off. We intentionally do not run competing model inference during a connected call to protect speech latency. Same-call session snapshot refresh is still unavailable.

## Root-cause fix for facts forgotten after reboot (2026-10-29)
- Fixed two independent firmware bugs found by source inspection after the user reported forgetting even the Japanese self-introduction: a literal `\\n` in an autogenerated C++ comment unintentionally commented out `mergeFact(key,value)` in the SD task, and `KittyMemory::queue()` pre-merged identity facts in RAM before the SD worker captured its revision baseline. The SD worker therefore saw no change and could skip writing `facts.tsv`. Both errors are removed.
- The SD worker now owns the entire merge -> revision detect -> verified snapshot save sequence. The queueing/audio callback does no SD file access or early structured fact modification. Japanese `私の名前はシャナです`, `私はシャナです`, and French `Je m'appelle Shana` are recognized, including normalizing the known Japanese transcription of Shana. Realtime call session still receives the fact snapshot only when a new session is connected.
- Minimal acceptance: with an initially formatted card, say `私の名前はシャナです`; verify the S3 log `[MEMORY] saved fact key=name` and `FACT MEMORIZED` before reboot; check `memory status` shows `name Shana`; reboot S3 and check `memory status` again **before** starting a new call; then ask `What's my name?`. If the fact persists but speech fails to recall it, investigate server-side injection of `kitty_sd_memory` separately. No SD reformat is necessary for the subsequent reboot test.

## Realtime multilingual TTS / S3 restart hardening
- TTS/stt language switching should remain supported; neither voice language nor stored memory facts are restricted to English, French, or Japanese at the transport level.
- Realtime WebSocket text events (including long base64-encoded assistant audio frames and multilingual transcripts) now use length-aware cJSON parsing directly from the bounded WebSocket payload. This avoids allocating and copying a second full-size JSON string in internal RAM for each audio frame, reducing heap pressure and fragmentation without adding extra inference or network latency.
- Startup prints `[S3 BOOT] reset_reason=...` and available/minimum internal heap plus PSRAM to distinguish an actual ESP32 reset from a WebSocket-only call disconnect. If the S3 resets, collect this line and any preceding Guru Meditation/backtrace, plus `[CALL]` lines; the cause is not confirmed without a real reset log.
- No changes to remote Open WebUI / Mac model or TTS services; no disabling multilingual recognition. Requires combined firmware build and on-device verification before promoting to main.

## Serial diagnostics for intermittent language / realtime resets
- Send `system status` (alias `diagnostics`) at 115200 baud at any time, including during a call. It prints current boot uptime and ESP reset reason, CPU frequency/core and loop-task stack high-water mark, number of RTOS tasks (not a fabricated CPU load percentage), internal heap and PSRAM available/minimum/largest blocks, SD usage, structured facts/archive index/write queues, memory-analysis task state, Wi-Fi connectivity, and realtime speaker/microphone buffer drop counters.
- Output is a **read-only snapshot**: no SD filesystem reads or formatting, model calls, I2S restarts or large diagnostics allocations. CPU usage percentage is not available from this lightweight sampling path; task count and stack/heap pressure are useful proxies but are not CPU utilization.
- For an apparent reboot during a foreign-language transcript or TTS change: capture the spontaneous Serial Monitor messages immediately before/after the reset, and run `system status` on restart. Compare `reset_reason`, minimum internal heap, largest contiguous block, and speaker/mic counters. A change of recognized language is not yet proven to be the cause.
