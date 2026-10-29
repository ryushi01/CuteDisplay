# CuteDisplay — validated system checkpoint (2026-10-29)

This document supersedes older *status* claims in historical handoff documents; those documents remain for engineering history. Hardware/software source files, exact CLI behavior and CI workflows are the ultimate implementation reference.

## User-validated functionality and current setup
- Dual-board CuteDisplay: Freenove ESP32-S3-WROOM CAM N16R8 is the brain; LILYGO T-Display-C5 (ST7789/AXP2602) renders Kitty-chan and receives C5 firmware over S3-to-C5 UART OTA.
- Brain uses Wi-Fi and communicates with an existing Open WebUI realtime gateway on Ubuntu `ai-server` over TLS-protected WebSocket. Ollama/voice services are on the Mac; audio is relayed via the Open WebUI realtime flow. Do **not** assume Ollama runs on the Ubuntu VM.
- S3 I2S microphone INMP441, MAX98357A amplifier and 4-ohm speaker, with live 24-kHz realtime audio. S3 mic and speaker share an audio ownership pipeline; keep it uninterrupted. ESP32-S3 CAM camera is present but not enabled.
- Kitty supports realtime listening/thinking/speaking states, full-screen animated face (16 moods), lip-sync, live captions, barge-in/overlap and voice responses. User confirmed real conversations and saving/recalling their name across calls.
- C5 short left press toggles realtime Call Mode; long left-button press retains manual push-to-talk. C5 short right press displays battery, S3 BLE/Wi-Fi and IP, plus microSD used percentage/used/capacity in KB/MB. Long right press controls S3 Wi-Fi.
- BLE with iPhone app remains important for first-time configuration and controls; C5 BLE connectivity and OTA must be preserved. RTC/NTP time, battery information and previous display features remain.
- Character: Kitty-chan, conversational Japanese オネエ personality; multilingual EN/JP/FR. Realtime response should be brief, spontaneous and human-like. Don't read out a memory inventory. The revised prompt and expression tool are implemented in `server/patch_openwebui_realtime_api_key.py`; changing the repo does NOT deploy the server patch.
- Voice identification is **not implemented**. The device presently assumes a single owner; never assert that voice biometric authentication exists.

## SD-only long-term memory — sources and behavior
- S3's built-in SD_MMC slot runs 1-bit SD at CLK GPIO39, CMD GPIO38, DATA0 GPIO40. Store persistent long-term data **only on the S3 microSD**, not in the ai-server or Mac databases.
- `/kitty/conversations.tsv`: timestamped archived exchanges; `/kitty/memory.idx`: compact offset/topic index; `/kitty/facts.tsv`: short structured facts, preferences and episodic notes. Media/audio is not archived to SD. The SD card is **not encrypted**.
- S3 task handles SD read/write/indexing in background on CPU0; realtime audio, UART and WebSocket callbacks must not synchronously perform filesystem I/O. Realtime voice server receives only bounded temporary memory context.
- Compact facts include name, location/work, subject attributes, multiple like/dislike subjects, brief plans/events/notes. Corrected facts can supersede matching facts; preferences on different subjects coexist. Current consolidation is **heuristic/rule-based**, NOT semantic understanding. Paraphrases and indirect cancellations may be missed (gym cancellation has a narrow special-case implementation). Old archive records are not necessarily removed by an updated fact.
- Ignore empty/vague pronoun-only preferences such as `likes:it`; firmware includes cleanup of invalid old preference entries. The user previously observed junk records and requested quality fixes. Rebooted hardware must still verify updated fixes.
- Memory bounds in current code: at most 24 active fact/note slots, new notes ≤112 UTF-8 bytes, realtime summary ≤700 bytes, history retrieval prompt bounded and a ~40-ms wait at AI request. Search index accommodates up to 150,000 recent entries (~2.4 MiB PSRAM); conversation archive remains on SD.
- C5 v35 adds a 3.5-second `FACT MEMORIZED` bottom toast beside Listening/Thinking/Speaking, signaled only after changed structured memory has been persisted to SD; it should not trigger on a duplicate or unsaved transcript. Existing C5 v34 adds SD used/total KB/MB and percent to the right-button info panel.
- `memory status`, `memory probe`, and explicit destructive `memory format CONFIRM` are S3 Serial Monitor commands (115200 baud). Never format automatically or flash with Erase All Flash enabled.

