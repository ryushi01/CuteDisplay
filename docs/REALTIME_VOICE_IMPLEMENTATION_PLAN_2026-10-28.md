# CuteDisplay — Real-time voice design gate (2026-10-28)

## Baseline and isolation
- Source: main at `649d6c766cc482513ab223a432e4a4b1cca296a5`.
- Development: `feature/realtime-voice`; the branch was initially identical to main.
- Immutable hardware-tested rollback: `stable/2026-10-28-wav-uart-autorecovery-hardware-tested`.
- Retain S3 `recoverFreshBootUART()`, C5 v13 display/button commands, encrypted BLE, ESP8266Audio 2.4.1 MP3 playback, 8-bit WAV STT with 16-bit WAV fallback, original I2S pins, Japanese render path, conversation context, NVS and OTA.
- Open WebUI is on Ubuntu, publicly reachable via the already configured HTTPS endpoint. Ollama, STT/TTS backends are on the Mac. Do not alter routing or assume a Mac/Ubuntu direct device API.

## Findings from official Open WebUI Voice Mode documentation
- Standard Voice Mode records on voice activity, sends an utterance after about two seconds of silence, transcribes using configured STT, streams LLM text, and synthesizes completed sentences before the LLM has finished; it supports interrupt/barge-in at the client level.
- Realtime Voice Mode is a DIFFERENT architecture: a speech-to-speech model/provider compatible with the OpenAI Realtime WebSocket protocol, 24kHz bidirectional audio, and function calling. Open WebUI proxies the provider connection. Existing ordinary STT/TTS/Ollama services do not by themselves constitute a Realtime-compatible provider.
- References:
  - https://docs.openwebui.com/features/chat-conversations/chat-features/voice-mode/
  - https://docs.openwebui.com/features/chat-conversations/audio/speech-to-text/stt-config/

## Decision for first implementation
Implement **opt-in Standard-style continuous conversation on S3**, reusing proven authenticated HTTPS STT, streamed chat completions and MP3/WAV TTS rather than assuming the Open WebUI browser Voice Mode is a reusable ESP32 audio API. This is a staged low-latency conversational loop, not a provider-side speech-to-speech Realtime session.

### Phase A — hands-free listening (first code milestone)
- Add disabled-by-default hands-free enable/disable from iPhone and optionally C5; leave C5 press/hold behavior unchanged when disabled.
- Run 16-kHz mono mic VAD/energy gate on S3 CPU0 worker, with configurable noise-floor calibration and bounded utterance length; avoid recording only based on naive fixed noise threshold.
- Collect pre-roll buffer (~200–300 ms) so the beginning of speech is not clipped. After voice onset, finish utterance after adjustable ~700–1200ms silence, initially with cautious longer silence to avoid cutoff. Bounded 30s utterance; initial focus on Japanese and English.
- Reuse existing 8-bit PCM WAV upload, 16-bit WAV compatibility fallback, then existing BrainAI path. No Opus/Ogg.
- Do not open another I2S capture while TTS, local audio test or OTA owns hardware. All ownership transitions must be explicit.
- Add status values LISTENING / UPLOADING / THINKING / SPEAKING via existing C5 activity frames. Keep display updates nonblocking.
- In phase A disable microphone during speaker playback to avoid self-trigger/feedback. This is hands-free sequential operation, not full duplex barge-in yet.
- Disabling hands-free or tapping STOP must release microphone, cancel any pending unsent utterance, and return to existing controls. Network errors must restore listening only under explicit enabled state with exponential/capped retry, not a busy loop.

### Phase B — reduce reply latency
- While streamed BrainAI text arrives, segment sentence-complete UTF-8 text for queue-based TTS, initially one clip at a time (Japanese punctuation 。！？ and English .!? with safeguards).
- Bound queued text, network buffers and PSRAM; preserve sentence ordering, cancellation generation IDs and complete response on C5.
- Existing final-answer TTS remains the fallback when sentence TTS fails or queues back up.
- Preserve the 24-hour conversation context semantics and ensure no partial/aborted response is saved as completed.

### Phase C — genuine barge-in
- Investigate echo cancellation/echo reference and hardware acoustic separation before enabling microphone while the speaker is active.
- Initially support physical short-tap to interrupt TTS and resume listening with no collision; this is not yet speech-triggered barge-in.
- Add speech-triggered interruption only after proving robust near-end speech detection and reliable I2S arbitration on target hardware.

### Phase D — optional native Realtime provider
- Only if user has a configured OpenAI-Realtime-compatible provider reachable by Open WebUI, assess authenticated bidirectional WebSocket and 24-kHz audio constraints on S3.
- Do not point S3 at Open WebUI's /api path with invented realtime endpoints. Verify installed Open WebUI version, server route, permissions, proxy websocket upgrades and provider compatibility first.

## Acceptance checklist
1. Existing manual hold-to-talk WAV STT and spoken reply unchanged with hands-free OFF.
2. No UART-disconnect after S3 upload reset, and C5 OTA + Japanese text still operate.
3. With hands-free ON, spoken Japanese prompt triggers once, is correctly transcribed and replies through existing TTS without button.
4. Quiet room remains idle for at least five minutes; background noise does not cause repeated accidental STT calls.
5. Multiple turns complete in order with conversation context. STOP works and disables listening.
6. Mic/speaker never contend for I2S in Phase A. Verify heap/PSRAM and per-stage latency on real hardware.
7. Validate C5 activity displays, iPhone BLE/wifi and fallbacks, then mark a new stable checkpoint ONLY after user confirms physical tests.

## Current status
Architecture/research only. No runtime firmware change in this document. Next action: implement Phase A on `feature/realtime-voice`, run combined workflow, then test on physical S3/C5 before pursuing Phase B.
