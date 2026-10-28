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


## 2026-10-28 macOS certificate-trust adjustment

A test Mac running Python 3.11 could open the Open WebUI site in Safari but the initial Python `urllib` HTTPS password login failed on certificate verification. **This is not evidence of invalid credentials or a 2FA failure.** Browser access may rely on macOS Keychain/native trust while the venv's OpenSSL trust roots differ. A missing server intermediate or invalid certificate may also cause this.

Both the interactive login and the WebSocket probe now use `truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)` to validate TLS using the operating system's trusted certificates without suppressing verification. Install `python -m pip install truststore 'websockets>=14,<17'` in `.venv-realtime` first. Run `curl -sS -o /dev/null -w 'HTTP %{http_code}, certificate verify result %{ssl_verify_result}\\n' "$OPENWEBUI_URL/"` to compare macOS native TLS verification. Never use `curl -k`, `ssl.CERT_NONE`, `verify=False` or `PYTHONHTTPSVERIFY=0`; if native macOS verification fails, repair the HTTPS certificate chain or trust configuration instead.

This adjustment only affects the **local Mac diagnostic scripts**; neither ESP32 firmware nor Open WebUI server was modified. Realtime WebSocket authorization and device-side authentication remain an open design gate.


## Phase 0 acceptance — user-verified Mac browser transport
User ran the diagnostic against their actual Open WebUI public HTTPS endpoint from a MacBook, using model `cutedisplay-ai`. The server accepted interactive account login with TOTP 2FA; the authenticated WebSocket returned:
- `bridge.ready` at **24,000 Hz**, provider model **`local`**.
- `bridge.pong` in response to the application ping.
- `curl` HTTP 200 and TLS verification result 0 using native macOS certificate trust.

This verifies the *control plane* only; do not infer that live PCM audio transport, microphone/speaker playback, conversation persistence or device authentication was tested.

## Phase 0.5 — MacBook audio round-trip user-verified (one turn)
- `tools/realtime_audio_smoke.py` runs a one-turn **Mac** microphone capture and speaker playback, connecting to the same authenticated WebSocket using a session JWT held in child-process memory.
- `tools/probe_openwebui_realtime_login.py --audio-smoke` handles interactive password + TOTP, then launches the one-turn audio test (requires `python -m pip install sounddevice truststore 'websockets>=14,<17'`).
- Use the same `--url` and `--model cutedisplay-ai` as the passing control-plane probe; run only in the environment that already passed 2FA.
- Captures 100 ms 24 kHz signed 16-bit mono PCM chunks to `input_audio_buffer.append`. After server-side VAD + transcription completion it sends `bridge.respond` and stops microphone capture, then receives `response.output_audio.delta` and streams PCM to macOS speakers. Saves **received assistant speech only** to `~/Downloads/CuteDisplay-realtime-smoke.wav`. Captured microphone audio is not saved to disk.
- Speak a greeting such as `こんにちは、キティちゃん。元気？`, then pause. This smoke test does **not** delegate `generate_chat_completion` to the selected model, update Open WebUI chat history, or validate barge-in; choose short ordinary small talk rather than substantive tasks. It is not the production call implementation.
- User must physically confirm mic permission (Terminal) and speaker output; consider `python -m sounddevice` when an audio device cannot open at 24 kHz.
- Do not flash any S3/C5 firmware based on a Mac-only smoke test. All firmware changes remain future work, starting with a secure device authentication/proxy design.

## JWT and 2FA architecture warning
Open WebUI's tested `/api/v1/audio/realtime` bridge expects an authenticated WebUI **session JWT**, rather than the preexisting `sk-` Open WebUI API key. The Mac diagnostic uses a transient JWT after explicit 2FA verification; **do not copy that user JWT, account password, or TOTP secret into ESP32 NVS, firmware or GitHub**. A practical autonomous device requires a narrowly scoped, revocable device identity and a server-side intermediary/session delegation path that respects existing 2FA. Design, secure, and test that gateway before connecting the S3 directly; never disable 2FA or relax TLS verification.


## Phase 0.5 user acceptance — 2026-10-28
User installed `sounddevice==0.5.6` and ran the local 2FA-authenticated audio smoke test on their MacBook with Open WebUI chat model `cutedisplay-ai`. Reported console output:

```text
Password accepted. Open your authenticator app for a fresh one-time code.
2FA verified.
Authenticated; running one-turn microphone/speaker voice test.
Voice bridge ready at 24 kHz.
Server detected speech.
Transcribed: Bonjour
Requested voice reply.
Voice response status: completed
Played and saved 2.85s response audio: ~/Downloads/CuteDisplay-realtime-smoke.wav
PASS: microphone -> VAD/STT -> realtime voice -> Mac speaker
```

