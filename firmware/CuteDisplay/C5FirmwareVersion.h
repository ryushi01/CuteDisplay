#pragma once
// Verified baseline: C5 v2 was installed by S3 UART OTA on 2026-10-27.
// v3 fixes UTF-8 boundary truncation when persisting messages.
// v4 keeps speech-bubble font readable instead of shrinking as it fills.\n// Increase this version whenever the C5 application changes. CI builds
// v6 adds inactivity-based receiver recovery for stalled OTA sessions.
// the C5 binary and bundles it into the S3 firmware automatically.
// v11 restores the persisted regular message after AI completion + 2 minutes.
static constexpr uint32_t C5_FIRMWARE_VERSION=11;
