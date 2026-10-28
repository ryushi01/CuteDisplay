# CuteDisplay — experimental native realtime I2S voice (C5 v22 / S3)

**Status: implemented in development source; Arduino CI and physical hardware validation still required.**
The hardware-tested C5 v21 checkpoint remains unchanged. This experiment lives only on
the feature/realtime-call-c5v21 branch.

## Validated server prerequisite
On 2026-10-28 the original Open WebUI origin https://ragnarok-project.com
passed its health check, and the existing native /api/v1/audio/realtime
WebSocket accepted the saved sk- user API key and replied to a ping.
No gateway, new provider URL, login, password or TOTP needed on the S3.

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
4. Flash dev S3 and C5 v22 as one matched pair ONLY after reviewing CI artifacts.
5. Short-tap left button; expect Connecting -> Listening. Talk briefly, then
   expect Thinking -> Speaking and audible response. Short tap ends immediately.
6. Retest original PTT long-hold outside Call Mode; test Wi-Fi loss and reconnect.
7. Verify that the iPhone app login still uses its usual 2FA only when needed;
   reconnecting a device needs no human password or one-time code.

## Limitations and follow-on

- Realtime captions/text have not yet been routed to the main Kitty chat bubble.
- No AEC, no speaker barge-in, no hands-free start without pressing C5.
- Real I2S, network latency, voice-event sizes, and board timing are still unverified.
- Open WebUI upstream realtime voice engine is separately configured; the
  chosen cutedisplay-ai model is the authorized chat context, not a speaker.
- No background OTA rollout; stable v21 never auto-updates from this experiment.
