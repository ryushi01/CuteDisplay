# Phase 3 beta — Brain Bluetooth, Wi-Fi, UART and iPhone testing

**Status: source fixes committed; build and hardware verification pending.** The previous Phase 3 build failed: the iPhone app showed **authentication is insufficient**, commands were lost in a full S3 queue, and S3 occasionally timed out waiting for C5 UART frames. The instructions below apply to the repaired firmware, not the old beta.

## Design and safeguards

- **Only the S3 Brain runs Bluetooth and Wi-Fi.** C5's BLE, Wi-Fi and LAN services remain disabled. The tiny LCD HUD and physical-button status view reflect S3's encrypted iPhone BLE connection and its actual Wi-Fi station connection/IP.
- The S3 BLE FFF0/FFF1 write/read characteristic requires encryption, using ESP32 Just Works bonding; phone app reads the protected characteristic to initiate iOS pairing. The S3 activates its proxy **automatically once BLE encryption/bonding is confirmed**; do not enter `proxy on`. Just Works lacks MITM protection, so this is **not production-grade secure provisioning**.
- The phone subscribes to FFF1 notifications and sends **one command at a time**. A GATT write response is not completion: wait for S3 `ACK:CMD` or `ACK:WIFI` after C5 UART completion. On `ERR`, stop the queue and show the reason; on a 20-second timeout, stop instead of blindly replaying. S3 maintains a bounded 16-command queue; each 96-byte UTF-8 command is split into 38-byte hex UART chunks and acknowledged in order. C5 responds only after processing the final command.
- S3 and C5 UART RX software buffers are now 2048 bytes, and if S3 sees no valid C5 frames for 10s it logs `Face UART timed out: silence=... bad_frames=... queued=...`. A timeout remains an **unresolved possible hardware/power or firmware stall** until reproduced and investigated.
- **C5 left GPIO0 button:** 1.4-second hold → C5 UART `WIFI_TOGGLE` → S3 enables/disables its own Wi-Fi → C5 receives `WIFI_STATE` to display confirmation. Wi-Fi credentials must first be configured on the S3 through iPhone. C5's radio never activates.
- The old C5 Wi-Fi TCP/8848 app fallback does not apply to the new S3 and is disabled in the new app. AI/STT/TTS remain not implemented.

## Safe flashing and rollback

1. Save the **known-working Phase 2 pair** at [f2e352c](https://github.com/ryushi01/CuteDisplay/commit/f2e352c3ccb9bf3e4487c41cb3e2de5d6c3fdf5d) before trying the new source. The Phase 2 C5 can be reflashed over USB if S3 pairing fails.
2. Disconnect **both USB cables and the S3 5V → C5 5V jumper** before programming either board. Flash each board individually on its own USB cable. Do not connect two USB supplies into a shared 5V rail. Reconnect the established pinout (S3 TX47→C5 RX1, S3 RX21←C5 TX6, GND↔GND) once both are powered off.
3. Arduino S3: **ESP32S3 Dev Module**, 16MB Flash, OPI PSRAM, `CuteDisplayBrain.ino` with both headers. C5: **ESP32C5 Dev Module**, 16MB Flash, QIO PSRAM, `lcd.ino` with existing LILYGO headers/libraries. Keep the user-verified power arrangement **prototype-only** until rated for current/backfeed. Optionally power boards separately with no positive 5V jumper during diagnosis.
4. Replace `BluetoothManager.swift` and `ContentView.swift` in the iOS Xcode project with matching main branch versions and rebuild/reinstall. If an earlier failed attempt left an incompatible bond, use **Forget Device** in the app and remove the Brain's old iOS Bluetooth bond if present, then re-authorize/pair through AccessorySetupKit.

## First test: one command, then build up

1. Open S3 Serial Monitor at **115200 + Newline**. Confirm `[S3] C5 UART connected` and periodic `[C5] STATUS ...`. If Face UART times out, retain the entire log, especially the new `bad_frames`/queued counts.
2. Open the rebuilt iPhone app, choose or pair **CuteDisplay-Brain-DEV**, and wait until it says **Connected securely to CuteDisplay**. S3 should log `BLE encryption/bonding succeeded; app relay READY`. The BLE icon on the C5 now reflects this *secure Brain connection* (not C5's own radio).
3. Send **one** mascot setting `C:1` (or tap Kitty) and verify that C5 changes and S3 logs `BLE -> C5 command acknowledged`. Do not begin the huge Japanese glyph batch until a single command passes.
4. Then send **Hello from Brain**; finally try one **Japanese** short text. Watch for `ERR:` or `Face UART timed out`, and confirm no `queue full` warnings appear. Hundreds of G2 glyph fragments may take longer now because the app waits for each C5 ACK, but ordering and safety matter more than raw send throughput.
5. Set S3 Wi-Fi SSID/password in the iPhone app (only your own network; never paste passwords into diagnostics). Send Connect; verify S3 logs `Brain WiFi CONNECTED`, C5 Wi-Fi icon turns green, and its diagnostic screen displays the **S3 IP**.
6. Hold the C5 left button for ~1.4 seconds. It must display **S3 WIFI OFF**, the S3 Wi-Fi should disconnect and its icon turns grey. Hold again to reconnect and get **S3 WIFI ON**. If no SSID was saved, C5 displays **SET WIFI IN APP**.
7. If BLE bond fails again, capture the *new* pairing and S3 logs; do not erase C5 battery or display settings. If the UART timeout recurs, repeat with two independent USB supplies and **no 5V bridge** to distinguish unstable power from software.

## Limitations

- The assistant has not run an Arduino or Xcode build; source requires compilation and physical tests.
- Just Works bonding encrypts communication but doesn't provide authenticated peer identity or MITM protection.
- The 5V shared-power current rating and USB backfeed behavior have not been measured.
- The C5 Bluetooth/Wi-Fi remains intentionally disabled and cannot be a fallback without USB reflashing the old firmware.
- Wi-Fi status is association, not proof of Internet or AI-server reachability. S3 AI/voice/camera integrations remain future work.


## Phase 4 update — persistent link-loss warning and increased UART speed

**Phase 4 source is not yet compiled/flashed/verified on hardware.** It requires *both* C5 and S3 firmware to match at **921600 baud**; do not flash only one side. Arduino **USB** Serial Monitor remains **115200**. C5 now shows a persistent topmost `BRAIN DISCONNECTED` overlay until valid frames from S3 return. With the Brain unavailable on power-up, the overlay stays indefinitely. After ~6 seconds of UART silence it reappears. It does not mean that the iPhone or S3 Wi-Fi is disconnected; those are reflected by separate HUD status icons. Local C5 BLE and Wi-Fi remain disabled.

One frame write per message, 2K RX+TX UART ring buffers on both ESP32s, faster reader service and larger 45-byte message segments improve physical serial throughput. The BLE app still uses end-to-end ACK pacing; do **not** remove it to increase speed, as earlier versions overflowed the S3 queue. Line bitrate increased from 115200 to 921600 (theoretical 92,160 user-data bytes per second before all protocol overhead); the system's real measured BLE-to-display rate is not yet known.

See [complete test/rollback instructions](../hardware/brain-link-921600.md).