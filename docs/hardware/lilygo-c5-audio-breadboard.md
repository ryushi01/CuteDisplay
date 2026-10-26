# CuteDisplay audio breadboard — LILYGO T-Display-C5 (current build)

**Status:** documented wiring and firmware GPIO assignments; **physical operation has not been verified by this repository**. Keep the last working firmware backup. This is the **current, single-board** setup; the Freenove ESP32-S3 camera board and external Waveshare LCD are reserved for later migration.

## Components

- LILYGO **T-Display-C5 V1.0**, ESP32-C5 with integrated **1.9-inch 320 × 170 landscape ST7789** display, buttons, Wi-Fi/BLE, and AXP2602 battery management.
- ELEGOO **830 tie-point / 63-column** solderless breadboard (Amazon ASIN **B06Y4KFCRJ**).
- **INMP441** I²S digital microphone breakout (3.3 V).
- **MAX98357A** I²S class-D mono speaker-amplifier breakout (power supply compatible with the specific breakout and supply design).
- **8 Ω, 1 W** speaker connected to the amplifier's **SPK+** and **SPK−** outputs.
- Dupont jumper wires and 5 V USB-C power input to the LILYGO.

## Board orientation and exact LILYGO header contacts

Place the **LILYGO screen facing upward, landscape, USB-C on the left**. The two rows of exposed **side-header holes run along the top and bottom edges** of the horizontal display. These are the physical side headers shown in the official board pinout, **not** connections to the glass LCD or buttons.

The source pin map is a **rear view with USB at the bottom**; its left column becomes the top-edge row in our intended front-view landscape layout, and its right column becomes the bottom-edge row. Check the **printed pin labels and physical orientation** before power-on; illustrated hole positions should never overrule printed labels.

**Top edge** (pin sequence from the official rear-view left header, from its top to bottom): `3V3, GPIO2, GPIO3, GPIO0, GPIO1, GPIO7, GPIO8, GPIO9, GPIO25, GPIO27, GND, 5V`.

**Bottom edge** (official rear-view right header, from its top to bottom): `GND, 3V3, TXD, RXD, GPIO4, GPIO5, GPIO6, GPIO10, GPIO23, GND, GND, 3V3`.

When the board is rotated/turned, **count from the corresponding end shown on the reference pin map**, not by assuming that pin 1 is always at the left of the screen.

## Electrical signal wiring — single source of truth

| LILYGO signal / pin | Destination |
| --- | --- |
| **GPIO1** (top-row GPIO1) | INMP441 **SCK/BCLK** **and** MAX98357A **BCLK** (shared clock) |
| **GPIO4** (bottom-row GPIO4) | INMP441 **WS** **and** MAX98357A **LRC/WS** (shared word select) |
| **GPIO5** (bottom-row GPIO5) | INMP441 **SD/DOUT** (microphone data **input** only) |
| **GPIO6** (bottom-row GPIO6) | MAX98357A **DIN** (speaker data **output** only) |
| **3V3** | INMP441 **VDD** |
| **GND** | INMP441 **GND**; INMP441 **L/R** (select left channel); MAX98357A **GND** |
| **5V/VBUS** (USB-supplied board header, if current budget permits) | MAX98357A **VIN**; do **not** use this voltage on the microphone |
| MAX98357A **SPK+** | Speaker **+** |
| MAX98357A **SPK−** | Speaker **−** — **never connect SPK− to GND** |

**Important:** microphone SD (GPIO5) and amplifier DIN (GPIO6) are **different data lines**. Multiple earlier illustrative images mistakenly joined them; **do not follow those mistaken connections**. The ESP32-C5 firmware already declares `VOICE_BCLK=GPIO_NUM_1`, `VOICE_WS=GPIO_NUM_4`, `VOICE_MIC_DIN=GPIO_NUM_5`, and `VOICE_AMP_DOUT=GPIO_NUM_6`.

## Simplest breadboard assembly

