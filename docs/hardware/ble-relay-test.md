# S3 Brain Phase 2: limited opt-in BLE relay test

**Not yet compiled or physically verified.** The previous S3-C5 UART link WAS verified on the user's boards: S3 USB Serial Monitor received HELLO and C5 STATUS, and `msg Hello from Brain` displayed on LILYGO.

## Power and wiring

No hardware changes needed. Tested link: S3 GPIO47 TX → C5 GPIO1 RX; C5 GPIO6 TX → S3 GPIO21 RX; GND ↔ GND. The user also reported that **one USB cable to S3**, plus an S3 5V→C5 5V jumper, powers both and retains functioning UART. **This is a successful boot observation only**: USB/header 5V current capacity, thermal behavior, voltage droop and backfeed protections are NOT verified. Do not connect a second USB power cable to C5 while sharing the 5V rail; do not add amplifier/other high-current loads yet.

## Flash only S3; leave C5 firmware untouched

Open `firmware/CuteDisplayBrain/CuteDisplayBrain.ino`, keeping `BrainPinPlan.h` and `CuteLink.h` beside it. Select ESP32S3 Dev Module (16MB Flash, OPI PSRAM) and flash via its USB-UART port. If other powered USB sources are connected, disconnect shared 5V/UART links during flashing to avoid backfeeding. You do **not** need to reflash the proven C5 firmware.

1. Open the **S3 USB Serial Monitor** at 115200 baud with **Newline** selected; confirm UART is online (`[C5] ... STATUS`, or enter `status`).
2. Enter **`ble on`** in the S3 console. This opens an unauthenticated BLE display-control test window for **five minutes**. It defaults to off at every reset and closes on `ble off` or expiry.
3. Using an independent BLE diagnostic app (nRF Connect or LightBlue), connect to **CuteDisplay-Brain-DEV**, find service **FFF0** / characteristic **FFF1**, and subscribe to notifications if desired. Write these values as **plain UTF-8 text**:
   - `Hello from BLE` (one display message, ASCII only, ≤80 bytes; no colon/pipe/control characters)
   - `C:1` (Kitty mascot)
   - `M:1` (mood test)
4. In S3 Serial Monitor, expect `[S3] BLE test forwarded TEXT seq=...`, then a real `[C5] seq=... ACK TEXT` and `[S3] BLE relay result: ACK TEXT`. FFF1's readable/notification response is `ACK:TEXT` or a diagnostic error. **BLE write-level success alone does not mean the C5 has accepted the command.**
5. Enter `ble off` to end the test.

**Security/compatibility limits:** The S3 diagnostic BLE endpoint does not enforce pairing or encryption. The 5-minute local USB opt-in and strict input allowlist lower risk but DO NOT provide authorization during the open window. Use only in a controlled test environment. Reject all Wi-Fi credentials, power/sleep commands, G/G2 glyph packets, configuration commands and Unicode messages. Do not pair the normal CuteDisplay iPhone app to the S3 yet: battery (180F), power (FFF3) and network (FFF5) GATT services and native SwiftUI protocol are not proxied. C5 direct iPhone BLE stays fully functional. UART retries, sequence collision/replay protection, UTF-8 glyph transfer and secure onboarding remain to be built.

Next milestone: authenticated BLE onboarding/provisioning, reliable bounded UART command queue/ACK and telemetry proxy; then staged app migration. AI/I2S/camera remain future work.
