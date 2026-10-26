# Phase 5 — S3 Brain auto-reconnect and local Wi-Fi fallback (BETA, UNTESTED)

## Status / constraints

The user has confirmed the iPhone can **pair with S3 over encrypted BLE, send messages**, and the S3 ↔ LILYGO C5 UART is **working at 921600 baud**. The S3 also joined a **2.4 GHz IoT WLAN**. These known-working parts must stay unchanged. This Phase 5 update changes **only** S3 firmware, the iOS Bluetooth manager and UI, and the iOS Info.plist instructions. Do not reflash the C5.

**Sources have not been compiled or tested on devices.** Keep the previous known-working commit `a37fc0c3395813fe21538d52b64b76248c551dd7` for immediate firmware/app rollback.

## Behavior

- Once the Brain is paired through Apple's AccessorySetupKit and **Automatically reconnect Brain Bluetooth** is on (on by default), the app reconnects to that same **authorized S3 Brain** when it returns to range. The CoreBluetooth pending connect can wait while out of range. A foreground timer retries after a failed connection. CoreBluetooth state restoration is configured, but iOS scheduling/background restrictions mean the app **cannot guarantee a reconnection while suspended or force-quit**.
- On a successful encrypted BLE session, the app asks FFF6 for **S3-owned IP and a 256-bit LAN key** (`W:GET:IP` and `W:GET:KEY`). The key is stored per authorized Brain in the iOS Keychain; the Brain generates/stores it in S3 NVS. C5 legacy LAN IP/token settings are discarded.
- If BLE isn't available, the app uses the remembered S3 IP or Bonjour `_cutedisplay._tcp` to find the **S3 server port 8848**, only over the iPhone Wi-Fi interface. The Brain accepts only IP addresses on its local subnet; IoT client isolation, guest VLANs and routing restrictions may block fallback even if both endpoints have Internet access.
- TCP authentication uses a fresh 16-byte random challenge encoded as 32 hex characters. The phone sends `AUTH <HMAC-SHA256(key, challenge-as-ASCII-hex)>`. The raw key is **never sent across TCP**. A `CMD <command>` is accepted only after authentication and acknowledged **after the C5 UART command completes**. Messages, glyph uploads, mascot settings and other display controls use the Brain relay on both transports. The app prioritizes BLE if it returns and switches away from TCP, with **no automatic replay** of an indeterminate in-flight command.
- Network status reads over LAN use `STATUS`, which returns the **Brain** network link state/IP/DHCP mode/subnet/gateway/DNS/RSSI. Wi-Fi SSID/password/IP *changes* and Bluetooth pairing/authorization require the encrypted BLE connection; the Brain rejects all LAN `W:` commands. No C5 network features are re-enabled.
- **Security caveat:** HMAC authenticates the connection and avoids sending the secret over the LAN, but TCP **payloads/commands are still unencrypted** and can be observed or tampered with by a malicious party on the network. Use only a trusted local network. A production design needs TLS or equivalent authenticated encrypted transport. The existing BLE profile is Just Works bonding, which provides encrypted GATT but no authenticated MITM defense.

## iPhone setup

- Copy the matching `BluetoothManager.swift` and `ContentView.swift` into the Xcode app target.
- In the **actual** Xcode app target Info settings (not merely the checked-in example fragment), add `NSLocalNetworkUsageDescription` and **`NSBonjourServices` = array containing `_cutedisplay._tcp`**. Existing AccessorySetupKit and Bluetooth permission keys must remain. Accept the iOS Local Network permission prompt.
- On first run of this version, **connect by BLE at least once** while the Brain is on the IoT network. Wait for Brain network details and IP; token exchange may take a few seconds. Do not paste the 256-bit key or Wi-Fi password into diagnostic reports.

## Controlled tests

1. Flash **only the S3** from the updated sketch folder, including the unchanged `BrainPinPlan.h` and `CuteLink.h`. Disconnect the shared 5V jumper before separately connecting USB supplies. Keep GPIO47 TX→C5 GPIO1 RX, C5 GPIO6 TX→S3 GPIO21 RX, common GND and **921600** board-to-board UART. S3 USB serial debug remains **115200**.
2. Rebuild the iPhone app using the new Swift files and Info settings. Pair/restore the already-authorized Brain via BLE. Confirm a message still displays on C5 and S3 logs `Brain LAN listening <ip>:8848`; do not remove an already-working BLE bond just for this update.
3. With the iPhone joined to a Wi-Fi network **that can reach the Brain IoT WLAN** (same subnet, without client isolation), temporarily move the iPhone out of BLE range or disable iPhone Bluetooth. The app should show **S3 Brain • Local Wi-Fi fallback** after LAN discovery/HMAC authentication. Send a short message and verify that C5 displays it.
4. Restore iPhone Bluetooth / return close to S3. The app should automatically reconnect to its previously authorized Brain (in foreground), switch to **S3 Brain • Bluetooth (preferred)**, and send a new message. No new pairing selection should be required unless the OS revoked authorization.
5. If fallback fails, check iPhone Local Network permission, that the Brain and phone are on the same subnet, that the router doesn't have IoT/guest isolation, and whether `[S3] Brain LAN listening ...` appears. DHCP-assigned IP may change; Bonjour improves discovery if permissions allow.

**Rollback:** Restore both S3 firmware and iPhone source from commit `a37fc0c3395813fe21538d52b64b76248c551dd7`. No C5 firmware flash needed.

