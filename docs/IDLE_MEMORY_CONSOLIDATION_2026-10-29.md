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
