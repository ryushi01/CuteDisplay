# CuteDisplay realtime — ONE Open WebUI URL (active decision)

Date: 2026-10-28. Replaces the proposed dedicated Mac gateway pairing architecture, which was rejected as unnecessarily complicated by the user.

## User requirement

CuteDisplay's ESP32-S3 brain must connect **directly to the user's existing Open WebUI server**. The iPhone app collects **one HTTPS WebUI URL**, the selected `cutedisplay-ai` model ID, and a **revocable Open WebUI `sk-` API key**. The iPhone provisions those three settings over the already-existing encrypted S3 BLE characteristic; they persist in S3 NVS and are reused after reboot. C5 remains display/UART only. NO second gateway host/port, dedicated certificate, provider URL, provider key, transcription endpoint, or TOTP request at each S3 start.

## Current implemented behavior

- **S3 normal chat REST:** `BrainAI.h` already uses `POST <OPENWEBUI_URL>/api/chat/completions` with the `sk-` API key and selected model. It stores `url`, `model`, `key` in the `brain-ai` ESP32 Preferences NVS namespace.
- **iPhone:** `ContentView.swift` exposes only the Open WebUI URL, model and API key. The new **Save Open WebUI connection** button saves to iOS Keychain and, if connected to S3 via encrypted BLE, queues U/M/K via the existing `AI:BEGIN`, `AI:DATA`, `AI:END` ACK-controlled provisioning; it **does not** launch a chat, require a prompt, or transfer the Open WebUI password/TOTP. If the S3 is offline, settings stay on the phone until Save is tapped again with BLE connected.
- **Manual PTT voice:** existing S3 direct-to-WebUI HTTP transcription/chat/TTS routes remain unchanged; no additional gateway.
- **Superseded experiment:** `gateway/` and `firmware/CuteDisplayBrain/BrainRealtime.h` are retained as historical code but NOT included in the active S3 build or presented in the active iPhone UI. DO NOT ask user to run `gateway/configure.py`, create self-signed gateway certificates, or add another host.

## One blocker for truly continuous native Open WebUI Realtime calls

**Verified source behavior** (Open WebUI backend `backend/open_webui/routers/audio/realtime.py` and `backend/open_webui/utils/auth.py`): the **browser-style** WebSocket `wss://<WEBUI_HOST>/api/v1/audio/realtime` currently expects a **session JWT**, resolved through `get_verified_user_by_token`. It **does NOT directly accept `sk-` API keys**. An API key works for normal HTTP REST chat, but substituting one in the websocket auth JSON will be rejected. Do not claim otherwise.

**Plan:** Make a minimal *server-side* change inside the **existing Open WebUI service** (not a separate gateway URL), adding permission-checked API-key auth for only `/api/v1/audio/realtime`:
1. Authenticate `sk-` using WebUI's existing API-key manager, the `auth.enable_api_keys` setting, `features.api_keys` permission for non-admin users, and configured endpoint restrictions. Never bypass MFA on human sign-in; the API key is already a user-authorized automation credential.
2. Preserve existing `chat.call` permission, selected model access control, and chat ownership checks in Realtime route.
3. Recheck API-key validity/permissions during long-lived sessions, so revoking the key disconnects the board promptly.
4. Use the same verified HTTPS certificate and WebUI hostname, upgrading to WSS; no self-signed client gateway cert or second server.
5. The iPhone still provisions only the standard `url`, `model`, and `sk-` key. No user password, session JWT, TOTP seed or 6-digit code is saved in S3.
6. Implement bounded 24kHz I2S mic/speaker streaming and WebUI event protocol on S3 after server auth path is proven. Keep manual PTT as fallback; C5 v21 source and font are immutable.

A version-guarded source patch is now **prepared in** `server/patch_openwebui_realtime_api_key.py`. It reuses Open WebUI's existing `get_current_user_by_api_key` permission and endpoint-allowlist checker for the *same* `/api/v1/audio/realtime` WSS route, and performs periodic API-key revocation checks. It keeps existing JWT behavior. **It is not installed, and has not yet been verified against the exact running Ubuntu Docker image.** The patch must be reviewed, checked against the deployed version, tested with positive/negative API keys and revocation, and baked into a persistent custom container image rather than manually changing a running ephemeral container. Do not put the normal human JWT in S3 NVS as a workaround; it expires, could bypass intended 2FA boundaries, and does not satisfy always-on availability.

## Security limits

Long-lived `sk-` credentials on S3 are sensitive: use a dedicated low-privilege account/key scoped to only needed endpoints, keep TLS certificate verification ON, avoid printing API keys on BLE serial logs or in Git, and rotate on device loss. Existing BLE "Just Works" does not offer active MITM resistance; formal stronger pairing and S3 flash encryption may be needed if deployed beyond personal prototype. API keys don't require a new human MFA event per call, but they must be created through an authorized Open WebUI account with normal human authentication.

## Validation gates

- iOS Swift parsing and S3 direct firmware compilation on this new branch: run GitHub Actions; no hardware claims until user tests it.
- Test normal REST model query over HTTPS using saved `sk-` and `cutedisplay-ai`.
- Implement/test WSS API-key support in the existing Open WebUI server and ensure a wrong/revoked key fails.
- Only then add guarded 24kHz duplex I2S and streaming audio on S3, respecting shared GPIO41/GPIO42 clocks, BLE/OTA/manual PTT compatibility and 24-hour memory requirements.

**Active simplified architecture:** `iPhone (one-time setup) -> S3 Wi-Fi -> one Open WebUI HTTPS/WSS URL -> selected chat model and existing voice stack -> S3 audio + C5 display`.
