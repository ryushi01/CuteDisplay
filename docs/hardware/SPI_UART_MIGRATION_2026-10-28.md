# S3 ↔ C5 high-speed SPI with independent UART recovery

Status: **design checkpoint only; no SPI wires should be connected yet and no SPI firmware has been flashed.** Created 2026-10-28.

## Objective
Use Freenove ESP32-S3 as SPI master and LILYGO T-Display-C5 as SPI slave. SPI will carry high-throughput binary firmware OTA blocks and, after verification, routine framed text/control/telemetry. Keep existing functional UART as an independent recovery link.

## Proposed netlist (physical GPIO assignments intentionally uncommitted)
| Signal | S3 side | C5 side | Notes |
|---|---|---|---|
| SPI MOSI | spare output-capable GPIO, same header cluster | spare input-capable GPIO | master → slave |
| SPI MISO | spare input-capable GPIO, same header cluster | spare output-capable GPIO | slave → master |
| SPI SCLK | spare output-capable GPIO, same header cluster | spare input-capable GPIO | 4 MHz initial, then 8 MHz if verified |
| SPI CS | spare output-capable GPIO, same header cluster | spare input-capable GPIO | dedicated chip select |
| SPI READY | spare input-capable GPIO nearby | spare output-capable GPIO | C5 signals receive/DMA readiness |
| UART TX recovery | **GPIO47** | **GPIO1 RX** | existing tested physical wire, leave unchanged |
| UART RX recovery | **GPIO21** | **GPIO6 TX** | existing tested physical wire, leave unchanged |
| GND | GND | GND | shared reference mandatory |
| Optional board power | *verify electrically* | *verify electrically* | do not assume safe 5V rail/backfeed protection |

That is **five new signal wires + two existing UART wires + common GND** (8 conductors total, excluding optional 5V power). If C5 lacks five safe spare pins, choose a tested alternative rather than share SPI lines with LCD, power management, USB, or bootstraps.

**Pin assignment gate:** Do not choose S3 GPIOs solely by numerical adjacency. Consult exact Freenove board variant silkscreen/schematic and C5 exposed header layout. S3 I2S GPIO41/42 clocks, GPIO1 mic data, GPIO2 DAC data, camera, SD, PSRAM, USB, boot and current UART assignments are reserved. C5 LCD SPI (GPIO26/7/9/8/23/25), PMIC I2C (2/3/10), buttons (0/28), UART (1/6) and other board/flash reservations must not overlap. C5 physical pins and ESP32-C5 slave support/driver pin mapping require confirmation before actual wiring. The SPI bus **must be separate** from the onboard display SPI bus.

## Transport and recovery safety
1. Preserve working UART protocol at 921600 baud as a guaranteed communication and OTA fallback. Maintain original boot/recovery and C5 v13 rollback images.
2. Add SPI support as a compile-time opt-in, *disabled by default*, with boot handshake / version negotiation. Boot on UART; enable SPI only when both sides advertise compatible SPI transport.
3. Use CS + READY handshake. S3 starts transfer only on READY. Start at 4 MHz, advance to 8 MHz on hardware proof. ESP32-C5 SPI slave DMA may need buffer alignment and transaction-size constraints; check target ESP-IDF Arduino platform.
4. Frame SPI blocks with magic, protocol version, command ID, sequence, offset, length, CRC32. Do not send string hex for OTA blocks. Acknowledge at block level; permit retry and resume on interruption. Only one active transport owns an OTA transaction.
5. C5 writes OTA using existing Update / ESP OTA two-slot semantics and checks SHA-256 before reboot. Track offset and atomic completion; reject out-of-order blocks. Limit payload size to available RAM, DMA, flash write and OTA slot; use e.g. 1024-byte blocks initially, not a fixed promise.
6. Timeout, CRC error, unexpected reset or SPI handshake failure: discard incomplete transaction safely, keep last bootable C5 application, restore normal UART communications; do not automatically switch pins or disable UART.
7. Keep text streaming behavior, iPhone BLE, I2S mic/speaker, camera reservation, battery readings and C5 display timing unchanged. Prioritize OTA benchmark first, only then migrate routine messaging.
8. Measure real throughput against current UART 40-byte hex + per-chunk ACK baseline, capture SHA-256 match and reboot success, and hardware-test at least one interrupted-transfer recovery before calling stable.

## Stage gates
- Stage A (current): architecture and physical GPIO availability review; no production change.
- Stage B: select neighboring S3 pins and free C5 pins, produce exact wiring diagram and continuity test.
- Stage C: SPI ping/pong and CRC/READY testing with UART still active; no OTA.
- Stage D: dual-transport binary OTA, benchmark and recovery tests.
- Stage E: optional migration of runtime text/telemetry after voice, OTA, BLE and LCD regression tests.
- Stage F: separate build artifact and hardware acceptance. Never merge until explicitly accepted.

## Existing verified pins and source references
- `firmware/CuteDisplayBrain/BrainPinPlan.h`: S3 UART GPIO47/21; I2S 41/42/1/2.
- `firmware/CuteDisplay/C5UARTOTA.h`: C5 UART GPIO1 RX and GPIO6 TX, 40-byte hex OTA DATA with per-frame ack, SHA-256 validation and two-slot update.
- `docs/hardware/s3-c5-breadboard-plan.md`: earlier candidate pin conflict review; physical S3 header assignments **not verified**.

Never claim SPI is already working, and do not require removing existing UART wires during rollout.
