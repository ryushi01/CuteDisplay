# CuteDisplay 🎀

## Release synchronization status (2026-10-23)

**Wi-Fi fallback is currently a testing candidate, not verified production.** The iOS `BluetoothManager.swift` includes an authenticated TCP fallback, but the repository's `firmware/CuteDisplay/lcd.ino` is older and does not yet contain the companion LAN server. Until the newer firmware is committed and uploaded to the board, the iOS fallback **will not work**. Use the complete `CuteDisplay_WiFi_BLE_Fallback.ino` provided with the release ZIP, rename it `lcd.ino`, and verify it against the hardware before replacing the repository version.

In Xcode, add the `NSLocalNetworkUsageDescription` key described in `ios/CuteDisplay/AccessorySetup-InfoPlist.xml` to the actual app target's Info settings. That XML file is an instruction fragment, **not** an installed Info.plist. Ensure that both iPhone and CuteDisplay are on the same trusted LAN, with TCP port 8848 reachable. The fallback is a foreground/best-effort TCP connection (no guarantee while the iOS app is suspended or force-quit) and is authenticated but not encrypted.

The repository doesn't include a complete Xcode project or the external ESP32 board/library dependencies. Neither the iPhone build nor Arduino firmware has been compiled and hardware-tested in this environment, so it is not appropriate to claim a production deployment.


A Bluetooth-controlled cute display built for the **LILYGO T-Display C5 (ESP32-C5)** with a **320×170 ST7789 LCD** and a companion **iPhone SwiftUI app**.

## Latest version: 4.0

- Six procedural, animated mascots and selectable moods (no sprite-sheet art)
- Optional randomized surprise animations (sneeze, stretch, startled, look around, butterfly)
- Adjustable mascot size and visibility; smaller mascots leave more room for text
- Japanese/Unicode text delivered as glyphs over BLE
- Message Mode with optional speech bubble and typewriter effect
- 25 color choices; black screen background with light-tinted speech bubble
- Drinks Mode with contrasting rows, pagination and automatic updates from iPhone
- Live AXP2602 battery percentage, voltage, charging/discharging current, health, temperature, time estimates, and calculated battery-side watts
- Remembered device pairing and automatic BLE reconnection when iOS permits the app to run
- Brightness and deep-sleep button

## Project layout

```text
firmware/CuteDisplay/lcd.ino       Arduino sketch (v3.8)
ios/CuteDisplay/ContentView.swift  SwiftUI screen
ios/CuteDisplay/BluetoothManager.swift  BLE communications
archive/                           Earlier downloadable versions
```

## Setup

### ESP32-C5 firmware
1. Install Arduino IDE and Espressif ESP32 board support (project last used ESP32 core 3.3.12).
2. Use your working **LILYGO board_config.h** and installed **axp2602.h** library. These external board/library files are **not included** in this repository.
3. Open `firmware/CuteDisplay/lcd.ino`. If Arduino IDE asks to create a matching sketch folder, allow it; copy your existing `board_config.h` alongside the sketch as in your working setup.
4. Select the board/port corresponding to the LILYGO T-Display C5, click **Verify**, then **Upload**.
5. **Do not** copy `MascotSprites.h` from 3.5B. That version's sprite artwork was rolled back.

### iPhone app
1. Open your existing CuteDisplay Xcode project. The full `.xcodeproj` was not available in the conversation, so this repository contains the **complete two Swift source files**, not a standalone buildable Xcode project.
2. Replace the corresponding `ContentView.swift` and `BluetoothManager.swift` files with the files in `ios/CuteDisplay/`.
3. Preserve your app's bundle identifier to retain saved app settings.
4. Select your physical iPhone; Build (⌘B), then Run (⌘R). BLE is not available in iPhone Simulator.

## BLE protocol

Uses `FFF0` control service and `FFF1` read/write characteristic; battery service `180F` with characteristic `2A19`. Additional power telemetry is exposed by `FFF3`/`FFF4` (read/notify) as `SOC,volts,amps,tempC,healthPercent,minutesToEmpty,minutesToFull`. Positive amps = charging, negative amps = discharging. Example commands include `D:RESET` / `D:ADD:NAME,COUNT` / `D:SHOW`, `C:<id>`, `T:<id>`, `B:<percent>`, and `S:0` / `S:1` for surprise animations.

## Earlier versions

Historical download packages are in `archive/`. **3.5B is retained only as history**: its sprite-based mascots were intentionally rolled back in favor of the procedural 3.4-style renderer. The latest recommended combination is v4.0 firmware and app source.

## Important notes

- Code in this repository is not independently hardware- or Xcode-verified; test on your device and keep backups of your working build.
- Don't commit private credentials, Apple signing certificates, or provisioning profiles.
- The app's deep sleep disables BLE until the board is physically restarted.
## Pairing and power notes

The iPhone app remembers the selected BLE peripheral UUID, automatically attempts reconnection when launched and after disconnection, and offers Pair New Device, Forget Device and an auto-reconnect switch. This is app-level remembered-device pairing, **not an encrypted Bluetooth bond**. Auto-reconnection in the background is subject to iOS execution policies; the app cannot reconnect while the board is in deep sleep. Current and power describe the **battery path**, not the complete USB input consumption. Power is calculated from battery voltage × absolute battery current. Some fuel-gauge estimates may be unavailable or inaccurate depending on calibration and battery conditions.

The changes were not independently compiled or tested on real hardware. Test with the board's original `axp2602.h` and `board_config.h` preserved.

## Native iOS accessory setup (v4.0)

- **Minimum deployment target: iOS 18.0**; add the native `AccessorySetupKit` framework to your app in Xcode.
- **Required manual Xcode configuration:** add the keys from [AccessorySetup-InfoPlist.xml](ios/CuteDisplay/AccessorySetup-InfoPlist.xml) to the app target's existing Info.plist. This repository does not contain the original Xcode project, so these keys cannot be set automatically. The file is an XML fragment, not a complete Info.plist.
- On your iPhone, open the app and tap **Pair New Device**. Select **CuteDisplay** in Apple's accessory picker. After pairing, the accessory is registered with the system and the app reconnects through its authorized Bluetooth identifier.
- Tap **Forget Device** to request removal through Apple's system accessory APIs. The user can also review system-managed accessories in iOS Settings > Privacy & Security > Accessories. Appearance in Bluetooth Settings > My Devices is controlled by iOS and isn't guaranteed for custom BLE hardware.
- The ESP32-C5 now requests secure-connections bonding and encrypted BLE command writes. The board has no convenient passkey-input mechanism; it uses Just Works bonding, which is encrypted but not MITM authenticated.
- If your Xcode app deployment target is below iOS 18, increase it; otherwise the AccessorySetupKit imports will not compile for the older target.
- Background reconnection is iOS-controlled. Additional background mode / state restoration changes would be needed for resilient suspended-app scenarios.
- Verify on your board and real iPhone; these source changes have not been independently compiled, flashed, or physically tested.
