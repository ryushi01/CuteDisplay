# Phase 4 — S3 Wi-Fi onboarding diagnostics (27 October 2026)

**Current status:** the user explicitly verified that iPhone → ESP32-S3 BLE pairing **and message updates work**, and S3 ↔ C5 UART works at 921600. Do not change their BLE security configuration, C5 firmware, serial speed or bidirectional Brain-disconnected popup in response to this Wi-Fi issue.

The user could not make the **S3 join Wi-Fi from the iPhone app**. The older S3 firmware acknowledged `W:C` as soon as a connection attempt was initiated, but gave the iPhone **no actual association result or Wi-Fi disconnect reason**. Therefore the cause (unsupported AP, password, WPA mode, DHCP, RF, etc.) was **not determined** by the previous report.

## Source changes

- The S3 registers `WiFi.onEvent(onBrainWiFiEvent)`; the callback records only numeric disconnect reasons (the main loop handles logs and notifications), avoiding BLE/Serial calls from the Wi-Fi event task. Logs contain **no Wi-Fi password**.
- It reports `N:STATE:CONNECTING`, `N:STATE:CONNECTED`, `N:STATE:RETRYING`, `N:STATE:OFF` and `N:FAIL:<reason>` / `N:FAIL:TIMEOUT` / `N:FAIL:BEGIN_FAIL` on the existing encrypted FFF5/FFF6 BLE service. `W:GET:STATE` and `W:GET:FAIL` expose the last state after reconnection.
- It validates `W:S` (1–32 UTF-8 bytes) and `W:P` (8–63 bytes or empty) instead of returning ACK for invalid values; `W:C` fails explicitly if no SSID. Existing `ACK:WIFI` still means **command accepted**, not **connected**.
- On DHCP, explicitly call `WiFi.config(INADDR_NONE,INADDR_NONE,INADDR_NONE)`, which resets a previous manual IP assignment; previously `W:DHCP` only changed the stored mode flag.
- App `BluetoothManager.swift` handles `N:STATE`/`N:FAIL`; Wi-Fi section in `ContentView.swift` shows the connection attempt, reason and IP. iPhone FFF1 message/mood transport and BLE encryption remain intact. C5 remains unchanged and does not start its own BLE or Wi-Fi.

## First test, one at a time

1. Ensure the target router or hotspot offers a **2.4 GHz** SSID. The ESP32-S3 cannot use 5 GHz Wi-Fi. For a dual-band router, use a dedicated 2.4 GHz SSID for diagnosis. A WPA2-Personal compatible network avoids conflating the test with WPA3-only configuration.
2. Flash **only S3** from this commit, preserving `BrainPinPlan.h`/`CuteLink.h` with the tested **921600** board-to-board UART. Rebuild the iPhone app with **both** updated Swift sources. You do not need to flash C5. Disconnect any shared 5V jumper before connecting programming USB to multiple boards.
3. Open S3 USB Serial Monitor at **115200 baud** and confirm the exact firmware banner `Phase4-WIFI-DIAG1-20261027`. Reconnect BLE and verify one small message still reaches C5.
4. In the app Wi-Fi section, enter **the 2.4 GHz SSID and its correct password**; tap Connect once. Keep the app foregrounded. The iPhone first shows CONFIGURING / CONNECTING. The S3 should print `[S3] Brain WiFi joining: SSID_bytes=... DHCP=... (2.4GHz only)`.
5. On success S3 prints `[S3] Brain WiFi CONNECTED` and `[S3] Brain WiFi IP=...`, and the app shows **Brain Wi-Fi connected**, current IP; LILYGO Wi-Fi icon should reflect the S3 via RADIO frames. If it fails, record **the new numeric `WiFi station disconnected: reason=...` or `timed out`** and exact app message. This is the information needed to identify the problem next; avoid including your password in logs.
6. `201` often means network not found (including 5 GHz-only SSID); `202` indicates authentication rejected, commonly wrong password/router security; `15` and `204` generally indicate a handshake problem. Other codes should not be guessed at. Timeout alone is not proof of a specific fault.

**Verification:** Sources were structurally checked, but no S3 Arduino compile, Xcode build, or physical Wi-Fi connection has been demonstrated with this update. Secure Just Works bonding still lacks MITM authentication and is not final production provisioning.