**Verified:** Actual macOS microphone input, 24 kHz PCM WebSocket upload, server VAD, STT, accepted `bridge.respond`, realtime audio generation, streamed output and macOS speaker API playback. User has **not explicitly confirmed hearing** the reply; the playback API and 2.85-second output file completed without reported errors. The observed transcript was **"Bonjour"** and the user explicitly clarified that saying *Bonjour* was intentional: this is a **successful French STT smoke test**, not a misrecognition of Japanese. This does **not** validate Japanese speech recognition, multi-turn context, the selected `cutedisplay-ai` chat-model tool delegation, live barge-in or S3 playback.

**Next**: keep stable C5 v21 unchanged. Add a **two-turn test using one WebSocket session** to prove turn rearming and ordered responses; test selected `cutedisplay-ai` delegated reasoning separately, then design opt-in device/gateway authentication that respects account 2FA. Only after these gates start S3 24 kHz firmware implementation. For security never store the user's TOTP/password/JWT in device firmware. Preserve WAV/manual PTT fallback.


## Phase 0.6 — two-turn persistent voice session, **Mac test user-verified PASS**
- User clarified that uttering **"Bonjour" was intentional**, and the one-turn real-audio pass is thus confirmed **French** speech recognition and 2.85-second output.
- New diagnostic `tools/realtime_two_turn_smoke.py` uses one 2FA-authenticated 24 kHz Realtime WebSocket for **two consecutive turns**, stopping microphone capture before each `bridge.respond`, draining audio playback before opening the next capture, and writing assistant audio to `~/Downloads/CuteDisplay-realtime-turn1.wav` and `-turn2.wav` (microphone not saved).
- After `git pull --ff-only` on `feature/realtime-call-c5v21`, run `python tools/probe_openwebui_realtime_login.py --url "$OPENWEBUI_URL" --model cutedisplay-ai --two-turn` in `.venv-realtime`, with `sounddevice`, `truststore` and `websockets` installed. Speak two short simple French phrases on separate prompts (e.g. `Bonjour` then `Ça va ?`); the test does not yet drive chat-model function delegation or chat history.
- Acceptance **passed on the Mac**. A passing Mac test does not mean ESP32-S3 firmware call mode works. C5 v21 source must remain untouched.

- CI syntax gate: [Validate realtime voice diagnostic scripts](https://github.com/ryushi01/CuteDisplay/actions/runs/40683113838) **passed** at commit `cc265bc2573c0f528a57e23a2e843d579425636c`. This validates Python compilation only, **not** an executed microphone/WebSocket test; user two-turn hardware acceptance is still pending.


## 2026-10-28 user acceptance — two-turn realtime French speech
User ran `--two-turn` on their MacBook with 2FA and `cutedisplay-ai`; **one authenticated WebSocket remained open for both turns**. Exact relevant output:

```text
Realtime connection ready. One WebSocket will remain open for two turns.
Turn 1/2: speak now, then pause for transcription.
Turn 1: server VAD detected speech.
Turn 1: transcribed: Coucou, comment ça va ?
Turn 1: response completed; 2.75s audio played and saved: ~/Downloads/CuteDisplay-realtime-turn1.wav
Turn 2/2: speak now, then pause for transcription.
Turn 2: server VAD detected speech.
Turn 2: transcribed: Moi, je vais bien. Merci.
Turn 2: response completed; 5.57s audio played and saved: ~/Downloads/CuteDisplay-realtime-turn2.wav
PASS: two sequential voice turns over one authenticated realtime WebSocket.
```

**Accepted:** WebSocket persists for two sequential microphone/VAD/transcription/assistant-audio turns; French transcription and audio playback API succeeded. **Not yet explicitly confirmed by user:** personally hearing both saved spoken answers / quality. **Not tested:** model delegation (`generate_chat_completion`), saved Open WebUI chat context, automatic ongoing hands-free loop, speech-triggered barge-in, ESP32 I2S/Wi-Fi, device auth, and C5 v21 regression on a new build. Maintain original hardware-tested v21 rollback unchanged.

**Next gate:** exercise `cutedisplay-ai` model delegation with a substantive spoken question (instead of provider-only small talk), then design/review narrowly scoped gateway authentication that does not store the user's password, 2FA secret or session JWT on ESP32.
