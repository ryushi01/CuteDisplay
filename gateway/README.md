> **SUPERSEDED — NOT THE ACTIVE CUTEDISPLAY SETUP.** The user chose direct S3 → one existing Open WebUI HTTPS/WSS origin, with URL/model/API key configured once in the iPhone app. Do **not** follow this gateway setup for the current build. See [the single-URL architecture](../docs/REALTIME_SINGLE_OPENWEBUI_ENDPOINT.md). This directory is retained only as an experimental/reference prototype.

# CuteDisplay Realtime Gateway — Phase 1 (experimental)

**Status 2026-10-28: gateway source, iPhone encrypted BLE provisioning and S3 WSS pairing/status client committed.** The **S3 microphone/speaker are not yet streaming realtime PCM**: the prototype reports `RT:STATUS=READY` when the transport is connected; this does not mean microphone capture is active. These sources require hardware validation. Existing manual PTT/WAV/MP3, C5 v21 accents, UART OTA and BLE remain unchanged.

## Why no Open WebUI password or 2FA for each call?

Open WebUI's **human/browser** Realtime WebSocket `/api/v1/audio/realtime` requires a user JWT, which does not accept a normal `sk-` key as a drop-in replacement. By contrast, Open WebUI supports durable `sk-` **API keys for HTTP automation even when MFA is enabled**. A locally hosted gateway uses a dedicated non-admin `sk-` key for `/api/chat/completions` and connects **directly to the existing configured OpenAI-Realtime-compatible provider** to stream 24kHz audio. Neither password, TOTP seed, browser JWT nor the `sk-` key is sent to the S3. The S3 retains only its distinct revocable **32-byte device secret**, provisioned once from the iPhone over encrypted BLE and saved in S3 NVS. The iPhone copy is kept in Keychain.

**Security limits:** the existing S3 BLE pairing is "Just Works" (encrypted but without active MITM proof), ESP32 NVS is not a hardware secure element unless flash encryption is deliberately configured, and a stolen device may disclose its individual key. Rotate the device key on loss. The dedicated API key inherits the issuing account's permissions; keep that account non-admin with minimum allowed access. Do not add this prototype to the public internet; restrict WSS listener to your private LAN/firewall. No insecure TLS fallback.

## Where: MacBook Terminal

1. Pull the project and create the Python environment:

```bash
cd "$HOME/CuteDisplay-realtime-v21"
git switch feature/realtime-call-c5v21
git pull --ff-only
python3 -m venv .venv-realtime
source .venv-realtime/bin/activate
python -m pip install 'websockets>=14,<17' 'cryptography>=43'
```

2. Decide on a **DNS hostname the S3 will resolve on its Wi-Fi** and that identifies this Mac. A Bonjour `.local` hostname might not resolve on every router/ESP32 configuration; test DNS on S3 before relying on it. For local testing, a split-horizon DNS record or router LAN DNS entry is preferable. Do **not** enter an IP address if its TLS certificate covers only a DNS name. Create a **two-year self-signed development CA/certificate** matching this exact hostname:

```bash
printf 'Enter DNS hostname of your gateway (reachable by S3): '
IFS= read -r CUTE_GATEWAY_HOST
python gateway/create_lan_cert.py --hostname "$CUTE_GATEWAY_HOST"
```

This creates:
- **PUBLIC** `~/.config/cutedisplay-gateway/gateway-server.crt` — paste its full PEM text into the iPhone app's **Public gateway CA certificate** field. Safe to transport; never confuse it with the private key.
- **PRIVATE** `~/.config/cutedisplay-gateway/gateway-server.key` — mode 0600, Mac-only; do **not** copy to iPhone/S3/GitHub. Renew certificate before it expires and re-pair the CA afterwards.

If you already have a valid WSS certificate and private key matching the LAN DNS hostname, use those paths instead. Do not overwrite your existing certificate unnecessarily.

3. In **Open WebUI Safari**, create an API key for a dedicated low-privilege user using **Settings → Account → API Keys**. Enable the instance's API key feature/permissions if necessary. Open WebUI API keys are unaffected by MFA, but not all users can create keys; don't disable 2FA. Save the API key **only on the gateway host**. **One API key per Open WebUI account**: rotating your own key could disrupt other clients; a dedicated account avoids this.

4. In **Open WebUI Admin → Settings → Audio → Realtime**, note:
   - Realtime provider **API base URL** (this is **not** the public Open WebUI site). The gateway's wizard converts it into `ws(s)://<base>/realtime?model=<id>`.
   - Provider **model ID** (Mac user test reported `local`); configured **voice**, **transcription model**, and provider-specific key if required.
   - If the provider lives on this same Mac, use its **loopback** base URL such as `http://127.0.0.1:8765/v1` **only if that matches your actual provider config**. If hosted on a different machine, the gateway requires **HTTPS/WSS**, not plaintext WS across LAN.

5. Run the **one-time interactive setup**. It asks for the Open WebUI API key without echoing it; do not enter your password or TOTP anywhere:

```bash
cd "$HOME/CuteDisplay-realtime-v21"
source .venv-realtime/bin/activate
python gateway/configure.py \
  --output "$HOME/.config/cutedisplay-gateway/private-config.json"
```

