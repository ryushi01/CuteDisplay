# CuteDisplay: ESP32-S3 brain + LILYGO C5 face — proposed pinout

> **Status 2026-10-27:** S3↔C5 UART is LIVE and tested, including a successful S3-delivered C5 v1→v2 firmware upgrade, reboot and working Kitty/iPhone app. **Audio GPIOs are proposed and NOT yet electrically/firmware tested.** Diagram is a netlist, not an exact physical breadboard placement. Verify your Freenove model and silk-screen labels before wiring; audio I²S code is not currently active.

![Proposed S3 + C5 breadboard wiring](cutedisplay-s3-c5-breadboard.svg)


## Next milestone: local record → playback, before AI networking

**Board identification gate:** this pinout assumes the Freenove FNK0085/FNK0085B ESP32-S3-WROOM CAM style board already in our project. **Do not transfer it blindly to FNK0102 or other Freenove S3 variants**, which may contain onboard microphone/amplifier/LCD and assign GPIO41/42/1 differently. Compare your actual silk-screen, camera/SD attachments and schematic. GPIO41/42 may conflict with optional external JTAG; use USB-JTAG, and keep GPIO19/20, 47/21 UART and camera/SD/PSRAM pins reserved. Physical 3V3/5V header output current and header availability are not yet established.

**Current approved candidate audio wiring — S3 only (C5 receives no audio wires):**

| Net | S3 terminal | Audio endpoint |
|---|---|---|
| Shared I²S BCLK | GPIO41 output | INMP441 SCK **and** MAX98357A BCLK |
| Shared I²S WS/LRCLK | GPIO42 output | INMP441 WS **and** MAX98357A LRC |
| Microphone serial data | GPIO1 input | INMP441 SD/DOUT |
| Speaker serial data | GPIO2 output | MAX98357A DIN |
| Microphone power | verified S3 3V3 | INMP441 VDD |
| Mic channel select | GND | INMP441 L/R (left) |
| Amplifier power | verified appropriately rated supply 3.3–5V per breakout | MAX98357A VIN/VCC |
| Shared reference | GND | both modules GND + S3/C5 GND |
| Speaker | not connected to GPIO | amplifier SPK+ and SPK− to 8 Ω / 1 W speaker |

**Risk review / precautions:**

1. **Never put 5 V on INMP441 or any GPIO.** Verify amplifier breakout VIN rating and 5V availability/current; a 3.3V amp supply may be suitable for low-volume initial tests if it can handle current. Do not assume a breadboard rail is continuous; measure first.
2. **MAX98357A speaker outputs are bridge-tied:** connect the speaker across SPK+ and SPK− only; **SPK− must never be grounded**. Limit output gain/PCM amplitude: at 5V the module could exceed the 1W speaker rating. Leave GAIN at breakout default only if tested at low level; check SD/enable default and channel selection on your exact module.
3. **Shared I²S clocks mean full-duplex compatibility must be tested:** microphone and amplifier need matching BCLK, WS, sample rate, slot width and correct microphone left-channel extraction/shift. Use an ESP32-S3 I²S full-duplex capable driver configuration, or prove compatibility before enabling both together. Initial test can record to RAM/PSRAM and then play back sequentially, not simultaneous, but ensure clock and driver reconfiguration are correct.
4. **Audio noise and radio interference:** keep mic data and clock wiring short, avoid long unscreened speaker leads adjacent to the microphone. Keep BLE and Wi-Fi as-is for baseline; audio quality with simultaneous radio traffic is a later gate, not a reason to remove Bluetooth.
5. **S3 power headroom:** speaker peaks can sag USB 5V or 3V3 and reset the S3/C5. Test modest volume with a suitable USB supply. Never bridge two USB 5V power sources through the boards.
6. **Firmware remains unchanged in this wiring-only commit.** No claim of successful recording, DAC playback, echo cancellation, OTA or streaming audio. UART OTA already tested and must remain functional. No wiring on C5 I²S pins: its GPIO1/6 are already dedicated to UART.

**Recommended first functional test:** power OFF and wire mic + amplifier + speaker as above; verify continuity/voltages and that Kitty/phone still work; then use a dedicated S3-local test that captures 2–3 seconds of mono PCM at 16 kHz, stores it in RAM/PSRAM, and plays it at low output gain. Inspect the S3 USB Serial Monitor for I²S initialization, nonzero microphone levels, playback completion and resets. Only after passing local record/playback should we add a UI trigger, buffering during Wi-Fi/BLE, STT/TTS or server processing.

