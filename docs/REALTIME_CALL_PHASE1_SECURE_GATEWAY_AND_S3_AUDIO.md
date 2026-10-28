# CuteDisplay — Phase 1: secure realtime device transport and I2S plan

Status: **Phase 1 secure persistent gateway and iPhone/S3 pairing code implemented; not deployed or hardware-tested; realtime S3 audio still pending.**
Date: 2026-10-28
Baseline: `stable/2026-10-28-c5-v21-french-font-hardware-tested` — immutable reference; development only on `feature/realtime-call-c5v21`.

## Proven server baseline

The actual Open WebUI deployment accepted:
1. Password + TOTP account login, kept in Mac process memory.
2. A 24,000 Hz authenticated realtime WebSocket; `bridge.ready` reported provider `local`; keepalive `bridge.pong` succeeded.
3. Intentional French "Bonjour", server VAD/STT and a 2.85-second spoken answer.
4. Two French user utterances and 2.75 / 5.57-second spoken replies across **one** WebSocket.
5. `generate_chat_completion` delegation on spoken "Quels outils sont disponibles dans mon modèle de chat ?", answered by selected `cutedisplay-ai` through the authenticated HTTPS chat-completions endpoint and voiced as 7.97 s audio.

Do not infer device playback or arbitrary tool usage from the above. The model/delegation test is minimal and does **not** reproduce browser chat-history, approvals or WebUI UI-tool logic.

## Hardware known constraints

Existing ESP32-S3 Freenove N16R8: `BrainPinPlan.h` sets:
- GPIO41 I2S BCLK and GPIO42 WS/LRC **shared by microphone and amplifier**.
- GPIO1 RX from INMP441 mic; GPIO2 TX to MAX98357A amp.
- 921600-baud UART to LILYGO C5: S3 GPIO47 TX -> C5 GPIO1 RX; C5 GPIO6 TX -> S3 GPIO21 RX.
- BLE for onboarding, Wi-Fi for gateway and AI.
- Current PTT mic code `BrainVoiceSTT.h` configures **I2S_NUM_0 RX** at 16 kHz / 32-bit stereo slots, snapshots WAV and posts HTTP STT.
- Current speaker code `BrainTTS.h` configures **I2S_NUM_1 TX** for WAV / uses ESP8266Audio I2S for MP3. Both modes reuse GPIO41/42 clock wires. Those modes are not a validated simultaneous full-duplex setup.

**Electrical gate:** Do not initialize two independent I2S *masters* on the same shared BCLK/WS physical wires at once. For full duplex, use one shared-clock I2S standard-mode TX/RX pair on a single controller with compatible 24 kHz / 32-bit stereo slots, after verifying ESP32-S3 Arduino / ESP-IDF version and MAX98357A acceptance. Capture INMP441 32-bit stereo and downconvert to 16-bit mono. Upconvert 16-bit mono PCM to compatible stereo TX slots with safe initial output gain. Measure actual input signal polarity and channel (L/R) on hardware. As a first bench mode, *half duplex* is safe but does **not** support barge-in. Enable truly concurrent I2S only when the shared-clock driver is verified, then address speaker-to-mic acoustic feedback.

## Proposed device transport (NOT an existing Open WebUI API)

```text
Freenove ESP32-S3 -- TLS + device-authenticated WebSocket --> personal gateway (Mac initially)
    INMP441 / MAX98357A                                 |   - Account 2FA performed locally
    24 kHz PCM audio                                      |   - Keeps user JWT only in volatile memory
    C5 UART captions/status                              |   - Routes tool delegation to cutedisplay-ai
                                                         v
                                               Existing Open WebUI public HTTPS/WSS
                                                         |
                                                 Realtime provider "local"
```

The **proposed** device-to-gateway WebSocket is **not yet implemented**. Do not confuse it with WebUI's already tested `/api/v1/audio/realtime` endpoint.