When prompted, enter the certificate path and private-key path created in step 2 and choose the gateway hostname and port **8766**. For S3 LAN reachability, explicitly use listen address `0.0.0.0` **only on a trusted private network**, with host firewall rules restricting access. The config file is created with mode **0600**; it contains the Open WebUI API key, upstream provider secret and the random S3 device key. It is ignored by Git. The wizard prints the distinct **64-character hex device pairing key** *once*. Enter that **device** key in the iPhone UI, never the WebUI API key.

6. **Verify the dedicated API key** from Mac Terminal before starting the gateway. This performs one small French text query using `cutedisplay-ai` and proves unattended HTTP model access without a human login:

```bash
cd "$HOME/CuteDisplay-realtime-v21"
source .venv-realtime/bin/activate
python gateway/verify_backend.py \
  --config "$HOME/.config/cutedisplay-gateway/private-config.json"
```

It should print `PASS: dedicated API key authenticated`. If you see 401/403 or a model access failure, grant the dedicated service account access to `cutedisplay-ai` in Open WebUI; do not disable MFA.

7. Start the gateway from **Mac Terminal** for the initial test:

```bash
cd "$HOME/CuteDisplay-realtime-v21"
source .venv-realtime/bin/activate
python gateway/cute_realtime_gateway.py \
  --config "$HOME/.config/cutedisplay-gateway/private-config.json"
```

The gateway listens with TLS and **rejects every client without a valid HMAC challenge response**. It uses the persistent service API key and does not request human 2FA. Leave this Terminal session running during the test.

8. In a **second Mac Terminal**, run the same TLS/device authentication that the S3 firmware will use, before flashing:

```bash
cd "$HOME/CuteDisplay-realtime-v21"
source .venv-realtime/bin/activate
python gateway/test_device_connect.py \
  --url "wss://$CUTE_GATEWAY_HOST:8766/" \
  --config "$HOME/.config/cutedisplay-gateway/private-config.json"
```

Success: `auth.ok`, `session.ready` at 24 kHz and `call.pong`. If it fails, the certificate/DNS/provider configuration must be repaired; **do not weaken TLS validation**.

9. After the above succeeds, optional **LaunchAgent** (start gateway automatically when this Mac user logs in; no prompts):

```bash
cd "$HOME/CuteDisplay-realtime-v21"
source .venv-realtime/bin/activate
python gateway/install_launchd.py \
  --config "$HOME/.config/cutedisplay-gateway/private-config.json"
launchctl bootstrap "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/local.cutedisplay.realtime-gateway.plist"
launchctl kickstart -k "gui/$(id -u)/local.cutedisplay.realtime-gateway"
```

**Stop the manual Terminal gateway before starting LaunchAgent** to avoid TCP port conflicts. Keep this Mac powered, connected, logged in and awake for unattended calls. The agent cannot provide voice if the Mac is off or sleeping. Logs live under `~/Library/Logs/CuteDisplay`; they contain only error categories and startup status, not secrets.

## Where: iPhone app (development build)

Open **Kitty AI → Realtime Call — One-Time Pairing** while connected to S3 over its encrypted Brain BLE. Enter:
- **Gateway WSS URL:** exact `wss://$CUTE_GATEWAY_HOST:8766/` using your real hostname, not the literal variable.
- **Device pairing secret:** the 64-hex string from the Mac wizard. Stored in iOS Keychain and on S3 NVS, **not** the Open WebUI API key.
- **Public gateway CA certificate:** entire `gateway-server.crt` PEM including BEGIN/END CERTIFICATE. Copy only the **public certificate**.
- **Auto-connect after power-on:** optional, OFF by default. On an audio-capable future build this will also control whether a listening session starts automatically; opt in deliberately.

Tap **Pair realtime gateway to S3**, let the BLE queue complete, then **Connect gateway** and **Status**. The S3 connects WSS with hostname verification and proves the device key through HMAC. The credentials remain after S3 restart, and no human password/2FA needs to be reentered. Use **Forget gateway pairing on S3** to revoke the local key; for **full server revocation**, generate a different key on the Mac and reconfigure/restart the gateway.

**Current hardware firmware is status-only:** on connected gateway it can display/report `READY` when authenticated, but the actual I2S microphone is **not** started. Audio transport will be enabled only after shared-clock I2S RX/TX and echo-control bench tests. Until then, continue using manual PTT.

## What this design does not promise yet

- Continuous full-duplex mic/speaker streaming on ESP32-S3; prototype gateway has the audio route but the S3 driver is not yet enabled.
- Speaker barge-in/echo cancellation.
- Open WebUI browser's chat history, approvals or UI tools: the gateway currently implements a narrow direct-API model query with bounded in-session history only.
- A service that works while the Mac/Realtime provider is powered off.
- Encryption at rest for ordinary ESP32 NVS.

Immutable rollback: `stable/2026-10-28-c5-v21-french-font-hardware-tested`. Development branch `feature/realtime-call-c5v21`.

## Supporting references

- https://docs.openwebui.com/features/authentication-access/api-keys/
- https://docs.openwebui.com/features/authentication-access/mfa/
- https://github.com/open-webui/open-webui/blob/main/backend/open_webui/routers/audio/realtime.py
- https://github.com/Links2004/arduinoWebSockets
