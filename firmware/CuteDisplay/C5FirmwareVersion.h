#pragma once
#include <stdint.h>
// C5 firmware version, increment for OTA-visible application changes.
// v13: last hardware-tested baseline.
// v14: expanded Unicode font coverage for French, Japanese, and symbols.
// v15: uppercase accented Latin rendering and matched glyph visual size.
static constexpr uint32_t C5_FIRMWARE_VERSION = 15;