- Gateway runs on the existing Mac first, since this Mac already hosts the realtime provider and other audio components. This keeps the original Open WebUI deployment, macOS 2FA login and C5 v21 untouched. It is an initial prototype, not guaranteed unattended operation.
- Device should hold only a separate rotatable device credential, **not** Open WebUI password, 2FA secret, `sk-` API key or user-session JWT.
- For LAN use: WebSocket **WSS** with validated server identity (trusted CA or pinned key under a rotation plan) **and** device authentication (challenge/response with per-device secret or client certificate). No unauthenticated LAN bridge or HTTP plaintext bearer tokens. Prefer nondefault local port and firewall rule limiting reachable clients. Deny-by-default for unauthenticated connections, enforce per-session limits, bounded traffic, expirations and revocation.
- Gateway authenticates user interactively (password + TOTP) to Open WebUI at boot/when its personal JWT expires; stores the short-lived JWT only in memory, never on the ESP32. **Tradeoff:** the user must reauthenticate when the gateway restarts or the session expires. A supported server-side scoped identity is required before true unattended use; do not silently bypass MFA.
- Gateway validates device identity and proxies audio to the known Open WebUI WSS. It must handle actual model delegation `generate_chat_completion`: POST with authenticated session JWT to selected chat model `cutedisplay-ai`, then `bridge.result` and `bridge.respond`. Implement full chat/history and error semantics deliberately; unlike the browser, the earlier Mac diagnostic only handled one function call.
- Bounded PCM frames 100 ms: 24,000 signed-16 samples per second, 4,800 bytes per frame (16-bit mono). Device ↔ gateway **binary WS** frames to avoid embedded base64; gateway translates to/from Open WebUI JSON base64 `input_audio_buffer.append` and `response.output_audio.delta`. Order, sequence, clock/drift, output buffer and max latency must be tracked.
- Server transcription arrives as `conversation.item.input_audio_transcription.completed`. Voice transcript comes in `response.output_audio_transcript.delta` events. Convert to bounded UTF-8 captions and existing UART packets without splitting UTF-8 codepoints. Maintain C5 animation/status text and 2-minute idle behavior. Hardware font remains frozen v21.
- Reconnect and power failures: close gateway and upstream WSS promptly, cancel active output, flush mic/speaker queues, preserve and re-enable manual PTT. No stale audio replay when reconnecting.

## Opt-in state machine and fallback

States: `OFF -> CONNECTING -> LISTENING -> USER_SPEAKING -> THINKING -> SPEAKING -> LISTENING`, plus `MUTED` and `ERROR`. Realtime audio and legacy `BrainVoiceSTT`/`BrainTTS` are **mutually exclusive I2S owners**. Call mode starts disabled by default. User selects it through a deliberate app/USB command only after authentication + hardware gate. On end/error, restore existing manual button behavior (hold/release PTT, short interrupt), C5 OTA and BLE. Preserve CPU1 primary loop / CPU0 tasks conventions.

## Acceptance sequence (must be executed on real hardware)

1. Gateway loopback: test strict TLS/device authentication, single use of TOTP JWT on Mac; prove no secret in S3, C5, logs or Git. Do not expose gateway to LAN until this is satisfied.
2. S3 connect/status-only: verify TLS certificate identity, device auth, keepalive and reconnect; *no audio yet*. Manual PTT should still work with Call Mode OFF.
3. S3 RX capture: real 24 kHz signed-16 PCM from INMP441; verify French/Japanese STT on WebUI while speaker is off. Record captured levels but not persistent raw speech.
4. S3 TX playback: receive 24 kHz PCM and play through MAX98357A with conservative gain; prevent UART starvation and OTA disruption. Validate no unwanted speaker noise.
5. Verify shared-clock RX+TX single-I2S-controller full duplex. Test acoustic feedback, VAD false triggers, echo and interruption/cancel. No false advertising of hands-free barge-in before this pass.
6. Realtime provider direct greetings and substantive delegated `cutedisplay-ai` questions, then 2+ turns, caption ordering and status labels. Confirm 24h memory expiry and New Conversation semantics.
7. Build combined firmware preserving C5 v21 exact fonts; offer hardware test image separate from stable. Promote only after user confirms.

## Explicit unresolved choices

- For an **always-on** companion with the existing Mac-based realtime provider, Mac must remain available while calls are active. The gateway can later move to Ubuntu if an appropriate secure, sustainable authentication scheme is defined. No relocation is assumed here.
- A gateway user-session JWT is powerful and should be isolated from untrusted clients; local process memory with explicit expiration is only suitable for prototype. For unattended use, prefer a purpose-built low-privilege delegated identity/session facility supported by Open WebUI, not self-minting JWTs or disabling 2FA.
- Full speaker+microphone full-duplex requires I2S arbitration plus acoustic echo control. Accept short alternating turns before promising arbitrary simultaneous speaking.

