# Phase 4 BLE pairing error 1288 / `ERR:NOT_READY` recovery

**Status:** Diagnostic and session-readiness changes have been made in source, but **neither Arduino nor Xcode builds / iPhone BLE pairing are verified**. Do not weaken BLE GATT encryption to hide the failure.

## Field report

The iPhone app reported `Send failed: Brain rejected command: ERR:NOT_READY`. S3 monitor showed:
```text
[S3] Encrypted FFF1 writes; BLE proxy starts disabled (proxy on)
[S3] BLE connected; encrypted write will trigger bonding if needed
Using default onAuthenticationComplete. Authentication failed with status 1288.
[S3] BLE disconnected; proxy gate closed
[S3] BLE transport connected; waiting for security/bonding
Using default onAuthenticationComplete. Authentication failed with status 1288.
```
The first two firmware messages belong to an **older S3 source** and are absent from the then-current main branch. Logs could span multiple boots or binaries. `1288` decimal is `0x0508` in NimBLE: a **peer-reported, unspecified SMP pairing failure**, not a specific proven key/configuration cause. Because encryption/bonding did not complete, the S3's `ERR:NOT_READY` is expected. Replacement code must be paired with matching firmware installed on S3 before other app functions work. Unreadable glyphs/garbled bytes in a USB monitor are not sufficient evidence of a UART root cause; use USB console **115200** and matched S3↔C5 UART firmware **921600**.

## Changes in source

- S3 now prints `[S3] CuteDisplay Brain FW=Phase4-BLEPAIR-FIX1-20261026` on boot, plus BLE host stack. **If this banner is absent, stop; you are not running this firmware.**
- NimBLE security callback handles both older `onAuthenticationComplete(desc*)` and newer failure-reporting `onAuthenticationComplete(desc*, status)` signatures, including `0x0508`, instead of the generic default callback. S3 prints status hex and explanation. BLE encryption and bonding requirements remain intact.
- S3 supports a **physical USB Serial Monitor** command `ble bonds clear` while iPhone is disconnected. On NimBLE, this clears the S3's **NimBLE bond store only**, not Wi-Fi provisioning, NVS display state, or user data. This can invalidate earlier iPhone pairing, so remove the Brain accessory and its old Bluetooth bond on the iPhone too. Bluedroid logs that this command is unsupported rather than risking an incomplete implementation.
- S3 sets FFF1 to `PAIRING_PENDING` on connect, `PAIRING_FAILED` on failure, `PROXY_DISABLED` on disconnect and `PROXY_READY` after successful encryption and UART relay activation. The Swift iPhone app waits up to approximately six seconds for actual `PROXY_READY` before allowing queued mascot, message, glyph and Wi-Fi writes, preventing the `ERR:NOT_READY` race after a protected read.
- **No C5 firmware/wire change in this fix.** The previous 921600 baud C5 sketch stays compatible with the new S3. C5 Bluetooth and Wi-Fi stay OFF, the persistent Brain-disconnected popup and long-press Wi-Fi toggle remain.

## One controlled test

1. Save a backup of the old known-working firmware if needed. With power OFF disconnect the shared S3→C5 5V jumper before programming. Flash the latest complete **S3** sketch folder (including `BrainPinPlan.h` and `CuteLink.h`); the C5 need not be flashed if it is already running the current 921600 baud Phase 4 firmware. If C5 is still 115200, you **must** flash it to a matching version too.
2. Open the **S3 USB-UART Serial Monitor at 115200, Newline** and reset the S3. Confirm the exact `Phase4-BLEPAIR-FIX1-20261026` firmware banner and `BLE host=NimBLE` (or `Bluedroid`). If old `proxy on` startup messages appear instead, check the correct S3 sketch directory, board/port and successful upload.
3. On the iPhone, use the app's **Forget Device** to remove the old Brain authorization and, if it appears in **iOS Settings → Bluetooth**, forget that Brain entry there too. Disconnect the phone from the S3. In S3 USB Serial Monitor type `ble bonds clear` and expect result `0` on NimBLE. Restart only S3 afterward.
4. Replace the Xcode app's `BluetoothManager.swift` with the matching current version and reinstall/relaunch the app. Pair `CuteDisplay-Brain-DEV` again through the app's native accessory picker. Look for the iPhone status **Connected securely to Brain** and S3 console `BLE encryption/bonding succeeded; app relay READY`.
5. **Only after this succeeds**, send a single `C:1` mascot command. Confirm S3 logs `BLE -> C5 command acknowledged`. Then test a short message, Wi-Fi onboarding, and Japanese glyphs one at a time.

If it fails again, capture the **new complete S3 boot and pairing log**, including FW banner, NimBLE host, pairing status/hex and the first C5 HELLO/STATUS line. Do not send Wi-Fi passwords or other credentials in logs.

## Security and link limits

Just Works BLE pairing is encrypted but not resistant to active man-in-the-middle attacks and should not be considered production provisioning. The UART 921600 rate is a bench target and unverified under full Wi-Fi+BLE load. The single-USB board power route has not been electrically load-rated; do not attach two USB power sources with shared 5V jumper connected.
