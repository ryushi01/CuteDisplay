# CuteDisplay — Project Handoff / Resume Here

**Last updated:** 2026-10-26  
**Repository:** https://github.com/ryushi01/CuteDisplay  
**Default branch:** `main`  
**Purpose:** Durable context to resume engineering in a new ChatGPT conversation without access to previous chat history. **This document tracks plans separately from tested/working features.**

## FIRST: what to do in a new chat

Tell the assistant:

> Please read `docs/PROJECT_HANDOFF.md` and `README.md` from `https://github.com/ryushi01/CuteDisplay`, then review the current `main` firmware and iOS source. Continue CuteDisplay from the recorded implementation status. Do not assume untested features are working, and use the linked GitHub connector to commit changes when requested.

Read the actual repository before making code changes because this document can become stale.

## BLE pair failure observed — 2026-10-26, fix source pending test

User reports iPhone `ERR:NOT_READY` and S3 NimBLE default callback `Authentication failed with status 1288` (0x0508, **peer unspecified pairing failure**); logs also include **older S3 startup messages** (`BLE proxy starts disabled (proxy on)`) absent from later GitHub firmware, implying an old build or mixed boots. Do not infer a specific pairing failure root cause from 0x0508 alone.

New S3 source exposes banner `Phase4-BLEPAIR-FIX1-20261026`, implements both NimBLE authentication callback signatures to report failed pairing status, and introduces USB-only `ble bonds clear` for NimBLE when disconnected. Old phone authorization/bond needs to be removed on iPhone as well, then re-paired. iOS `BluetoothManager.swift` now waits until FFF1 actual `PROXY_READY` rather than assuming a protected read alone means the S3 command relay is active. C5 firmware **unchanged** in this targeted fix. All code **uncompiled/unverified**, preserve encrypted GATT permissions and ensure S3↔C5 UART baud is matched. See [1288 failure recovery](hardware/ble-pairing-1288.md).

## Latest source — 2026-10-26 Phase 4 persistent UART-link popup & 921600 baud (NOT TESTED)

At user's request, the C5 LCD now draws a **persistent opaque BRAIN DISCONNECTED** foreground pop-up from startup / after **6 seconds with no valid S3 UART frames**. It is composited after mascot, text, battery, Wi-Fi, and connection HUD, so nothing hides it. A new valid CRC-checked S3 frame causes the C5 loop to redraw immediately and **remove** the warning. The message indicates the physical UART Brain/Face connection only; iPhone BLE connection and S3 Wi-Fi are separate indicator states. C5 BLE and C5 Wi-Fi remain **OFF**. GPIO0 long hold still toggles only **S3 Wi-Fi** via UART.

UART settings on **both** boards changed from 115200 to **921600, 8N1**, with **2K receive + 2K transmit driver ring buffers**, 1 buffered frame write instead of many print calls, more frames drained per loop, and BLE UART hex command segments now **45 bytes** (90 hex digits). `CuteLink.h` was updated **identically** for both boards; S3 source uses `BrainPinPlan.h` for UART_BAUD=921600; C5 uses the matching literal 921600. **No wire/pin changes:** S3 TX47→C5 RX1, C5 TX6→S3 RX21, common GND. **USB Serial Monitor remains 115200.** 921600 is an increased serial bitrate, **not** proof of maximum UART/BLE throughput; bench reliability/CRC/loss and supply brownouts unverified. If line errors occur, roll back **both** boards to 115200 or change both settings to 460800. **Both firmwares MUST be flashed as a pair** or the UART stays disconnected. Source has NOT been compiled, flashed or tested yet.

The user's previous app errors, security and queue-flooding repair notes remain in older sections. iOS source from Phase 3 is unchanged by Phase 4; for the **full source bundle**, download GitHub commit archive with both Arduino sketch folders (including headers), the complete iOS app source, docs and diagrams. See [Phase-4 pop-up/fast UART test](hardware/brain-link-921600.md).

## Latest field failure and repair — 2026-10-26 (NOT YET RETESTED)

