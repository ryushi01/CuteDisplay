#pragma once
// Placeholder for source editing. The combined-firmware build replaces this
// with generated Noto CJK JP bitmaps. Build using tools/build_s3_with_c5_update.sh.
#include <stdint.h>
static constexpr uint32_t C5_JP_COUNT=0;
struct C5JPEntry {uint16_t cp;uint8_t bitmap[32];};
inline const C5JPEntry *c5JPFind(uint32_t){return nullptr;}
