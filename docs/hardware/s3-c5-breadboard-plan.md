# S3 brain + LILYGO face — breadboard integration plan

**Status: planned, not yet electrically assembled, compiled or tested.** This document describes the *new* ELEGOO 830-point breadboard concept. It supersedes the old LILYGO I²S wiring reference. Camera connectivity is intentionally **out of scope for this phase**.

![Two-board breadboard concept](cutedisplay-s3-c5-breadboard.svg)

## Current responsibilities

| Component | Responsibility now | Intended next stage |
| --- | --- | --- |
| LILYGO T-Display-C5 | Existing mascot/display, messages, battery, BLE and Wi-Fi continue unchanged | UART display/text renderer; battery telemetry back to S3 |
| Freenove ESP32-S3-CAM N16R8 | New independent BLE diagnostic sketch: `firmware/CuteDisplayBrain/CuteDisplayBrain.ino` | iPhone BLE endpoint, UART bridge, Wi-Fi gateway, I²S mic/amp |
| INMP441 | Not yet assigned S3 pins | I²S digital microphone at 3.3 V |
| MAX98357A and 8 Ω speaker | Not yet assigned S3 pins | I²S speaker output, power budget to be measured |
| iPhone app | Still connects to LILYGO C5 | S3 BLE pairing only after full bridge and telemetry support |
| External AI backend | Separate server | OpenAI or Ollama with speech recognition and synthesis |

## Electrical connection matrix — signals, not final GPIO numbers

| Source | Destination | Requirements |
| --- | --- | --- |
| S3 **TX** (available UART GPIO TBD) | LILYGO **RX** (available UART GPIO TBD) | 3.3 V logic, cross-connected |
| LILYGO **TX** (available UART GPIO TBD) | S3 **RX** (available UART GPIO TBD) | 3.3 V logic, cross-connected |
| S3 **GND** | LILYGO **GND** | Mandatory common reference, even with independent USB power |
| S3 **I²S BCLK** GPIO TBD | INMP441 **SCK** and MAX98357A **BCLK** | Shared clock |
| S3 **I²S WS** GPIO TBD | INMP441 **WS** and MAX98357A **LRC** | Shared word select |
| INMP441 **SD/DOUT** | S3 **I²S RX** GPIO TBD | Microphone-only input |
| S3 **I²S TX** GPIO TBD | MAX98357A **DIN** | Amplifier-only output |
| Regulated **3.3 V** | INMP441 **VDD** | Never feed 5 V to mic |
| Verified amplifier supply | MAX98357A **VIN** | Check module rating, regulator and total USB current budget |
| Common **GND** | Mic and amplifier **GND**; mic **L/R** | L/R grounded selects left channel |
| MAX98357A **SPK+**, **SPK−** | Speaker terminals | Neither terminal to GND |

### Before connecting

1. Confirm **exact board** is Freenove FNK0085B / ESP32-S3 N16R8 and identify its exposed GPIO header orientation from the manufacturer's pin diagram.
2. Reserve all camera-connected GPIOs now, even though camera firmware is deferred; avoid flash/PSRAM/USB/boot-strapping pins and assign UART and I²S from free breakout pins.
3. Confirm LILYGO accessible TX/RX pin locations, and ensure those contacts are **not in use by LCD, AXP2602, buttons or other board hardware**.
4. Power both boards from their **own USB-C connectors** for first tests; join **GND only** between boards and cross TX/RX. **Do not bridge 5 V outputs or different 3.3 V regulators.**
5. First test UART packets and display behavior. Then add mic and amp with their own verified power and pin mapping.
6. Treat diagram as **topology/concept**, not a hole-by-hole placement or completed pin assignment. The final pin map belongs in this document once checked.

## Implementation and compatibility

The LILYGO firmware remains the last working **BLE/iPhone-controlled** animation and battery system, with its earlier I²S loopback removed. The S3 diagnostic sketch advertises `CuteDisplay-Brain-DEV` with BLE service `FFF0` and characteristic `FFF1`, but **does not forward commands**. The iPhone app is **not** switched to the S3 yet: it still needs UART bridge firmware plus compatible battery/telemetry and pairing migration.

UART protocol proposal: framed messages with version, sequence number, type, bounded length, UTF-8 payload, acknowledgement/timeout for settings, and bidirectional telemetry. Candidate message types are `DISPLAY_TEXT`, `SET_MASCOT`, `SET_MOOD`, `AI_STATE`, `BATTERY_STATUS`, and `DEVICE_READY`; **none of these are implemented yet**. For Japanese text, preserve/extend the existing glyph transport rather than assuming arbitrary UTF-8 fonts are available on the C5.

**Future:** assess the optional external Waveshare SPI LCD and camera on the S3 only after stable voice and UART operation, with measured heap/PSRAM and CPU headroom.

[Project README](../../README.md) · [Historical, retired C5 audio plan](lilygo-c5-audio-breadboard.md)