User tried the earlier Phase-3 firmware/app on physical S3+C5 and reported iPhone BLE apparently connecting, but error **"Send failed: authentication is insufficient"** on commands; message, mascot settings and S3 Wi-Fi setup would not work. Subsequent S3 logs:
```text
[C5] STATUS lcd=1;ble=1;wifi=0;soc=100
[S3] WARNING: command queue full; BLE write not delivered
[S3] C5 UART connected
[C5] STATUS lcd=1;ble=0;wifi=0;soc=100
[S3] Face UART timed out
```
The early S3 firmware's `FFF1` permissions required encryption, but the Brain had not initiated pairing reliably or enabled the proxy automatically. Independently, the SwiftUI app interpreted GATT **write-with-response** as C5 command success, so multi-packet glyph and settings uploads flooded S3's UART queue even when the proxy was disabled. The C5-to-S3 UART timeout implies >10 seconds without valid inbound frames and is **not proven to be only queue-related**: possible reset, poor jumper, power/brownout or processing stall. Do not claim a proven root cause for the UART silence from these logs alone.

**Current source changes awaiting Arduino/Xcode and hardware testing:** S3 initiates BLE secure connection on connect (Bluedroid/NimBLE), listens for security-complete event, enables FFF1 bridge automatically for **each bonded/encrypted session**, creates notification CCC descriptors and refuses BLE writes while not ready. Swift `BluetoothManager` reads protected FFF1 first, subscribes to its notifications and **waits for ACK:CMD/ACK:WIFI or ERR** before sending the next command; legacy C5 direct GATT (without FFF1 notify) still uses old write callbacks for recovery builds. S3 UART command queue is now 16 bounded slots (not 256) with explicit ERROR on overflow, and both S3/C5 UART RX software buffers are 2048 bytes. The C5 ACKs after processing commands; S3 logs silence and invalid frames if the UART stops. No automatic replay after iOS ACK timeout; old UI queue is cancelled on error.

**New requested feature:** C5 GPIO0 1.4-second long-press sends `WIFI_TOGGLE` to Brain by UART, S3 turns its **own** Wi-Fi on/off and sends `WIFI_STATE` feedback to the LILYGO. If no network has been set on S3, LILYGO displays **SET WIFI IN APP**. The C5 radio remains disabled even when the button is held. HUD status, S3 Wi-Fi credentials and S3-only BLE remain the architecture.

**Next test, one item at a time:** (1) reflash S3+C5 and build/install matching Swift code, repair old iPhone pairing if needed, confirm app "Connected securely" and send a single `C:1`; (2) send a message/Japanese glyphs to confirm queue pacing; (3) configure S3 Wi-Fi and test C5 button toggle + icon/IP; (4) if timeout still happens, capture complete S3 logs including `bad_frames` and test separate USB with the shared 5V jumper removed. Git reference Phase 2 known-good recovery baseline: `f2e352c3ccb9bf3e4487c41cb3e2de5d6c3fdf5d` (C5 BLE reenabled when reflashed). Do not replace/erase NVS unless deliberately resetting bonds.

## Latest engineering update — 2026-10-26 Brain owns BLE/Wi-Fi, C5 radios DISABLED (UNTESTED BETA)

Per explicit user request, the new Phase-3 firmware makes the ESP32-S3 the **only wireless controller**: C5 does not initialize Bluetooth, connect to Wi-Fi, or start its old LAN server. UART W: commands sent to the C5 are rejected, and the long-press GPIO0 Wi-Fi toggle no longer enables C5 radio. S3 now manages Wi-Fi credentials, DHCP/static IP, station connection and Wi-Fi telemetry; S3 BLE FFF0/FFF1 is encrypted/Just Works bonded and exposes C5 power/battery over 180F/2A19 and FFF3/FFF4 plus **S3's own** Wi-Fi data over FFF5/FFF6. S3 broadcasts `RADIO` b/w/IP frames to C5 every ~1.8 seconds. C5 top-right Bluetooth/Wi-Fi indicators and physical-button status overlay display **the real S3 BLE-client & S3 Wi-Fi station** state and S3 IP; when S3 status is missing/offline, both icons show disconnected (never fall back to C5). C5 battery is still physically measured on C5. Existing Kitty and all other display behavior intended unchanged.

**CRITICAL MIGRATION CHANGE:** Direct LILYGO BLE recovery is intentionally **disabled** in the new C5 build. To recover from a failed S3 connection, **reflash the earlier working C5 firmware over its own USB-C**, temporarily disconnecting the S3↔C5 5V jumper before plugging in a second USB. The known working Phase-2 baseline is commit `f2e352c3ccb9bf3e4487c41cb3e2de5d6c3fdf5d`. The new S3 USB `proxy on` gate is still temporary (10 minutes); Apple app has an authorized-accessory selector, and legacy C5 LAN fallback is switched off. Just Works does not protect against MITM during pairing. No Xcode project committed, so app compilation is unverified. Newly changed code **has not been compiled or flashed** as of this update.

