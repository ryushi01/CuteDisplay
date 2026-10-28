# CuteDisplay — Realtime voice call integration (work branch)

Date: 2026-10-28
Status: **Phase 0, investigation + read-only bridge probe. No device voice-call firmware implemented or hardware-tested yet.**

## Baseline: never regress the accepted v21 fonts
- Fork point: `stable/2026-10-28-c5-v21-french-font-hardware-tested` (hardware-accepted "it works perfectly !").
- Implementation branch: `feature/realtime-call-c5v21`; **do not modify the stable source**.
- C5 v21: preserve the original 5x7 ASCII bitmaps and matching diacritic composition, Japanese/emoji, UART OTA (921600 baud, negotiated 40/160-byte packets), and its existing buttons/animation. Do not revive v18–v20 font experiments.
- S3: preserve I2S mic/speaker wiring (BCLK 41, WS 42, INMP441 input 1, MAX98357A output 2), proven WAV STT and MP3 TTS, UART auto-recovery, iPhone app, BLE, Wi-Fi, NVS, and rollback.
- Old base remains: `stable/2026-10-28-wav-uart-autorecovery-hardware-tested`.

## Verified upstream behavior — Open WebUI
Official documentation: https://docs.openwebui.com/features/chat-conversations/chat-features/voice-mode/

**Standard call mode**: browser voice activity detection, transcribed utterances after silence, model text streaming and sentence TTS. **Realtime call mode**: browser sends/receives audio through an authenticated WebSocket to an OpenAI-compatible realtime provider via Open WebUI.

Current Open WebUI source inspected:
- https://github.com/open-webui/open-webui/blob/main/backend/open_webui/routers/audio/realtime.py
- https://github.com/open-webui/open-webui/blob/main/backend/open_webui/utils/auth.py
- https://github.com/open-webui/open-webui/blob/main/backend/open_webui/main.py

**Version gate:** These are from upstream main on 2026-10-28, *not an observation of the user's running Docker version*. Verify deployed container version, Audio > Voice calls > Realtime configuration and public reverse-proxy WebSocket upgrades before relying on this API.

Observed WebSocket API in this upstream source:
- Device/client-facing endpoint: `wss://<your-public-Open-WebUI-host>/api/v1/audio/realtime` (the audio router is mounted at `/api/v1/audio`).
- First WebSocket TEXT message: `{"type":"auth","token":"<WEBUI_SESSION_JWT>","model_id":"<SERVER_MODEL_ID>"}`; optional `chat_id` must belong to that user. Never put JWT in query params or logs.
- **Important:** this bridge's `get_verified_user_by_token` decodes **session JWT**; an `sk-` API key is **not** a drop-in substitute for this specific WebSocket auth.
- Ready event: `{"type":"bridge.ready","model":"...","voice":"...","sample_rate":24000}`.
- Keepalive application message: `{"type":"bridge.ping"}` and reply `bridge.pong`.
- Outbound user audio: `input_audio_buffer.append` with base64-encoded mono signed 16-bit PCM at **24 kHz** (max 48,000 decoded bytes per event); browser handles server turn detection.
- Incoming: `response.*`, `conversation.item.*`, `input_audio_buffer.*` events, some carrying base64 PCM output. A full-featured client must handle `bridge.respond`, `bridge.result`, the selected chat model's generation flow, cancellation/truncation and chat-history persistence; **a connection alone is not a working call**.
- Bridge rejects unauthenticated clients, disabled Realtime mode, unapproved/non-server chat models, invalid setup and provider failures. Call duration is limited and permissions/session are rechecked.
- Streaming budget (uncompressed): one direction 24,000 samples/second x 2 bytes = 48 kB/s, before base64/JSON and buffering. Both directions together require sufficiently bounded Wi-Fi/TLS/PSRAM buffers.

