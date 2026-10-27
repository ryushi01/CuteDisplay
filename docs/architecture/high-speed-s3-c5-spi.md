# High-speed S3 ↔ C5 link: shared SPI bus design (2026-10-27)

**Status: Architecture and pin-verification gate. Not wired or enabled in firmware.** The existing 921600-baud UART and OTA remain production/recovery path. Do NOT connect unverified pins.

## Critical discovery

The LilyGO T-Display-C5 uses **SPI2_HOST** for its ST7789 display. The ESP32-C5 has **one general-purpose GP-SPI peripheral (SPI2)**; SPI0/1 are used for flash/PSRAM. Therefore a *second independent hardware SPI slave on C5* while maintaining the LCD master on SPI2 is **not possible**. Avoid the previously proposed *S3 master / C5 slave on a separate SPI controller* approach.

References:
- ESP32-C5 technical reference: https://documentation.espressif.com/esp32-c5_technical_reference_manual_en.pdf (SPI controller chapter).
- LilyGO T-Display-C5: https://github.com/Xinyuan-LilyGO/T-Display-C5
- ESP-IDF C5 SPI slave: https://docs.espressif.com/projects/esp-idf/en/stable/esp32c5/api-reference/peripherals/spi_slave.html

## Pinout image received: LILYGO T-Display-C5 v1.0

The board diagram supplied by the user labels the left breakout as GPIO2, GPIO3, GPIO0, GPIO1, GPIO7, GPIO8, GPIO9, GPIO25, GPIO27; and the right breakout as GPIO4, GPIO5, GPIO6, GPIO10, GPIO23, with TXD/RXD and power pads. Existing firmware uses LCD GPIO7 SCLK, GPIO9 MOSI, GPIO26 CS (internal), GPIO8 DC, GPIO23 RST, GPIO25 BL. UART GPIO1 RX/GPIO6 TX, I2C GPIO2/3, and boot GPIO0 are already occupied.

**Candidate C5 breakout connections for experimental shared SPI:**

| SPI net | C5 v1.0 header GPIO | Status |
|---|---|---|
| SCLK clock | GPIO7, existing LCD clock | electrically shared; breakout shown |
| MOSI C5 to S3 | GPIO9, existing LCD data | electrically shared; breakout shown |
| MISO S3 to C5 | GPIO4 | candidate only, not wired |
| S3 SPI CS (active-low) | GPIO5 | candidate only, not wired |
| S3 READY (optional) | GPIO10 | candidate only; SDIO-CMD alternate function—verify no SDIO use |
| Common GND | existing GND | required |

**Important integration blocker:** C5's `spi_bus_initialize(SPI2_HOST)` currently sets `miso_io_num=-1`. Before connecting S3 MISO, the C5 must initialize the *single shared* SPI2 bus with the chosen MISO GPIO and register a second slave-select device using the SAME bus, with arbitration against the LCD DMA. This cannot be fixed with wiring alone.

**S3 SPI slave GPIOs remain unassigned** until the precise Freenove S3 CAM board breakout/schematic is checked against its camera, SD, audio GPIO1/2/41/42, and UART GPIO21/47. Never use the C5's GPIO23 for the proposed CS—it is the LCD reset line. Verify 3.3 V logic, short wires, board grounds and no output-output conflicts before power-on.

---

## Viable architecture to experiment with

