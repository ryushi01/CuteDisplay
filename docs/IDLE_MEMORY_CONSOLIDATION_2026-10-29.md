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
- Before your next acceptance test, if you wish to **format the SD card**, first copy off any information you want to keep. Formatting **permanently erases existing conversation archive, facts, index, and saved personal preferences**. Use the existing USB Serial Monitor explicit confirmation command `memory format CONFIRM` only after the firmware reports that formatting is available; do not enable Arduino **Erase All Flash**. Record the old `memory status` first if you want a reference.
- Hardware acceptance: record time to first reply and audio drop counters before/after; tell Kitty in French `Je suis très occupé au travail, donc je ne peux pas prendre de vacances pour le moment.` Stop the call; leave the device fully idle at least 20 seconds; review `[MEMORY AI]` logs and `memory status`; restart Call Mode and ask in English what you said about work/holidays. Repeat with a plan correction. If the model takes longer than the configured timeout, extraction may be skipped without blocking conversation.