**Existing local backend:** MacBook `local.kittychan.realtime` on port 8765, Qwen3-TTS `server_bounded:app` on 8321, Ubuntu `kitty-tts.service` on 8322 and public Open WebUI HTTPS. Previous browser call was functional but intermittent TTS failures/disconnects were observed. Latest sentence-skip/silent-WAV continuity hotfix was deployed; sustained retest remained pending. Do not change this hosting topology or bypass the existing Open WebUI public endpoint.

## Phase 0 — test the actual deployed Open WebUI bridge (no firmware change)
New local-only diagnostic: `tools/probe_openwebui_realtime.py`.

Use a temporary virtualenv with `websockets>=14,<17`. For accounts using local Open WebUI password login **and an existing 2FA authenticator**, use `tools/probe_openwebui_realtime_login.py` instead of manually copying a JWT. This helper asks for email/password and, when the server returns `next_step=verify`, prompts for the current six-digit authenticator code. It posts `challenge_token`, `code`, and `recovery=false` to `/api/v1/auths/mfa/verify`, receives the normal session JWT, and starts the WebSocket probe. The credentials and challenge stay in process memory, are not printed, and are not written to the repository.

Recommended run:
`python tools/probe_openwebui_realtime_login.py --url https://YOUR-OPENWEBUI-HOST --model YOUR-SERVER-MODEL-ID`

For SSO, disabled password login, MFA enrollment/reset, or incompatible older Open WebUI versions, stop and inspect the server's authentication mode rather than disabling 2FA. A fallback low-level `probe_openwebui_realtime.py` can still accept `OPENWEBUI_SESSION_JWT` from a locally managed session for diagnostics, but is not preferred.

Success is `bridge.ready` at 24000 Hz followed by `bridge.pong`. This validates authenticated transport and that the realtime provider starts; it **does not** synthesize audio, validate S3 hardware or prove sustained conversation. The probe sends no audio or chat messages and does not expose token values. Do not save these credentials to CuteDisplay device NVS.

## Design gates before an S3 firmware release
1. Verify real Open WebUI bridge handshake on the deployed server and capture only token-free success/failure/status. Inspect whether existing browser Call Mode uses **Realtime**, not Standard.
2. Solve long-lived authentication **without storing a human user session JWT directly on the ESP32**. Evaluate a narrow, authenticated Ubuntu device-to-WebUI gateway or a supported secure delegated session flow, with explicit lifecycle, revocation and rate limits. Do not reuse an `sk-` key where this websocket expects JWT.
3. Establish correct chat ownership and `generate_chat_completion` delegation. Current bridge supplies a realtime provider and requires the frontend to handle conversation state; simply forwarding PCM will not preserve chat turns or all tools. Consider a server-side purpose-built adapter if substantial browser logic would otherwise live on S3.
4. Bench-test 24 kHz mono PCM capture, playback, concurrent I2S ownership and echo feedback on the Freenove S3. Retain 16 kHz WAV/STT + MP3/TTS manual fallback. Keep C5 unchanged for this gate.
5. Add an opt-in call state machine (OFF/CONNECTING/LISTENING/THINKING/SPEAKING/MUTED/ERROR), explicit start/end/mute/stop controls and automatic cleanup on network failure. Manual hold-to-talk must work when call mode is OFF.
6. Bound base64 frames, audio queues and worst-case PSRAM/heap; instrument end-of-speech -> first-audio, interruptions, no spurious VAD, and the 24h conversation retention behavior.
7. Deploy only a combined firmware artifact built from this branch; hardware acceptance is required before promoting anything to stable. Keep v21 character rendering and OTA unchanged.

## Next candidate milestone
Once Phase 0 passes, implement **S3 opt-in WebSocket connection + status-only read path** (no audio) behind a disabled-by-default switch, with authentication mediation agreed and tested. Only then layer small PCM chunks and speaker output. A simpler **Standard-style hands-free VAD loop** using existing STT/LLM/TTS is a fallback if native WebSocket authentication/delegation proves unsuitable, but it is not equivalent to Open WebUI's Realtime provider.

No services, firmware, credentials, or audio data were modified by this checkpoint.
