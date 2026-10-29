# CuteDisplay — experimental native realtime I2S voice (C5 v22 / S3)

**Status: implemented in development source; Arduino CI and physical hardware validation still required.**
The hardware-tested C5 v21 checkpoint remains unchanged. This experiment lives only on
the feature/realtime-call-c5v21 branch.

## Validated server prerequisite
On 2026-10-28 the original Open WebUI origin https://ragnarok-project.com
passed its health check, and the existing native /api/v1/audio/realtime
WebSocket accepted the saved sk- user API key and replied to a ping.
No gateway, new provider URL, login, password or TOTP needed on the S3.

## Configure the shared API key from the iPhone (preferred)

In the CuteDisplay iPhone app, go to **Kitty AI — Open WebUI**. The existing
secure Open WebUI user API-key field is also the credential for realtime
Call Mode. Enter the same revocable **sk-** user key that passed the Ubuntu
probe, with https://ragnarok-project.com and model cutedisplay-ai.

- **Save Open WebUI connection** updates URL, model and key together.
- **Update API Key on S3** (new iPhone development UI) changes ONLY the saved
  key, leaving the URL/model untouched. The key stays in iOS Keychain.
- S3 must be connected over encrypted BLE; never send credentials via LAN,
  URLs, serial consoles, transcripts or Github.
- The app reports **Confirmed: API key saved on S3** only when the S3
  acknowledges AI:END with ACK:AI_SAVED. A queued transfer alone is not proof.
- The firmware re-reads the key from its brain-ai Preferences for the next
  call. Browser login and 2FA settings remain unchanged.
- If an old app build is installed, the existing **Save Open WebUI connection**
  button still provisions the key to the S3. Rebuild the iOS app to get the
  dedicated key-only update and S3 acknowledgment UI.

If `call start` reports CALL_ERROR before socket/I2S startup, the experimental
S3 USB console `call diagnose` command checks local prerequisites and does
not print any secret. A periodic S3 TIME log does not by itself prove that
clock sync caused the failure.

## Wiring — unchanged from BrainPinPlan.h

| S3 pin | INMP441 mic | MAX98357A amp |
| --- | --- | --- |
| GPIO41 | SCK/BCLK | BCLK |
| GPIO42 | WS | LRC |
| GPIO1 | SD mic output | — |
| GPIO2 | — | DIN |
| 3V3 | VDD | see existing power plan |
| GND | GND and L/R selection (left) | GND |

Do not apply 5V to the microphone. Connect speaker ONLY to amplifier SPK+ and SPK-.
Keep the already-validated S3/C5 UART wiring: GPIO47 TX and GPIO21 RX on S3.
Power rails must still follow docs/hardware/s3-c5-breadboard-plan.md.
No camera/SD integration is enabled in this experiment.

## Architecture

- C5 v22 short tap toggles Call Mode; long hold while OFF keeps manual PTT.
- Existing HTTPS Open WebUI URL and saved sk- key are reused for WSS; cert validated.
- CPU0 runs one paired I2S STD 24kHz duplex master with shared 32-bit stereo clocks.
- CPU1 Arduino loop owns WebSocket and transfers bounded audio blocks via RTOS queues.
- Mic left channel is converted to signed PCM16 little-endian, 480 samples (20ms),
  sent in native input_audio_buffer.append JSON (base64). 50 frames/sec.
- Provider response.output_audio.delta audio is validated and decoded to PCM16,
  then played through MAX98357A with conservative clamped output volume.
- C5 status labels follow actual socket/I2S and server events: Connecting,
  Listening, Thinking and Speaking. CALL_ status is retained for C5 button logic.
- This FIRST test is **acoustically half-duplex**: microphone upload is muted while
  Kitty replies and for a 300ms audio tail to avoid immediate speaker feedback.
  It does **not** support barge-in or echo cancellation yet.
- Corrupt base64, overlarge audio bursts, queue overflow, loss of I2S or TLS
  fails closed to CALL_ERROR; no silent fake listening.
- Legacy PTT, TTS, audio beep/test and C5 OTA are blocked from shared I2S
  while Call Mode is active. Stable manual PTT works with Call Mode OFF.

## Hardware test gate (only after CI build and binary review)

1. Keep the v21 checkpoint intact and verify microphone L/R=GND, shared clocks,
   and speaker amplifier power/wiring before attaching hardware.
2. With Call Mode OFF, run existing 'audio diagnose' and 'audio test' over S3 USB
   serial to confirm both microphone and speaker channels already work.
3. Configure modest audio levels, e.g. mic=100%, speaker=25%, before the call.
4. Save your stable C5 v21 recovery image before uploading experimental
   S3 combined firmware. Existing AUTOMATIC version-checked OTA is restored:
   S3 will install embedded C5 v22 on a connected C5 v21 when the system is
   idle, and confirm the updated version after reboot. There is no USB
   permission command. This intentionally updates C5 too, as in prior releases.
5. After both boards report the expected versions, use USB Serial Monitor at
   115200 baud: 'c5 ota status', 'call diagnose', 'call start', 'call status',
   'call stop'. Then use the C5 left short tap for Call Mode and verify
   Connecting -> Listening -> Thinking -> Speaking. Long hold outside Call
   Mode retains the manual voice push-to-talk behavior.
6. Retest original PTT long-hold outside Call Mode; test Wi-Fi loss and reconnect.
7. Verify that the iPhone app login still uses its usual 2FA only when needed;
   reconnecting a device needs no human password or one-time code.

## Limitations and follow-on

- Realtime captions/text have not yet been routed to the main Kitty chat bubble.
- No AEC, no speaker barge-in, no hands-free start without pressing C5.
- Real I2S, network latency, voice-event sizes, and board timing are still unverified.
- Open WebUI upstream realtime voice engine is separately configured; the
  chosen cutedisplay-ai model is the authorized chat context, not a speaker.
- Automatic version-checked C5 OTA remains enabled as before. Uploading
  an S3 build containing C5 v22 will upgrade a connected v21 automatically
  once idle; keep the v21 recovery image until v22 is hardware-validated.
