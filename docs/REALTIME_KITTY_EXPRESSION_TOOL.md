# CuteDisplay realtime Kitty expressions — device-only Open WebUI tool

Status: development branch `feature/realtime-kitty-fullscreen-expressions`.
Do not overwrite frozen hardware baseline `stable/2026-10-29-realtime-voice-hardware-validated` (`78d4abd9`).

## What's different

- A dedicated `set_expression` realtime **function tool**, rather than hoping
  the 3D avatar's optional `play_animation` gestures are enabled.
- Fixed allowlist: neutral, happy, sad, angry, hungry, sleepy, excited, shy.
- Offered only to authenticated realtime clients that send
  `"kitty_expressions":true` in their existing first WebSocket auth message.
  Existing browser/iPhone and older S3 clients see the unchanged tool list.
- The S3 validates one of the eight exact emotions, changes only C5 Call Mode
  face state, replies with the pre-existing validated
  `bridge.animation.result` and `bridge.animation.respond` continuation.
- No new host, provider, API key, password, login, or Open WebUI database.
  The HTTPS/WSS microphone and speaker stream, core pin mapping, and PSRAM
  audio ring are unchanged; C5 v23 artwork is unchanged.
- Because `set_expression` is a model tool choice, the face responds when the
  voice model invokes it; it is not a guaranteed psychological emotion detector.

## One coordinated installation (no repeated firmware experiments)

### On ai-server (Ubuntu): one safeguarded upgrade command

From a shell on your existing ai-server:

```bash
cd ~/CuteDisplay-realtime-server
git fetch origin feature/realtime-kitty-fullscreen-expressions
git switch feature/realtime-kitty-fullscreen-expressions
git pull --ff-only
bash server/upgrade_kitty_expressions.sh
```

This server script:
1. Checks your exact running Open WebUI Docker container, persistent volume,
   original Compose and existing /health before changes.
2. Builds a new image **from the image currently running**, preserving its
   user, API-key patch, Open WebUI server version, and browser MFA.
3. Creates a consistency-safe stopped-state backup of the Open WebUI data
   volume, verifies gzip/tar/SHA-256, and separately preserves the original
   tagged image and rollback Compose override.
4. Deploys only the Open WebUI service after the backup passes, checks the
   exact image and HTTP health, and automatically reverts the container if
   deployment fails. The verified backup remains in a private directory.

**Important:** This command is written for the previously documented host
layout `/home/ryushi/docker-compose.yaml`, Compose project `ryushi`,
service `open-webui`, Docker volume `open-webui`, host port `8080`.
If your current server has changed, the script refuses to deploy.
The user must run this command on their server; GitHub CI alone does NOT
change their server.

### On the Mac: one S3 upload, no C5 USB upload

1. Download the successful `CuteDisplay-CombinedFirmware` GitHub Actions
   artifact from this feature branch, and extract it.
2. Open `CuteDisplayBrain/CuteDisplayBrain.ino` in Arduino IDE.
   Upload ONLY to the S3 using the existing ESP32S3 Dev Module, 16MB flash,
   OPI PSRAM, Custom partition scheme, and ESP32 core 3.3.12.
   Keep **Erase All Flash disabled** to preserve your Wi-Fi/Open WebUI key.
3. Automatic version-checked C5 OTA still works. If the C5 is already v23,
   it should NOT flash a new C5 image. iPhone app remains unchanged.

### ONE acceptance test

- Start a realtime call from the C5 left short tap.
- Say: **"Kitty, act sad for a moment, then cheer up and get excited!"**
  Check that the full-screen expression changes when the voice model calls
  `set_expression` and that speech plays smoothly.
- Short-tap to end Call Mode. Original normal message and long-press PTT
  should return unchanged.

Optional S3 serial diagnostics: `call status` and `call mood 3` within a
call. Look for `[CALL FACE] AI set expression=2 (set_expression)` and
`[CALL FACE] AI set expression=6 (set_expression)`. These logs show a
**real model tool call**, not a locally forced expression.

## Rollback and limits

If S3 Call Mode misbehaves, upload the validated v22 S3 combined firmware
ZIP from commit `78d4abd9` without erasing flash. Keep existing C5 v23
unless a display recovery specifically requires reverting it.
The server command prints a `rollback.yaml` path and undo command.
Do not delete the server backup until you have confirmed the voice call.

This does not alter the upstream Open WebUI source repository, add an avatar
model to your account, or guarantee that the realtime voice provider chooses
the tool on every appropriate emotion. This is an opt-in tool that gives it
an explicit, bounded way to change Kitty's face.