Manufacturer references: [Freenove FNK0085 camera pin map](https://docs.freenove.com/projects/fnk0085/en/latest/fnk0085/codes/Python/Preface.html), [Adafruit MAX98357 speaker/output guide](https://learn.adafruit.com/adafruit-max98357-i2s-class-d-mono-amp), [Freenove FNK0102 alternate onboard audio pin map](https://docs.freenove.com/projects/fnk0102/en/latest/fnk0102/codes/Main/Preface.html).

## Connectivity decision

- **Bluetooth Low Energy remains enabled permanently as an intended feature on the S3** for first-time iPhone provisioning and local settings/control. Do not redesign as Wi-Fi-only merely because Wi-Fi audio and BLE may coexist.
- **Wi-Fi on S3** serves the separate AI backend (OpenAI or self-hosted Ollama/Open WebUI, STT and TTS). Audio capture/playback are on the S3; heavy AI processing stays on the server.
- **Wired UART** carries text, mood, animation commands and battery telemetry between S3 and C5. The C5 stays autonomous for LCD rendering. **Camera use is deferred, but its pins are reserved.**
- **Transition:** the current iPhone app still talks to C5; the S3 BLE diagnostic service `FFF0`/`FFF1` is *not yet* a functional replacement. Do not cut off C5 BLE until UART relay, telemetry and iOS migration pass end-to-end tests.

## Current UART assignment and proposed audio signals

**UART GPIOs reflect the individual successful S3 and C5 loopback tests**; inter-board testing is next. Audio assignments remain candidates. They avoid the commonly documented Freenove camera, SD and octal-PSRAM pins. GPIO41/42 overlap the ESP32-S3's optional external JTAG functions; do not enable external JTAG on these pins. The S3 package's USB-JTAG through GPIO19/20 is left untouched. Check breakout availability on the *specific* FNK0085B and any on-board peripherals before declaring the wiring final.

| Net | Freenove ESP32-S3 | Module or LILYGO T-Display-C5 | Direction |
| --- | --- | --- | --- |
| I²S BCLK | **GPIO41** | INMP441 **SCK** + MAX98357A **BCLK** | S3 → both |
| I²S WS/LRCLK | **GPIO42** | INMP441 **WS** + MAX98357A **LRC** | S3 → both |
| I²S microphone data | **GPIO1** | INMP441 **SD/DOUT** | Mic → S3 |
| I²S speaker data | **GPIO2** | MAX98357A **DIN** | S3 → amplifier |
| UART control to face | **GPIO47 TX** | LILYGO **GPIO1 RX** | S3 → C5 |
| UART telemetry from face | **GPIO21 RX** | LILYGO **GPIO6 TX** | C5 → S3 |
| UART reference | **GND** | LILYGO **GND** | Shared ground |
| Microphone supply | Regulated **3V3** | INMP441 **VDD** | 3.3 V only |
| Microphone channel | **GND** | INMP441 **L/R** | Left channel |
| Amplifier supply | Rated **5V/VIN** if verified on actual board | MAX98357A **VIN** | Never via S3 GPIO |
| Audio ground | **GND** | INMP441 **GND**, MAX98357A **GND** | Shared ground |
| Speaker | MAX98357A **SPK+ / SPK−** | 8 Ω speaker pair | Direct output; never ground SPK− |

**Physical wiring:** For bring-up, power S3 and C5 separately over their USB inputs and connect the **two UART signal wires and common GND** between boards. Never connect both positive rails together. The S3 and LILYGO GPIOs use 3.3 V logic; don't feed 5 V into a GPIO. Connect the amplifier only after confirming the available 5 V header output and power distribution. The ELEGOO breadboard supply rails may be split or disconnected from one another—continuity-test before relying on them.

## Conflict review — preserved for future camera support

| Reserved hardware | ESP32-S3 GPIOs to avoid |
| --- | --- |
| Camera | **4–13, 15–18** (GPIO14 not included in this camera mapping) |
| Onboard microSD | **38, 39, 40** |
| Octal PSRAM / flash routing | **33–37** and other flash-connected pins **26–32** |
| USB Serial/JTAG | **19, 20** |
| Strapping / boot-sensitive | **0, 3, 45, 46** |
| UART0 debugging | **43, 44** (not used here) |
| External JTAG alternatives | **39–42**, hence 41/42 are only valid when not using that JTAG mode |

Manufacturer pin mappings and board variants can differ. Confirm against the Freenove `FNK0085` documentation and the board's printed labels. For C5, the built-in LCD already uses GPIO26/7/9/8/23/25, AXP2602 uses 2/3 and interrupt 10, button uses GPIO0; the new UART GPIO6/1 avoid those known firmware reservations and passed a direct C5 loopback (TX6 → RX1); earlier GPIO4/5 did not receive due to a bad contact.

Sources:
- [Freenove FNK0085 manufacturer documentation](https://docs.freenove.com/projects/fnk0085/en/latest/)
- [ESP32-S3 datasheet — GPIO matrix and reserved-function constraints](https://documentation.espressif.com/esp32_s3_datasheet_en.pdf)
- [Freenove-compatible camera and SD map cross-check](https://github.com/jaysys/esp32s3-with-camera-ov2640-and-sdcard/blob/main/pinmap.md)
- [LILYGO T-Display-C5 quick start and display pins](https://wiki.lilygo.cc/products/t-display-series/t-display-c5/quick-start)

## Implementation stages and safety gates

1. Compare exact header pin labeling to the table, verify power, and run a standalone **UART TX/RX cross-link** at **115200 8N1**. Implement framing, command checksums/length limits, ACK and a `HELLO` handshake before routing live app commands.
2. Verify battery telemetry and saved display settings through S3; keep C5's BLE recovery path until successful.
3. Wire the INMP441/MAX98357A on the S3 pins above and verify microphone capture and speaker playback **without** network traffic.
4. Add Wi-Fi speech streaming and measure audio under simultaneous BLE configuration traffic. Prefer fixing buffering, task scheduling and traffic load **before** considering Wi-Fi-only operation; BLE is needed for initial provisioning.
5. Integrate the independent AI backend. Defer onboard camera and optional Waveshare display migration until measurements support them.

The S3 pin constants are documented in [`firmware/CuteDisplayBrain/BrainPinPlan.h`](../../firmware/CuteDisplayBrain/BrainPinPlan.h). UART is initialized in both main sketches; I²S remains inactive. The complete power-safe UART flash/monitor checklist is in [uart-bringup.md](uart-bringup.md).

[README](../../README.md) · [Historical retired LILYGO C5 audio guide](lilygo-c5-audio-breadboard.md)