All new Phase 3 source: S3 `firmware/CuteDisplayBrain/CuteDisplayBrain.ino`, C5 `firmware/CuteDisplay/lcd.ino`, `ios/CuteDisplay/BluetoothManager.swift`, `ios/CuteDisplay/ContentView.swift`. [Staged verification and rollback](architecture/ble-brain-proxy-beta.md). Previous proven UART pins remain S3 TX47→C5 RX1, C5 TX6→S3 RX21, common GND. Shared single S3 USB-C power has been observed to boot both but lacks proven current/backfeed rating. Do not connect C5 USB while power rails are linked.

## Latest hardware verification — 2026-10-26 UART idle heartbeat works

User explicitly confirmed **"it works"** after flashing the latest S3 and C5 sketches containing the phase-2 idle keepalive fix (commit `f2e352c`). Treat the **3-second S3 HEARTBEAT accepted silently by C5** as user-tested on the running two-board prototype; the preceding repeated HELLO/reconnect symptom is considered resolved by this report. No new Serial Monitor transcript was supplied for the heartbeat verification, and prolonged stress/resets were not measured.

Current baseline: S3 Brain USB-C ↔ S3 5V output to LILYGO 5V header (user-reported working single-USB prototype only; electrical path/current/backfeed *not certified*); S3 GPIO47 TX → C5 GPIO1 RX, C5 GPIO6 TX → S3 GPIO21 RX, common GND. LILYGO's separate USB-C must stay unplugged with shared 5V connected. BLE diagnostic `C:1` write → S3 UART MASCOT → C5 ACK had already been verified. Existing iPhone app connects directly to C5 and must remain usable.

**Next engineering sequence:** 1) secure/authorize S3 BLE onboarding instead of relying on the unauthenticated five-minute diagnostic gate, 2) reliable framed UART commands and receipt/response tracking with reset/state synchronization, 3) UTF-8 Japanese/French text and glyph packets, 4) mirror C5 battery/power/Wi-Fi telemetry through equivalent S3 BLE services, 5) stage iPhone app selection of S3 while retaining direct C5 recovery BLE. None of those features are confirmed implemented. Keep the current working firmware pair as a recovery baseline before changing protocol, and do not add audio/AI loads until single-USB power is rated/verified.

## Latest test report — 2026-10-26 BLE-to-UART succeeds; C5 idle reconnect explained and fix committed

**New user-confirmed result:** After installing the Phase-2 BLE S3 sketch and keeping the previously working C5 display firmware, the user supplied S3 USB monitor logs:
```text
[C5] seq=342 STATUS lcd=1;ble=1;wifi=1;soc=100
[C5] HELLO
[C5] seq=345 LOG C5 connected
[S3] BLE test forwarded MASCOT seq=2
[C5] seq=2 ACK MASCOT
[S3] BLE relay result: ACK MASCOT
[S3] BLE test forwarded MASCOT seq=3
[C5] seq=3 ACK MASCOT
[S3] BLE relay result: ACK MASCOT
```
This **confirms basic Bluetooth write → S3 → UART → C5 accepted MASCOT command and C5-to-S3 ACK**. The user says other tests seem to work but provided no complete outputs, so do not mark all app functions, Unicode or battery proxy verified. The link's repeated idle `HELLO` / `LOG C5 connected` is explained by C5's 10-second **inbound** UART timeout: C5 sends status every 5 seconds, but that does not refresh its last-S3-receive timestamp when S3 is idle. This is a firmware keepalive issue, not necessarily loose wiring or a board reboot. **New untested firmware commit** now makes S3 send a silent `HEARTBEAT` frame every 3 seconds while online, and C5 accepts it without ACK, preventing spurious C5 reconnects. Both sketches must be reflashed to test this improvement. The previous hardware-verified pins S3 TX47/RX21 ↔ C5 RX1/TX6, common GND, are unchanged.

## Latest development — 2026-10-26 Phase 2 BLE test relay / single-USB observed

After confirming UART and `msg Hello from Brain`, the user reconnected S3 5V → C5 5V power (with common ground and verified UART TX/RX) and reported **both boards work with only the S3 USB-C powered**. This is a boot/operation observation; no current capacity, regulator heat, voltage stability, backfeed behavior or battery charger interactions have been electrically verified. The C5's USB input must remain unplugged while the two 5V pins are joined. Do not treat as permanent power-design validation.

