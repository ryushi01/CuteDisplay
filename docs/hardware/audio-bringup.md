# CuteDisplay S3 isolated audio bring-up

This is a **temporary diagnostic sketch**, **not** the regular S3 Brain firmware. It does not run Kitty UART, S3→C5 OTA, iPhone BLE, Wi-Fi, or AI. After the test, re-upload the **known-good combined S3 firmware artifact** to restore them. **Never use during an active C5 firmware transfer.**

Arduino IDE: ESP32S3 Dev Module; 16 MB flash; OPI PSRAM; ESP32 core **3.3.12**. Open `CuteDisplayAudioTest.ino` in its own folder; select S3 USB port; upload; open Serial Monitor 115200.

Wiring (power OFF): INMP441 VDD→3V3, GND→GND, L/R→GND, SCK→S3 GPIO41, WS→S3 GPIO42, SD→S3 GPIO1. MAX98357A VIN→3V3 (only if this module and the S3 regulator are rated for the required current), GND→GND, BCLK→S3 GPIO41, LRC→S3 GPIO42, DIN→S3 GPIO2, SD/GAIN left at board defaults if the amp is enabled. Speaker across amp SPK+/SPK−; **do not connect either speaker output to GND**. C5 UART wiring stays in place. Shared I²S clocks are intentional. Use low volume; stop if supply browns out or overheating occurs. GPIO41/42 are candidate pins on the selected Freenove S3 board, still awaiting bench confirmation.

The sketch records 2 seconds at 16 kHz from the **left** I²S microphone slot, then stops RX, reconfigures the same clock pins for TX, and plays through the amplifier. Open Serial Monitor before pressing S3 Reset so you see the messages. Expected logs: `Recording now`, `Recorded 32000 samples; peak=...`, `Playing your recording now`, `Sent 64000/64000 bytes`, `Test complete`. If `peak=0` or sound is silent, report the full serial output and photo of pin labels. **This source has not yet been flashed/tested on real hardware.**

For the production integration, use a nonblocking audio worker so UART OTA, BLE and Wi-Fi stay responsive. This isolated proof-of-wiring intentionally does *not* include those services.
