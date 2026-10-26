#pragma once
// CuteDisplay ESP32-S3 FNK0085B candidate breakout GPIO map.
// CONFLICT-REVIEWED, NOT BENCH-VALIDATED. No peripherals are initialized here.
// See docs/hardware/s3-c5-breadboard-plan.md for the matching diagram,
// camera/SD/PSRAM exclusions and electrical precautions.
namespace BrainPinPlan {
inline constexpr int I2S_BCLK = 41;  // S3 -> INMP441 SCK and MAX98357A BCLK
inline constexpr int I2S_WS   = 42;  // S3 -> INMP441 WS and MAX98357A LRC
inline constexpr int I2S_DIN  = 1;   // INMP441 SD -> S3
inline constexpr int I2S_DOUT = 2;   // S3 -> MAX98357A DIN
inline constexpr int UART_TX  = 47;  // S3 TX -> LILYGO C5 GPIO1 RX
inline constexpr int UART_RX  = 21;  // S3 RX <- LILYGO C5 GPIO6 TX
inline constexpr int C5_UART_TX = 6;
inline constexpr int C5_UART_RX = 1;
inline constexpr int UART_BAUD = 115200;
// Keep BLE enabled for iPhone onboarding and offline local management.
// Wi-Fi is for AI backend; camera integration deliberately postponed.
}