No network services, user settings, C5 or S3 source have been changed in this phase; this document is a design gate only.

## Phase 1 source implementation checkpoint — 2026-10-28

The user explicitly requires **NO password, TOTP code or repeated login on board startup**. Open WebUI's browser Realtime bridge expects a user JWT and is therefore unsuitable for unattended S3 sessions; independent **sk- API keys** are supported for noninteractive HTTP chat completions with global MFA enabled. To avoid storing user-session JWT or TOTP on the board, the new gateway connects **directly to the configured Mac OpenAI-Realtime-compatible provider** for audio and calls Open WebUI's selected `cutedisplay-ai` via a dedicated scoped service API key over verified HTTPS. This gateway is **not** an adaptation of the WebUI JWT bridge; it maintains an independent call session and limited context.

**Committed source (branch `feature/realtime-call-c5v21`):**
- `gateway/cute_realtime_gateway.py`: WSS listener with mode-0600 config; 256-bit per-device HMAC challenge using fresh random nonce; verified upstream transport; 24 kHz bidirectional binary PCM; provider VAD/STT, tool-call delegation to WebUI `cutedisplay-ai` via stable `sk-` API key, bounded outputs and disconnect handling. Plaintext upstream allowed **only on localhost loopback** for the Mac realtime provider; no unauthenticated LAN gateway.
- `gateway/configure.py`: Mac interactive one-time service API key and provider settings; generates random device key for iOS app, never puts human password or 2FA code in firmware.
- `gateway/create_lan_cert.py`: one-time two-year, DNS-SAN signed RSA certificate, private key mode 0600, public cert for S3 CA pinning.
- `gateway/install_launchd.py`: run gateway at Mac user login without another manual sign-in (Mac must remain awake).
- `gateway/verify_backend.py`: no-login API-key model test; `gateway/test_device_connect.py`: simulated S3 CA-verified HMAC and provider session readiness probe.
- `gateway/test_gateway.py`, `gateway/test_voice_session.py`: automated local authentication, direct provider 24k PCM, transcription→selected-model function delegation→binary spoken output simulation.
- `firmware/CuteDisplayBrain/BrainRealtime.h`: WebSockets 2.7.2 CA-validated WSS client and device HMAC; persistent S3 NVS gateway URL, CA PEM, device-only key, and explicit boot auto-join option; reconnect after Wi-Fi loss; **status-only; no S3 mic/speaker I2S active**.
- `firmware/CuteDisplayBrain/CuteDisplayBrain.ino`: new encrypted BLE `RT:` command handler, initializes/ticks secure gateway client alongside untouched manual PTT and C5 transport.
- `ios/CuteDisplay/ContentView.swift`: new Realtime Call setup UI, URL, Keychain-backed per-device secret, public CA certificate and explicit auto-join toggle, connect/disconnect/status/forget.
- `ios/CuteDisplay/BluetoothManager.swift`: sends segmented credential and CA provisioning via existing sequential ACK-checked, encrypted BLE control characteristic FFF1.
- `gateway/README.md`: comprehensive Mac Terminal and iPhone configuration workflow. Follow this guide for exact commands.

**Current validation:**
- Gateway Python syntax, offline HMAC tests and simulated upstream audio/model flow: PASS in GitHub Actions. iOS Swift parser: PASS (**not an Xcode build**).
- Arduino combined S3/C5 firmware earlier compile for secure status client: PASS on commit `8f08df4738`. Subsequent reconnect/READY refinements may require a newer build; GitHub Actions may still be running. **No hardware tests or uploads.**
- Existing hardware-tested immutable C5 v21 base untouched. Previous Mac French 1-turn, 2-turn and delegated model voice tests all PASS.
- Full realtime S3 microphone/speaker, simultaneous I2S RX/TX and echo cancellation, C5 streaming captions, production privacy indicators, multi-turn model context and 24h history parity are not implemented / verified yet.

**Next acceptance:** Setup Mac provider/gateway once, run `gateway/verify_backend.py` and `gateway/test_device_connect.py` without interactive Open WebUI login, then rebuild/flash **S3 experimental firmware only after a current-branch compile passes**, and validate WSS HMAC status/reconnect using the iPhone pairing UI. Continue manual PTT as fallback. After that, enable shared-clock 24k I2S duplex in a separate guarded hardware milestone. Do not claim true hands-free calls before that physical validation.
