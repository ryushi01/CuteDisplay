## Experimental prototype in `feature/s3-ai-streaming` (not ready for production)

Implemented on this isolated branch, not main:
- C5 v8 UART receiver for `AI_BEGIN`, `AI_DATA`, and `AI_END` with ACKs, bounded rolling text buffer, fixed-size text and local reveal/mouth animation.
- S3 worker submits `stream:true` HTTPS Open WebUI chat requests, parses SSE with cJSON, queues UTF-8-safe chunks and uses one-at-a-time UART ACK/retry.
- iPhone sends URL/model/key/CA PEM/prompt in up-to-40-byte hex blocks over **encrypted BLE**; S3 persists configuration, then receives `AI:GO`. The iPhone no longer directly calls Open WebUI in this branch.
- TLS uses a **user-provided certificate authority PEM** and certificate verification. Deliberately no insecure TLS bypass.

**Important prototype security limitations:** The current S3 BLE profile uses Just Works bonding (encrypted but without MITM authentication). The stored API credential is saved in Preferences/NVS, which is **not assumed encrypted at rest**. Until authenticated provisioning plus flash encryption are addressed, use a revocable, least-privilege test API key only, not a high-value credential. Prefer an isolated network and never expose the C5 UART to secrets. Certificate PEM belongs in the iPhone UI; do not commit it to Git. S3 and server require correct wall-clock time for TLS certificate checks.

**Known feature gaps:** This prototype only accepts one prompt at a time, has limited status reporting in the phone UI, and C5 can draw only Japanese glyphs it already knows or has cached (iPhone no longer creates live glyph packets from the streamed response). Continuous multi-turn chat history, token pacing over real display ACK, robust cancellation, special-case Open WebUI stream events, credential rotation, and voice transport are not complete. End-to-end latency and power/radio coexistence are unmeasured.

**Bring-up order:** (1) GitHub Actions build success; (2) validate C5 startup/UART OTA from known-good combined sketch; (3) confirm S3 Wi-Fi reaches AI-SERVER; (4) paste Open WebUI's CA PEM in iPhone UI and send limited-scope test key; (5) observe S3 Serial Monitor `[AI]` lines and Kitty output. Keep stable rollback firmware.

---

# CuteDisplay AI streaming architecture — S3 owns inference transport

**Decision:** The S3 Brain (not the iPhone) makes the Open WebUI request, consumes AI response tokens, and delivers display text to C5. The iPhone is a secure configuration and prompt controller. **This architecture is not yet implemented.** No AI credentials should be committed to Git.

## Confirmed deployment
- AI-SERVER: Open WebUI API and Workspace custom model.
- MacBook: Ollama inference and the existing working voice services.
- ESP32-S3 Brain: Wi-Fi, encrypted BLE control, UART to display, I2S microphone and amplifier.
- ESP32-C5 Kitty: local mascot, LCD, glyph cache, fixed-size vertical scroll and typewriter rendering.

## Network and key safety gates
- S3 requires **Wi-Fi reachability** to Open WebUI on AI-SERVER. iPhone Wi-Fi access does not prove S3 can reach AI-SERVER, especially across different subnets.
- Use HTTPS with certificate validation (CA/certificate chain). **Never** use `setInsecure()` or transmit Bearer tokens via HTTP.
- Provision API base URL, model ID and Open WebUI API key from the bonded encrypted iPhone connection, or another user-approved secure provisioning method. Current BLE command protocol permits at most 96 UTF-8 bytes per command and cannot transport a long key directly; use authenticated chunked provisioning with integrity and bounds. Store secrets in S3 NVS and never forward them to C5, UART logs, or unauthenticated LAN.
- Prompt may be larger than 96 bytes: design a separate chunked command protocol, with full reassembly, delivery ACKs and timeout handling.
- Respect the active Open WebUI custom Workspace model and its server-side personality. Do not override it with a second mobile hardcoded system prompt.

## Streaming pipeline
1. iPhone sends authorized prompt to S3 over encrypted BLE (or authenticated local network).
2. S3 queues request and uses Wi-Fi HTTPS to `POST /api/chat/completions` with `stream: true`.
3. S3 parses SSE incrementally, handling fragmented UTF-8/JSON boundaries, `data:` lines, delta content, errors and `[DONE]`. Bound RAM/response size and never block BLE/UART polling in the main loop: use a worker task, queue, bounded ring buffer and cancellation.
4. S3 forwards incremental UTF-8 text in ordered acknowledged chunks over current 921600-baud UART. C5 text buffer appends, rather than replacing a whole speech bubble for every token. Existing 96-byte commands can be reused initially with sequence and backpressure; firmware OTA has priority and AI stream pauses safely.
5. C5 owns fixed-scale wrapping, vertical line scroll, typewriter reveal pacing and mascot mouth animation **while newly buffered characters are actually being revealed**. On `AI_END`, wait until display backlog drains, then close the speaking expression and restore the ordinary mascot.
6. Prefer request/response phase telemetry to iPhone; iPhone closure/backgrounding must not abort S3-managed inference unless explicitly cancelled.
7. Reuse MacBook's voice services later; do not assume existing browser real-time voice API accepts native ESP32 I²S audio.

## Migration status
- C5's standalone typewriter improvement is on main (C5 v7 source); combined build and on-device behavior still unverified.
- Reverted iPhone-based live SSE client experiment because it would place model transport in the wrong component. Older iOS text-only request remains as a **temporary diagnostic client**, not the target architecture.
- Working Bluetooth reconnection and UART OTA remain protected. No GPIO changes.

## Acceptance tests
- S3 reaches the Open WebUI HTTPS endpoint; base URL, model and private API key provisioned securely.
- Prompt from iPhone accepted; Kitty starts typing before the AI response completes, in English, Japanese and French.
- Fixed readable font with upward scroll; Kitty stops moving its mouth precisely after final buffered character is revealed.
- Long responses and many Japanese glyphs do not freeze UI, drop UTF-8 sequences or break battery notifications.
- BLE reconnect, audio beep, UART OTA and reboot recovery still pass.