The **S3-only Phase 2 BLE test relay source** now uses `ble on` / `ble off` USB Serial Monitor commands to enable an **unauthenticated five-minute gated** relay from S3 `FFF0/FFF1` BLE diagnostic writes to existing UART `TEXT`, `MASCOT`, `MOOD` commands. Allowed: plain printable ASCII text (≤80 bytes, no colon/pipe), `C:0..5`, `M:0..7`; all other (including Wi-Fi credentials, power and glyph uploads) rejected. One in-flight UART response at a time, 3-second ACK/NACK timeout and no automatic retries. **New code not compiled/flashed/hardware tested yet**. C5 firmware, working pinout and native iPhone app unchanged. S3 BLE remains non-authenticated and is **NOT** a full iPhone proxy. [Phase 2 instructions](hardware/ble-relay-test.md). The next work is secure pairing, UART robustness, UTF-8 glyph transport and battery/network service proxy, then app migration.

## Latest status — 2026-10-26 two-board UART HELLO, status and display command verified

User flashed the previous S3 BLE diagnostic and confirmed its serial boot/advertising logs; user reports flashing current C5. S3 USB → C5 power booted both, but C5 USB → S3 lit power while S3 failed to boot. This is not a current-path safety rating, so user chose **separate USB supplies** for development and no 5V positive jumper. Do not power two USB supplies into common 5V rails.

**Current phase-1 source:** both Arduino firmware folders contain `CuteLink.h`; S3 UART1 GPIO47 TX/GPIO21 RX and USB console (help/status/ping/battery/msg/mood/mascot); C5 now uses UART1 **GPIO6 TX/GPIO1 RX** (previous GPIO4 TX/GPIO5 RX retired), HELLO/ACK and diagnostics. S3 original phase-1 sketch and original C5 phase-1 sketch were flashed and booted. **Independent UART loopback verified on both boards:** S3 physical jumper GPIO47↔21 echoed its own HELLO/ACK; C5 physical jumper GPIO6↔1 repeatedly showed matching TEST_18 through TEST_22 TX/RX. Earlier TX-only behavior was traced to bad contact at the C5 header and user had to press connector firmly. **VERIFIED END-TO-END on physical S3/C5 (2026-10-26):** User flashed pin-updated integrated C5 firmware, connected S3 GPIO47 TX → C5 GPIO1 RX; C5 GPIO6 TX → S3 GPIO21 RX; GND → GND, with separate USB power and no 5V jumper. S3 USB serial displayed real `[C5] HELLO`, `[C5] seq=51 LOG C5 connected` and periodic `[C5] seq=48 STATUS lcd=1;ble=1;wifi=1;soc=100` (also seq=49,50,52). From S3 USB Serial Monitor user sent `msg Hello from Brain` and saw that exact text on the LILYGO screen. This confirms bidirectional UART and text-command handling; not yet proof of reliability under resets or Wi-Fi/AI workloads. **Do not rewire or reassign the known-working GPIOs without reason.** iPhone still connects straight to C5; S3 BLE service remains diagnostic only. Use [UART bring-up guide](hardware/uart-bringup.md). No robust retries, Japanese glyph UART, C5 battery BLE proxy, iPhone migration or AI/audio/camera.

## Product goal

Build a cute, multilingual (English/Japanese/French), animated, compact AI companion. Kitty/mascot remains on the **right side** of the LILYGO screen, with user messages/AI text readable elsewhere. Smooth, expressive mood-aware animations and accessories are a priority. Keep response text, BLE configuration, battery status, reconnection behavior and existing appearance controls working. The AI backend can be OpenAI or a separate user-hosted CPU-only Ollama/Open WebUI server (STT/TTS off-device). Camera support is **postponed**, not abandoned.

## Hardware and chosen architecture

**LILYGO T-Display-C5 / ESP32-C5 — FACE:**
- Integrated 320 × 170 LCD; autonomous mascot animations, messages, Japanese glyph handling, battery readings, local GPIO0 controls, display preferences.
- **Historical verified Phase-2 firmware** had direct C5 BLE and Wi-Fi; **new Phase-3 build disables both**. UART control from S3 remains.
- Old INMP441/MAX98357A I²S audio loopback and GPIO28 long-press test have been **removed** from its firmware.
- Future S3 UART commands should tell C5 *what* to display and animate; do not stream LCD framebuffers over UART.