1. Leave the LILYGO's built-in LCD attached; **no display jumper wires are required**.
2. Put the LILYGO across the breadboard's center trench, **with USB-C to the left**; install properly sized male header pins if the board has only through-holes. Do not rely on a diagram's decorative wire placement.
3. Put microphone and amplifier on **different groups of columns** with separate male header pins and enough space for Dupont wires. The speaker can be beside the breadboard, attached through short leads to SPK+/SPK−; a speaker without 2.54 mm pins will not plug into solderless holes.
4. Connect three **ground** leads (mic GND, mic L/R, amplifier GND) to a shared ground node/rail and run one return to a LILYGO GND header contact.
5. Connect INMP441 VDD to the **3.3 V** header; connect amplifier VIN to the **5 V/VBUS** header **only if measured available and safely supplied**. Keep 3.3 V and 5 V separate.
6. Connect the **four** GPIO signals in the table. The two clock GPIOs each fan out to **both** I²S boards, while data pins do **not** fan out.
7. Connect the speaker only to the amplifier outputs. Inspect the hardware for power shorts before connecting USB-C.

### Breadboard power rail notes

The ELEGOO 830 has **63 columns**, two five-hole strips separated by the center trench, and four power distribution strips; **not every red/blue rail is automatically linked to the others**. Use only the rail segments needed, verify electrical continuity with a multimeter, and **never join 3V3 and 5V rails**. Speaker peak current and USB input capability must be checked; LILYGO lists a 5 V / 500 mA USB supply specification, which is **not a guarantee** that this entire current is available to an external amplifier. Start at low amplifier volume, verify supply stability, and use a properly designed separate amplifier power supply with **common ground** if needed. Avoid back-feeding the 5 V header from another USB adapter.

## Already used by the built-in LILYGO hardware

| Function | GPIO |
| --- | --- |
| LCD CS / SCK / MOSI / DC / RST / BL | 26 / 7 / 9 / 8 / 23 / 25 |
| AXP2602 bus | I²C 2 (SDA), 3 (SCL), interrupt 10 |
| User button | GPIO0 |
| Right BOOT/voice-loopback button | GPIO28 |

Do not reuse these pins for the external audio modules.

## Current software behavior and validation

- Active sketch: [`firmware/CuteDisplay/lcd.ino`](../../firmware/CuteDisplay/lcd.ino), currently labelled **4.2**.
- Hold **GPIO28** for **1.4 seconds** to trigger **two seconds** of microphone recording then local speaker playback. This is **sequential loopback**, not full-duplex voice chat.
- GPIO28 short press has no action; GPIO0 retains its existing app/status/Wi-Fi behavior.
- The real-time AI server/STT/Ollama/TTS pipeline **has not yet been implemented in the committed firmware**.
- The iPhone app is still the primary BLE controller. Wi-Fi support in firmware is separate from a completed voice AI workflow.
- Not verified here: bench fit, USB-current budget, Arduino firmware compilation, real microphone/speaker function, or echo cancellation.

### Test sequence

1. With power disconnected, verify every connection against the table and compare header labels to the official pin map.
2. Power from USB-C and verify the normal mascot/display operation, BLE and battery status.
3. At low speaker volume, hold GPIO28 for 1.4 seconds; record for 2 seconds, then listen for playback.
4. Inspect serial logs for I²S errors and watch for resets or power droop.
5. Only after a successful local loopback, develop STT → Ollama → TTS streaming and talking animations.

## Future (not wired in this phase)

- Freenove ESP32-S3 camera board (FNK0085B N16R8) and Waveshare 1.9-inch ST7789V2 display (SKU 23822) are future candidates.
- Do not infer that they are integrated with the current sketch. A firmware port and a new conflict-checked GPIO map will be required before migration.

## References

- [LILYGO T-Display-C5 hardware documentation](https://github.com/Xinyuan-LilyGO/T-Display-C5)
- [LILYGO T-Display-C5 product](https://lilygo.cc/products/t-display-c5)
- [ELEGOO 830 breadboard](https://www.amazon.co.jp/dp/B06Y4KFCRJ)