## Memory + realtime call path
1. User speaks to S3 INMP441; S3 sends realtime audio over Wi-Fi TLS WebSocket to the existing Open WebUI on ai-server.
2. The gateway/STT provider produces a transcription event. The S3 queues a transcript + placeholder answer to SD memory; extraction and persistence occur on the SD worker.
3. When a call starts, S3 sends a bounded `kitty_sd_memory` snapshot to the Open WebUI realtime gateway, which temporarily adds it to system instructions. These are *not* permanent server-side memory records.
4. Realtime voice may invoke the `generate_chat_completion` tool. S3 delegates that to its Open WebUI `/api/chat/completions` client and forwards the result. Voice output returns from the realtime voice system and plays via the S3 MAX98357A. C5 renders captions/mood/lip-sync/status.
5. If a delegated Open WebUI request returns HTTP 200 but no usable SSE content/`[DONE]`, the firmware treats it as a stream failure; the voice engine may say a tool was unavailable or ask to retry. A successful later joke proved intermittent successful delegation. Do not claim all tool errors were fixed.

## Validation and operational checklist
- User confirmed SD mount and `memory probe`: `mounted=1`, `indexed` and `saved` counters increase, `failed=0`.
- User confirmed `name\tShana` persisted and real-time conversation could retrieve their name. A transient `CALL_ERROR` was cleared by starting a call; later logs showed LISTENING→THINKING→SPEAKING, mic and speaker active with zero mic drops.
- User also observed inappropriate memory like `likes:it`, `likes:and what food I dislike`, duplicated pasta variants, and both gym plan and cancellation; mitigation commits implement vague-subject rejection and some consolidation, but hardware verification is still required.
- Prompt validated by user at high level; actual installation of newest prompt on ai-server must be checked independently. Discretionary/private memory prompt was committed later; it is a policy preference, not biometric security.
- Latest source C5 version is v35. Confirm *latest* combined firmware GitHub Actions run success before flashing; prior successful builds do not prove the v35 notification compiles or is hardware-tested.
- Always preserve full SD storage on firmware updates. Enable no implicit formatting; if an SD backup is needed, power down before removing the card.
- Acceptance test: tell Kitty a new meaningful fact, expect `FACT MEMORIZED` toast for 3.5 s; repeated identical fact should not toast; reboot S3, restart realtime call, verify recall; test multiple positive and negative preferences and a cancelled plan; short right-button press should show SD usage.

## Deployment and recovery
- Git branch prior to promotion: `feature/realtime-kitty-fullscreen-expressions`. Stable older checkpoints (2026-10-27/28) remain preserved.
- GitHub Actions `Build combined S3 + C5 firmware` outputs the Arduino IDE-ready S3 firmware bundle with embedded C5 OTA image. Upload S3 via Arduino IDE with **Erase All Flash disabled**; C5 automatically OTA-updates if its version is older.
- Installing a newer server prompt/expression/SD-memory relay patch requires separately running the audited `server/upgrade_kitty_expressions.sh` on ai-server with the updated git checkout; review the script prerequisites, backups and rollback before use. Do not deploy remotely by committing to GitHub.
- Local config, API keys, credentials and Wi-Fi settings must not be committed. Historical docs describe evolving paths; check `server/README_DIRECT_OPENWEBUI.md`, `docs/KITTY_SD_MEMORY_V1.md`, `docs/combined-firmware.md` and `docs/hardware/` for detailed instructions and pinouts.

## Boundaries and future work
- Speaker recognition / multiple-person memories are only proposals. The camera is not active.
- Fully semantic memory consolidation, embeddings/subject disambiguation, robust joke-context reference resolution, encryption, configurable per-person privacy and automatic forgetting/retention remain future work.
- The assistant's 2026-10-29 updates improve memory quality but do not guarantee that Kitty remembers everything or never misclassifies statements.
- Avoid unsafely replacing the proven real-time audio path with experimental pipelines. Preserve CI and hardware/rollback checkpoints.