**Freenove ESP32-S3-WROOM CAM N16R8 (FNK0085B expected) — BRAIN:**
- Future iPhone BLE pairing, onboarding and local control. **Bluetooth stays in the design** even if Wi-Fi is used for AI/audio; remove BLE only if explicitly reconsidered following measured failures, not preemptively.
- Wi-Fi to external AI services, I²S microphone INMP441 and MAX98357A + 8 Ω/1 W speaker, orchestration and audio buffering.
- Onboard camera exists but **no camera wiring, software or tests in current stage**.
- Experimental S3 sketch `firmware/CuteDisplayBrain/CuteDisplayBrain.ino` advertises `CuteDisplay-Brain-DEV` over BLE service `FFF0`, characteristic `FFF1`; it **does not** run UART relay, I²S recording/playback, AI, phone migration or camera. It is a diagnostic starting point, not a deployable brain.
- A separate Waveshare 1.9-inch ST7789V2 screen was considered for possible later *single-board* migration, ONLY if benchmarks show S3 can run everything with smooth animation; current architecture is two boards.

**iPhone SwiftUI app:** Current `ios/CuteDisplay/ContentView.swift`, `BluetoothManager.swift`, and `AccessorySetup-InfoPlist.xml`. Direct BLE to LILYGO and authenticated Wi-Fi fallback are the current working source design. S3-only BLE pairing, proxy control, status relays and AccessorySetupKit migration still need implementation. Keep LILYGO recovery connectivity until S3 bridge proven.

## Repo source files

- `firmware/CuteDisplay/lcd.ino` — existing face firmware. Historical Drinks Mode already removed in source and previously confirmed working; audio loopback code removed. LCD renderer, BLE, Wi-Fi, moods, battery remain.
- `firmware/CuteDisplayBrain/CuteDisplayBrain.ino` — *incomplete* S3 BLE diagnostic sketch; source not independently compiled/flashed.
- `firmware/CuteDisplayBrain/BrainPinPlan.h` — proposed signal constants only, not active peripherals.
- `ios/CuteDisplay/ContentView.swift`, `ios/CuteDisplay/BluetoothManager.swift` — current app; no S3 migration yet.
- `docs/hardware/s3-c5-breadboard-plan.md` — proposed hardware signals, reserved GPIOs, and physical verification checklist.
- `docs/hardware/cutedisplay-s3-c5-breadboard.svg` — **multi-board wiring topology** displayed in README; not an exact hole-by-hole breadboard layout.
- `docs/hardware/option1-lilygo-powers-s3.svg` — **power-only experimental plan**, not approved until LILYGO 5V path verified.
- `docs/architecture/cutedisplay-dual-board.svg` — overall architecture.
- `docs/hardware/lilygo-c5-audio-breadboard.md` and `docs/hardware/cutedisplay-c5-audio-wiring.svg` — **retired/historical ONLY**; do not follow for new hardware build.

## Proposed wiring: UART + audio — NOT yet bench-verified

| Function | S3 | Other end |
| --- | --- | --- |
| UART S3 sends display commands | GPIO47 TX | LILYGO GPIO1 RX |
| UART C5 sends status | GPIO21 RX | LILYGO GPIO6 TX |
| UART shared reference | GND | LILYGO GND |
| I²S bit clock | GPIO41 | INMP441 SCK and MAX98357A BCLK |
| I²S word select | GPIO42 | INMP441 WS and MAX98357A LRC |
| Audio microphone input | GPIO1 | INMP441 SD |
| Audio amplifier output | GPIO2 | MAX98357A DIN |
| Mic power | 3V3 + GND | INMP441 VDD + GND; L/R grounded |
| Amp power | Verified rated supply (often 5V) + GND | MAX98357A VIN + GND |
| Speaker | MAX98357A SPK+/SPK− | 8 Ω speaker directly; never connect SPK− to ground |

These choices avoid documented S3 camera GPIO4–13,15–18, SD GPIO38–40 and octal PSRAM/flash pins. GPIO41 and GPIO42 are usable through the GPIO matrix but conflict with optional external JTAG functions. **Check exposed pin labels and any onboard peripheral assignment on exact Freenove board** before connecting.

LILYGO GPIO6 (TX) and GPIO1 (RX) are now selected after an actual local UART loopback pass; the original GPIO4/5 test produced TX-only output with poor jumper contact. Both S3 GPIO47/21 and C5 GPIO6/1 have passed standalone loopbacks, but the combined link still requires testing. Existing C5 LCD GPIO26/7/9/8/23/25, battery I²C 2/3/10, and GPIO0 user button must remain untouched.

