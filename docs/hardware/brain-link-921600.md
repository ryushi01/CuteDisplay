# Phase 4 bench guide — persistent Brain-loss popup and 921600-baud UART

This is a **source-only beta**, not a tested, guaranteed-working firmware release.

## Exactly what is changed

- C5 LCD displays a modal `BRAIN DISCONNECTED` warning during startup when no S3 frames have been received, or after approximately **6 seconds** without a valid inbound CRC-checked UART frame. The popup is the **last composited layer**, so Kitty animations, text, battery and Wi-Fi popups can't hide it.
- It stays visible **until the S3 sends a new valid frame**. C5 redraws after valid link recovery, restoring the previous message, mascot and UI state rather than overwriting user settings.
- C5 Bluetooth and Wi-Fi remain **disabled**. The C5's normal Bluetooth/Wi-Fi icons describe the S3's encrypted iPhone client and real Wi-Fi association, respectively. The persistent popup describes **UART liveness only**.
- S3/C5 UART now use **921600 8N1**, up from 115200, on the tested crossed TX/RX pins. Both drivers have 2 KB RX and TX buffers; `CuteLink.h` has a single buffered `write()` per frame and both copies are identical. S3 has 45-byte framed hex segments instead of 38; C5 accepts up to 90 encoded hex characters. Increased frame-poll budgets drain burst traffic.
- **Raw UART theoretical data rate:** 921600/10 = **92160 bytes/s** before CRC framing, ACK, BLE pacing, C5 display work, and real electrical limitations. This is not the measured application throughput or a guaranteed maximum speed.

## Full source download

Download the repository ZIP for the exact updated commit. It includes the full, unabridged projects:

- `firmware/CuteDisplayBrain/CuteDisplayBrain.ino`, `BrainPinPlan.h`, `CuteLink.h`
- `firmware/CuteDisplay/lcd.ino`, `CuteLink.h`, all its other library/configuration headers
- `ios/CuteDisplay/BluetoothManager.swift`, `ContentView.swift` and other app sources
- pinout / project handoff and architecture docs

The iOS app did not change in Phase 4; use the already-updated Phase 3 app source. The old working Phase 2 rollback was commit `f2e352c3ccb9bf3e4487c41cb3e2de5d6c3fdf5d` (BLE/Wi-Fi on C5 were enabled in that rollback build).

## Safe flash and test

1. **Turn power OFF on both boards.** Disconnect the shared positive 5V jumper *before* connecting either board to its own programming USB. If you use the existing single-S3-USB power experiment, never additionally power the C5 USB with 5V lines bridged.
2. Flash **both boards**, not just one. Use `ESP32S3 Dev Module`, 16MB Flash, OPI PSRAM for S3; `ESP32C5 Dev Module`, 16MB Flash, QIO PSRAM for C5. No "Erase all Flash" operation is needed. Flash each complete sketch folder with its headers.
3. Restore **S3 GPIO47 TX → C5 GPIO1 RX; C5 GPIO6 TX → S3 GPIO21 RX; common GND**. No additional GPIO wiring. Power both by the existing bench arrangement once all power wires are connected and power is OFF.
4. Open **S3 USB Serial Monitor at 115200 baud** (the USB console remains at 115200 even though board-to-board UART is 921600). Check normal `[S3] C5 UART connected` and `[C5] STATUS ...`. The C5's popup must clear after valid UART handshake.
5. **Safest deliberate disconnection test:** Switch to **separate USB supplies** while power is OFF, remove the shared 5V jumper, and boot both boards. Then unplug **only S3 USB** while keeping C5 independently powered. After ~6 seconds, the LILYGO must show and keep `BRAIN DISCONNECTED` on screen indefinitely. Reconnect S3 USB; after its valid UART handshake, the popup must vanish without losing the current Kitty display/mood. Do not simulate a Brain outage by unplugging the S3 USB when it is also powering the C5: both would power off and no popup could display.
6. Send a single iPhone mascot/message command after link recovery, then a Japanese glyph message. Check for UART `bad_frames` or frame timeout. A rapid flood of new commands should still be paced by the iPhone's end-to-end ACK.
7. If UART is unstable at 921600 with long loose Dupont wires, use shorter firmly seated wires, confirm GND and stable S3/C5 supply. To fall back without changing pinout, set `BrainPinPlan.h` `UART_BAUD` and C5's `Serial1.begin(...)` **both** to `460800` or both to `115200`, recompile and flash both. A baud mismatch makes both sides appear offline and keeps the warning visible.

**Power safety:** Shared S3 USB → C5 5V was observed to work but header capacity, battery-charger interaction, brownout margin and backfeed protection were never electrically rated/measured. Do not connect two USB power feeds while positive rails are bridged. Heavy I²S mic/amplifier load remains out of scope.

**Verification status:** source was statically reviewed; Arduino / Xcode compilation, 921600 UART bit-error measurements, pop-up disconnection/reconnection and full BLE throughput are still **unverified** until user hardware testing.
