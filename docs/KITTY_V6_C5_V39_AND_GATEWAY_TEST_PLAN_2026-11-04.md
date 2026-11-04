# Kitty V6 — final integration staging and C5 v39 display test
**Checkpoint date:** 2026-11-04

## What is already installed and verified

The operator-confirmed Ubuntu memory-service owner-grant guard and candidate-only X-vector safety-stage installer both completed successfully. `kitty-memory-v6.service` was healthy after restart, and private semantic requests with unverified owner grants returned HTTP 403. Do NOT rerun either installer.

The working Open WebUI realtime gateway, S3 archive, Mac model/TTS, and C5 v38 hardware remain unchanged.

## New GitHub source ready for targeted test

- `server/kitty_passive_turn_bridge_v6.py`: optional observation of the actual upstream provider's completed transcript items, while always keeping owner-private history closed until an independent per-item speaker attestation and owner grant are present. No inference work in the relay, no context sent from probable voice IDs. Unit tests check 120-turn continuity, stale/cancelled turns, and guest/owner isolation. **This is not installed in live Open WebUI**.
- `server/kitty_gateway_provider_scope_v6.py`: safe AST-based read-only inspection of the *actual* private Open WebUI `realtime.py`. It reports only status labels, not source code or credentials. Its result is needed to version-match an event hook; earlier inspection showed multiple `await ws.send_json(event)` sites and no uniquely named `upstream_events` callback. **Do not apply the old broad text-replacement gateway patches.**
- `firmware/CuteDisplay/C5CallFace.h`: Call Mode captions are now drawn in **pure black glyphs directly on the Kitty-chan background** at the upper forehead (two 16-pixel-separated rows, starting y=40), with the existing UTF-8 width-aware wrapping. No opaque black caption rectangle; the separate opaque status capsule was removed and replaced with small black state text. Existing expressions, eye animations, bow and audio-driven lip movement are unchanged.
- `firmware/CuteDisplay/C5FirmwareVersion.h`: version **v39** for version-checked OTA. No hardware OTA has taken place yet. C5 v38 remains the accepted running baseline until the operator verifies v39.

## One safe Ubuntu gateway integration check (no service changes)

After the new main branch code is available locally:

```bash
cd ~/kitty-v6/private/kitty-sync-deployment/live-sync-build
git fetch origin main
git show FETCH_HEAD:server/kitty_gateway_provider_scope_v6.py | sudo docker exec -i open-webui python3 -
```

This returns `KITTY_V6_PROVIDER_SCOPE_READ_ONLY` and fixed states such as `provider_transcript_scope`, `provider_forwards_in_scope`, and `passive_hook_safe`. **Do not interpret `passive_hook_safe=yes` as permission to activate private history**: the real independently trusted speaker-to-turn issuer and app enrollment path remain missing.

The next gateway change must be created from this exact scope, backed up, syntactically checked, and opt-in/off by default. Do not copy a generic source patch into live `realtime.py` when the origin of `event` is unclear.

## C5 v39 hardware acceptance (one update, not yet performed)

1. Wait for full GitHub Actions **Build combined S3 + C5 firmware** to finish successfully for the v39 revision, including C5 binary packaging (ESP32-C5 chip ID 0x0017, version=39, OTA size limit), C5 and S3 compilation, and all caption/identity contracts.
2. For this **display-only test**, prefer flashing **only the C5 directly over its own USB** from the matching generated `release/lcd` Arduino project *if that C5 USB port is accessible*, preserving the running S3, its memory and its private sync settings. Use the exact C5 board settings/partitions from the verified artifact. Do not use an app-only binary at flash offset 0.
3. If updating C5 only via the existing S3-to-C5 UART OTA instead, compile/upload the S3 *from a trusted local build* with the required **private `KITTY_SYNC_PRIVATE_HEADER`** supplied on that host, so live SD/sync credentials remain intact. Do not assume a public CI artifact contains private credentials; its release builder explicitly excludes them.
4. Confirm C5 reports **v39**, iPhone BLE still pairs, and call start/stop, facial expressions/lip sync and long user+assistant captions remain working. The conversation text should have **no black rectangle**, with black letters over Kitty's bright face. Confirm exiting Call Mode restores the original messaging UI.
5. Run **one** realistic conversation with earlier decision recall, a guest or ChatGPT playback turn, and a later follow-up; record factual result and, only if unexpected, mic drops/UART ACK/heap/stack. Do not claim secure owner-private recall passed unless an independent per-item trust issuer and real session key were actually active.

## Explicit remaining limitations

Synthetic attestation tests and a healthy memory service do **not** mean hands-free persistent owner voice learning or secure automatic cross-call owner memory is functioning. Those require real speaker provenance, a verified/consented learning path, and the version-matched gateway patch. The C5 screen patch is unrelated to that security blocker and may be tested separately without weakening memory security.

Do not modify S3 SD archive or protected speaker anchors. Preserve the known-good C5 v38 image for rollback. No full C5/S3 flash should be performed until the operator decides which isolated hardware path to use.