**Basic phase-1 UART diagnostics are now physically VERIFIED end-to-end for HELLO/STATUS and one `TEXT` command.** Versioned bounded frames, CRC8, sequence ACK, HELLO, status/battery, ASCII console tests exist. Reliable retries, Japanese glyph chunks, BLE proxy and reconnection sync are not implemented. Do not migrate iPhone pairing yet.

## Current FIRST physical experiment: Option 1 — ONE USB-C ON LILYGO

![Power-only proposed test](hardware/option1-lilygo-powers-s3.svg)

Desired experience: Plug **one USB-C cable into the LILYGO** and let its 5V header also feed the S3. **Only two inter-board power wires for the FIRST test**, without UART, microphone, amp, speaker or camera:

| Source — LILYGO T-Display-C5 | Destination — Freenove S3 |
| --- | --- |
| **5V header** (candidate outgoing supply) | **5V/VIN header** (input; check pin label) |
| **GND** | **GND** |

**CRITICAL SAFETY GATE — DO NOT CONNECT S3 POWER YET JUST BECAUSE PINS SAY 5V.** We have NOT verified the LILYGO 5V header's current capacity or exact USB-VBUS current-limited/protected power path, nor backfeed behavior when programming S3 separately. A 5V voltage reading alone does **not** prove it can safely support the S3's Wi-Fi peak current. A large external USB adapter does not prove the LILYGO PCB's path can handle the extra load. Obtain the actual schematic/current ratings or manufacturer assurance and verify with measurement before powering the S3 via the C5. If capacity cannot be established, use two separate USB inputs temporarily or a protected single-input distribution board instead. Avoid bonding 5V/3V3 outputs from different regulators; no accidental positive-rail bridges. Only power/ground for initial test, with all other modules unplugged. When connecting UART later, mind unpowered-IO backfeeding.

The user expects their S3 board to arrive **2026-10-26** and wants to start with this power experiment. Before giving them specific pin positions, compare exact board photos and printed pin labels to the manufacturer schematic; the SVG is **conceptual and not a literal visual map of board connector orientation**.

### Why Wi-Fi + BLE is retained

BLE stays for onboarding, pairing, local settings and recovery; Wi-Fi connects the external AI backend. Streaming audio dropouts from BLE/Wi-Fi coexistence are a possible performance issue, **not an established problem**. Plan dedicated I²S DMA buffers, bounded task scheduling, ring buffers and robust networking; stress-test under simultaneous BLE before considering a Wi-Fi-only *operating mode*. The future app should be able to configure Wi-Fi over BLE.

## Validated vs pending

**Previously reported working by user:** Existing LILYGO display/iPhone integration, BLE reconnection/battery, animations, Drinks Mode removal. Actual firmware source changed to remove C5 I²S voice code, but no independent compile or physical regression test was performed here.

**Not validated or incomplete:** robust UART recovery/retries and UTF-8/Japanese glyph transfer (basic S3↔C5 bidirectional UART is verified); S3 Bluetooth pairing/proxy from iPhone; I²S mic/speaker; simultaneous BLE/Wi-Fi/STT/TTS; camera; Waveshare migration; long-term physical header security and **Option 1 single-USB-C power path rating**.

## Engineering order to resume

1. **Power-path safety verification:** inspect S3 board and LILYGO labels + C5 VBUS-to-5V schematic/current rating. Only then power-only Option 1 test, or choose safe parallel supply.
2. **UART:** bring up TX/RX/GND, establish framing, restore display state, send iPhone commands through S3, report C5 telemetry.
3. **BLE app migration:** retain BLE on S3 for first-time configuration (and leave legacy C5 recovery BLE until new stack proven).
4. **S3 mic/amplifier:** compile local I²S record/playback with correct S3 GPIOs and tested supply.
5. **External STT → selected AI → TTS** and synchronized mascot animations.
6. **Benchmark Wi-Fi/BLE/audio**, then consider camera and optional alternate LCD.

## Requirements for code contributions

- Commit actual files to `main` when user asks; do not report pushed work without GitHub confirmation.
- Preserve working LILYGO mascot rendering, right-side character placement, Japanese text, BLE and battery behavior.
- Never accidentally reactivate removed Drinks Mode or former LILYGO audio loopback.
- Do not replace the iOS app with a hypothetical stub: its full Xcode project is not in this repo, only Swift source and Info.plist fragments.
- Distinguish documented intended pinout from electronically tested layout; never assert that the proposed power supply is safe without proof.
- Update this document whenever architectural decisions or milestone status change.
