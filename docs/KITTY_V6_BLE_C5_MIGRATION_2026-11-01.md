# Kitty V6 Phase 1 — Move the iPhone BLE endpoint to the C5 (2026-11-01)

**Branch:** `feature/kitty-semantic-v6-cpu`  
**Preserve:** hardware-validated S3/C5 v36 at `cf507454edb5379001479364301ca043430ecc89` (see `KITTY_V6_WORKING_BASELINE_AND_NEXT_STEPS_2026-10-31.md`).

## Verified source findings

- S3 `firmware/CuteDisplayBrain/CuteDisplayBrain.ino` currently instantiates the phone-facing BLE GATT server, encrypted FFF1 command/read/notify, FFF6 encrypted network read, security callbacks, command and telemetry queues, and link-ready/reconnect state.
- C5 `firmware/CuteDisplay/lcd.ino` already contains a legacy BLE server (`initBLE()`) but **does not start it**: `setup()` deliberately disables C5 Bluetooth and Wi-Fi. Its old FFF1 characteristic lacks NOTIFY and encrypted permissions and is **not a drop-in replacement** for the Brain BLE protocol.
- iPhone `ios/CuteDisplay/BluetoothManager.swift` expects FFF0/FFF1, 180F/2A19, FFF3/FFF4, FFF5/FFF6, encrypted FFF1 readiness and `PROXY_READY`, per-command acknowledgments, and encrypted provisioning of S3 Wi-Fi and Open WebUI keys.
- The physical UART remains 921600 baud: C5 RX GPIO1 / TX GPIO6; S3 TX GPIO47 / RX GPIO21.
- The C5 already uses `CuteLink` framed UART, supports OTA in the combined release, and must retain display, face expressions, buttons and status handling.
- S3 still needs Wi-Fi, direct realtime 24 kHz duplex audio, SD archive, per-speaker memory, voice recognition, and C5 OTA. S3 Bluetooth should be completely uninitialized **after** all phone BLE ownership has moved.

## Target protocol

```text
iPhone CoreBluetooth (same FFFx service/characteristic IDs)
       | bonded encrypted BLE (no MITM; Just Works limitation)
       v
C5 BLE GATT + bounded pending-command queue
       | UART APP_CMD(id, part) -> S3
       | UART APP_ACK(id, status) <- S3
       | UART APP_EVT(type, payload) <- S3
       v
S3 command dispatcher / Wi-Fi / AI / audio / SD
S3 -> C5 -> iPhone: network status, AI status, command completion
S3 -> C5 display: existing frames (unmodified)
```

**Important:** `CuteLink::PAYLOAD` limits individual UART frames. Segment and reassemble requests and telemetry with bounded buffers, CRC, sequence IDs and timeouts; never send raw 96-byte, unbounded, or plaintext-traced secret values. Preserve single-command ACK ordering and existing ESP32 firmware-update frames. Never let a local C5 command silently ACK a S3-owned operation before S3 confirms it.

## Implementation sequence (one combined release, minimal flashes)

1. Add a **C5-owned secure GATT server** compatible with the existing iPhone app: bonded Just Works encrypted FFF1 read/write + notify, encrypted FFF6 read, same UUIDs and battery/power reporting, `PROXY_READY` only when S3 UART is online and bridge is ready. Keep BLE work out of LCD drawing and OTA critical sections.
2. Add C5-to-S3 bounded command frames and S3-to-C5 results/telemetry frames. Reuse the existing command dispatcher on S3. Keep Wi-Fi and Open WebUI credentials in S3 NVS only; do not persist them on C5, echo them to UART debug logs, or expose them through unprotected GATT read.
3. Completely remove runtime S3 BLE initialization, server, callbacks, connection queues and advertising; also remove S3 BLE compile-time dependencies where safe. Ensure LAN authentication and app command handling remain independently functional. Use UART-origin connection state instead of S3 `bleAuthenticated` and enforce bridge session gating.
4. Update iOS labels/reconnect and provisioning flow so the phone pairs with the **C5's new BLE identity**; old bonded S3 identifier will not be reused. Keep existing command strings and their ACK semantics; preserve AccessorySetupKit/background behavior.
5. Bump C5 firmware version **37 or higher** only in a complete release. Run one CI combined build, inspect compile and static protocol checks, then flash the S3 combined sketch **once**; S3 transfers the new C5 app over the proven UART OTA channel.
6. Short acceptance check: app pairs with C5, receives `PROXY_READY`, display command ACKs, S3 Wi-Fi status/provisioning and a short realtime call work; C5 OTA/version and SD remain intact. Record `heap_caps_get_free_size(MALLOC_CAP_INTERNAL)` and largest block on S3 before/after; don't claim savings without measurements.

## Safety and rollback

- Existing v36 is **working**, migration is **not implemented or hardware-validated** by this design note. Do not upload a mixed S3-only or C5-only intermediate firmware.
- The first combined flash may update C5; preserve stable combined artifact and C5 USB recovery. S3 and C5 must agree on new UART APP frames before BLE switches.
- Trust boundary: encrypted BLE Just Works blocks passive sniffing but **does not prove the owner identity**. Never equate iPhone pairing, voice matching or a spoken name with verified-owner permission to read private memories.
- Bluetooth changes first; only afterward implement durable speaker-scoped SD writes, per-turn direct-realtime recall, consistent voice matching and bounded private server storage.
