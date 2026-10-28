# CuteDisplay C5 v23 — panoramic Kitty Face Mode

## Scope and baseline

New isolated development branch: `feature/realtime-kitty-fullscreen-expressions`.
**Do not modify** frozen working stable commit `78d4abd9` or branch
`stable/2026-10-29-realtime-voice-hardware-validated`.

The existing working Open WebUI 24 kHz realtime microphone/speaker, ESP32-S3
pinout, iPhone provisioning, manual long-hold PTT, and version-checked
automatic C5 UART OTA are all preserved. No server redeployment or app install.

## Purpose-designed screen artwork

A newly drawn, **320x170 pixel**, panoramic close-up Kitty face appears only
while realtime Call Mode is active. This is new code in
`firmware/CuteDisplay/C5CallFace.h`, **not** a scaled 98x170 right-side
mascot. All points and shapes are clipped inside the LCD dimensions.

- Full-screen ears, bow, white face, eyes, yellow nose, whiskers, cheeks,
  state-dependent details and a thin bottom state capsule.
- 8 facial expressions, mapped onto existing mood semantics without
  writing the user's persisted normal-display settings:
  `0 neutral; 1 happy; 2 sad; 3 angry; 4 hungry; 5 sleepy; 6 excited; 7 shy`.
- Dynamic blinking, thoughtful glance, listening pulse, sparkles, temporary
  crying eye, annoyed eyebrows, shy blush and sleepy eyes.
- Actual speaker PCM loudness (0-9) is sent from S3 to C5 over existing UART
  at most 8 times per second; the mouth animates in sync with Kitty's voice.
- While the call is starting, the C5 face shows a connecting animation.
- Existing `ACTIVITY` frames drive Listening, Thinking and Speaking.
- Optional model-controlled avatar gestures via Open WebUI's existing
  `play_animation` tool are mapped to expressions, **only if those gestures
  are configured and approved by the existing server**. We return
  `started` when a recognized tool action is accepted and continue the
  voice response via the preexisting bridge protocol.
- When the realtime provider offers assistant audio-transcript events,
  conservative Japanese/English/French emotion words can also select
  temporary facial moods. This is a fallback, not guaranteed emotional
  inference; no extra model request or second server is added.
- AI moods return to friendly after ten seconds. Mic silence / absent
  lip updates clear the mouth, and call end/error/UART loss restores the
  exact same ordinary text/messaging display without altering preferences.

## One-upload installation and one conversation test

1. Keep a copy of the **validated** S3+C5 v22 ZIP for rollback.
2. From the successful `Build combined S3 + C5 firmware` Action for this
   exact commit, download **one** `CuteDisplay-CombinedFirmware` artifact.
3. Extract it, open `CuteDisplayBrain/CuteDisplayBrain.ino` in Arduino IDE,
   and upload **only the S3** via USB with the existing known-good
   ESP32S3 Dev Module, 16MB flash, OPI PSRAM, Custom partitions,
   ESP32 core 3.3.12, WebSockets 2.7.2, ESP8266Audio 2.4.1.
   **Never erase all flash**, which contains the saved Wi-Fi/API key.
4. Existing automatic UART OTA upgrades C5 from v22 to **v23** after S3
   upload. Expect the normal successful post-reboot version confirmation.
   No C5 USB upload and no `c5 ota enable` command are necessary.
5. Short-tap C5 left button once: full-screen Kitty face should replace
   only the Call Mode display. Talk and listen to a real answer, then ask
   another question without ending Call Mode. See Listening, Thinking and
   Speaking, with mouth movement during real speaker output.
6. **Optional visual sweep** during the same call (no additional firmware
   builds/tests): use `call mood 2`, `call mood 3`, `call mood 6` from
   S3 USB Serial Monitor to see sad, angry, and excited faces. All 8 moods
   can be displayed with `call mood 0` through `call mood 7`.
7. Short-tap left button again: original saved message/small mascot returns.
   Long-hold manual PTT works exactly as before outside Call Mode.
   If something fails, `call stop`, and use the saved v22 firmware for
   rollback; do not modify the Open WebUI server as a first reaction.

## Acceptance criteria

- The full-screen face has proper proportions and does not overlap
  persistent normal-message UI because the normal renderer is bypassed only
  during Call Mode.
- Normal message display, clock/battery indicators, BLE configuration,
  automatic C5 OTA and manual PTT are unchanged outside Call Mode.
- Realtime audio remains responsive and uninterrupted, matching the user's
  accepted v22 baseline.
- User-confirmed results after installing v23 are required before this
  artwork version can itself be called hardware validated.
