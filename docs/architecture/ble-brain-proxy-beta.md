# Phase 3 — Brain-only BLE/Wi-Fi, app compatibility and status indicators

**IMPORTANT: THIS IS AN UNCOMPILED, UNTESTED BETA SOURCE UPDATE.** Use it only after saving your known-working previous build/commit \`f2e352c\`. The original iPhone-to-LILYGO direct BLE recovery method is intentionally disabled **in this build**, per the user's design decision; recovery requires **USB reflashing the previous C5 firmware**. Neither S3 nor C5 firmware or the Swift app update has been built in this environment.

## What changes

**S3 Brain = wireless controller**
- BLE \`CuteDisplay-Brain-DEV\` FFF0/FFF1 (encrypted writes, bonded Just Works; **not MITM-authenticated**). Battery 180F/2A19, power FFF3/FFF4 mirror real LILYGO AXP2602 samples; network FFF5/FFF6 reports **S3 Wi-Fi**, not C5. In iOS, the user chooses the authorized S3 in the new **Active Bluetooth device** picker. The app's outdated TCP/8848 C5 LAN fallback is disabled, and old C5 LAN credentials cleared when switching accessories.
- **Wi-Fi credentials now reside only on S3:** iPhone BLE \`W:S:<ssid>\`, \`W:P:<pass>\`, \`W:C\`, \`W:ON/OFF/FORGET\`, \`W:DHCP\`, \`W:STATIC:<ip>|<mask>|<gateway>|<dns>\`, \`W:GET:<field>\` are handled locally by S3. The S3 attempts a station connection (auto-on after boot when saved and enabled); it does not currently run an AI server client, HTTP API, STT/TTS or an iPhone TCP fallback service. Some fields such as \`W:GET:KEY\` and ICMP ping are not fully implemented on Brain, by design.
- S3 sends \`RADIO\` frames over existing UART approximately every 1.8 s with \`b=0/1;w=0/1;ip=<S3_IP_or_->\`. Bluetooth flag means **phone client connected to S3**, not merely radio enabled. Wi-Fi flag means **S3 station associated**. The S3 UART timeout/HELLO/HEARTBEAT remains.

**LILYGO C5 = display only**
- **Does not call \`initBLE()\`, \`WiFi.begin()\`, or \`loadWifiConfig()\`** in this build. C5 Wi-Fi is explicitly put into WIFI_OFF at startup. Its legacy W: commands are rejected, and the old physical-button Wi-Fi toggle does not turn on the local radio. Previous C5 NVS display configuration is preserved.
- Tiny top-right Bluetooth/Wi-Fi HUD indicators and the battery/diagnostic screen's BT/WIFI indicators reflect the **Brain's flags**, not LILYGO's independent radios. The diagnostic screen now labels \`SOURCE: ESP32-S3 BRAIN\` and shows \`S3 IP:\`. On a stale or lost S3 status/link, both flags display OFF/grey (no misleading C5 fallback). C5 battery SOC remains its own AXP2602 reading; the BLE battery service on S3 mirrors that C5 value.
- C5 still performs all mascot rendering, messages, Unicode/24x24 glyphs, mood/accessory handling and battery sensing. UART \`CMDHEX\` transports original app commands up to 96 UTF-8 bytes with chunk ACKs.
- The **5V shared-power arrangement is still only user-observed to boot and function**, not rated/validated. With 5V jumpers attached, power via **S3 USB-C only** and never also plug in C5 USB-C. For firmware flashing, unplug power, remove the 5V jumper, and flash separately.

## Flash & test — retain safe rollback

1. Back up/save the known-working Phase 2 firmware source, e.g. GitHub commit \`f2e352c3ccb9bf3e4487c41cb3e2de5d6c3fdf5d\`. That old build retained C5 Bluetooth and Wi-Fi, so USB-reflashing it restores standalone C5 connections.
2. Disconnect shared 5V with all power OFF. Upload **S3 Brain \`CuteDisplayBrain.ino\` + BrainPinPlan.h + CuteLink.h**, then separately upload **C5 \`lcd.ino\` + its CuteLink.h and LILYGO dependencies**. Do not erase all flash / NVS. S3 board: ESP32S3 Dev Module, 16MB Flash, OPI PSRAM. C5: ESP32C5 Dev Module, 16MB Flash, QIO PSRAM.
3. Power OFF. Reconnect verified UART **S3 GPIO47 TX → C5 GPIO1 RX**, **C5 GPIO6 TX → S3 GPIO21 RX**, **GND ↔ GND**. Use separate USB supplies with no 5V bridge for the safest software bring-up; shared S3→C5 5V is an unqualified prototype-only option and C5 USB-C must remain unplugged if using it.
4. S3 Serial Monitor 115200, Newline: verify \`[C5] HELLO\`, \`[C5] STATUS ...\`, and that HELLO does not repeatedly restart when idle; type \`status\`. **Confirm C5 Serial Monitor (if separately powered) prints "Local BLE/WiFi disabled"**. If S3 Bluetooth is not connected, the C5 BT icon should be grey; if S3 Wi-Fi is not configured, Wi-Fi icon grey.
5. On S3 console type **\`proxy on\`**. This enables the beta phone command forwarding for **10 minutes**; repeat after expiry. On iPhone with BLE diagnostic app, bond with \`CuteDisplay-Brain-DEV\`, write \`C:1\` and \`Hello from Brain\` to FFF1; check actual C5 display and UART ACKs. Verify battery FFF4 and FFF6 values.
6. **Brain Wi-Fi test:** With the S3 still in beta proxy window, provision your own SSID/password from the native iPhone app after choosing S3 (never paste a password into Serial Monitor logs). Expected: S3 prints \`Brain WiFi CONNECTED\`, the C5 Wi-Fi icon turns green and C5 diagnostics show **S3 IP**. Disconnect S3 Wi-Fi using iPhone; C5 Wi-Fi icon should turn grey even though C5 itself never initializes Wi-Fi.
7. After authorizing the Brain with Apple's picker, use the app's **Active Bluetooth device** menu to select the Brain; note the S3 currently retains the \`-DEV\` BLE name. Test plain text, mood, brightness, settings, then Japanese text/glyphs and power readings. **Do not remove the old C5 accessory record unless you intentionally want to.** Its radio is disabled in new firmware, so switching back will require USB rollback.
8. If the app or UART fails, restore both old firmware sketches over USB (especially C5) using the known commit. Disconnect shared 5V before using two programming cables.

## Remaining limits

- Neither an on-device Arduino build nor an Xcode build was run; compile issues are possible. Send exact compiler diagnostics before assuming a working update.
- Encryption + Just Works bonding is **not MITM-resistant identity verification**. The 10-minute USB gate is a temporary diagnostic safeguard, not production secure onboarding. Persistent secure authorization and pairing UX still need implementation.
- BLE GATT writes from iPhone can queue faster than the C5 can fully commit many glyph packets; app-level backpressure and UART recovery under reboot need stress testing. Do not claim exactly-once delivery.
- S3 Wi-Fi uses a basic retry loop and ESP32 station connection only. **AI/voice/network API communication is not yet added.**
- C5 audio, local BLE, local Wi-Fi are disabled by design; later microphone and speaker belong on S3. Test 5V rail capacity and brownouts before wiring audio modules.