Use the **C5 as SPI master** and share the *existing* SPI2 bus with two separate chip-selects:
- LCD ST7789: existing C5 SCLK GPIO7, MOSI GPIO9, CS GPIO26, DC GPIO8 and RST GPIO23 — **unchanged**.
- S3: SPI slave device on the LCD's SCLK and MOSI nets, plus a **separate C5 chip-select output**, an S3 MISO→C5 MISO return, and optionally S3 READY→C5 input.
- The C5 sends S3↔C5 data via queued SPI2 master transactions when the LCD is idle, using **separate CS**. The LCD must never be selected during an S3 transaction, and S3 must never drive a bus except when selected.
- Existing S3↔C5 UART TX/RX/GND remains connected for recovery, commands, OTA and *request/doorbell* notification from S3 that data is queued. The C5 must initiate SPI clocks; the S3 cannot push SPI bytes asynchronously.
- SPI slave device on S3 must use a tested free SPI controller and GPIO. S3 pin assignment pending board-variant schematic and breakout inspection.
- Data protocol: versioned framing, length + sequence + CRC32, bounded FIFO and acknowledgments, idempotent retransmission, timeout fallback to UART. Benchmark 4–8 MHz first, not a guaranteed 20 MHz. Queued DMA can be considered only after 8-bit functional test.
- SPI driver ownership: one task/transaction manager owns C5 SPI2 host and shares it safely with the esp_lcd driver. Do not call a second independent spi_bus_initialize(SPI2_HOST,...) or allow races with in-flight LCD DMA.
- RTC, flash and PSRAM pins, bootstraps, I2C power management and USB pins must not be repurposed.

## Proposed physical signals (GPIOs NOT YET ASSIGNED)

| Signal | C5 side | S3 side | Note |
|---|---|---|---|
| SPI CLK | Existing LCD SPI2 SCLK, GPIO7 *bus tap* | S3 SPI slave SCLK (TBD) | Existing LCD continues |
| MOSI C5→S3 | Existing LCD SPI2 MOSI, GPIO9 *bus tap* | S3 slave MOSI (TBD) | Existing LCD continues |
| MISO S3→C5 | Free C5 GPIO (TBD) | S3 slave MISO (TBD) | Additional connection |
| S3 chip select | Free C5 GPIO output (TBD) | S3 slave CS (TBD) | Separate from LCD CS GPIO26 |
| READY optional | Free C5 GPIO input (TBD) | S3 GPIO output (TBD) | Optional; UART can signal availability |
| GND | Already common | Already common | Mandatory |

**Do not attach to GPIO7/9 blindly**: these lines connect to an active LCD, and physical breakout availability and bus loading are unverified. Need manufacturer schematic, access point, and actual photos of the boards. No 5V signaling; use 3.3V only.

## Why it might help and what it cannot fix

1. SPI offers higher raw bit rate for large frames/OTA, but there is added complexity because C5 must schedule transactions around display DMA.
2. Currently the iPhone pushes UTF-8 messages and font/glyph packets through encrypted BLE into small UART commands with per-command acknowledgments; this overhead and the screen rendering/typewriter animation can dominate short-message latency.
3. Before hardware migration, benchmark actual BLE→UART→LCD timings, glyph cache hit/miss and firmware OTA throughput. A larger packet protocol and caching may deliver bigger improvements with zero new wires.
4. A future SPI migration must be feature-flagged, dual-board negotiated, and leave UART boot/OTA as the fallback. Never force two-board simultaneous upgrade without a rollback method.

## Implementation gates

1. Confirm exact T-Display-C5 PCB revision and *physically exposed* spare pins (vendor schematic + board photo). Confirm S3 CAM board GPIO breakout/camera/PSRAM mapping.
2. Prepare a passive SPI-bus probe / logic analyzer test to ensure LCD clock/MOSI/CS behavior and signal integrity before attaching the S3.
3. Build a **separate experimental branch**, not the stable baseline, with C5 master SPI2 bus arbitration + S3 slave test code and a simple throughput benchmark; no OTA migration yet.
4. Verify LCD keeps rendering normally, BLE reconnection works, mic/speaker unchanged, power/BMS telemetry unaffected.
5. Add CRC/fallback and only then evaluate high-speed firmware transfers.

## Current wiring stays unchanged

S3 TX GPIO47 → C5 RX GPIO1; C5 TX GPIO6 → S3 RX GPIO21; common ground.
S3 audio: BCLK GPIO41, WS GPIO42, mic DIN GPIO1, amp DOUT GPIO2. Do not reuse these.
