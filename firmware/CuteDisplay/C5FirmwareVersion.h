#pragma once
#include <stdint.h>
// C5 firmware version, increment for OTA-visible application changes.
// v13: last hardware-tested baseline.
// v14: expanded Unicode font coverage for French, Japanese, and symbols.
// v15: uppercase accented Latin rendering and matched glyph visual size.
// v16: colored inline emoji faces, hearts and special symbols.
// v17: negotiated 160-byte UART OTA packets, backwards-compatible receiver.
// v18: unified bold chat font for ASCII and accented Latin.
// v19 restores original ASCII chat style and selectively adjusts Latin accents.
// v20: consistent Latin glyph priority; ignore old smooth overrides.
// v21: French accents drawn using the exact matching ASCII letter bitmap.
// v22: C5 left short tap toggles realtime call; long hold preserves PTT.
// v23: 320x170 bespoke full-screen Kitty call face with 8 moods, lip sync and
// immediate return to the original normal message/mascot on CALL_OFF.
// v24: dedicated C5-local animated thinking face; keep spoken mood until audio ends.
// v25: AI-selected emotions appear only during CALL_SPEAKING, never THINKING/LISTENING.
// v26: compact live transcription caption at bottom of full-screen Call Mode.
// v27: always-visible compact user/Kitty transcript strip in realtime Call Mode.
// v28: two-line top conversation monitor, black text without a dark panel.
// v29: two-line chronological captions with newest text on lower row.
// v30: smooth 200ms expression transitions while retaining live lip sync.
// v31: width-aware UTF-8 caption wrapping and segmented UART text scrolling.
static constexpr uint32_t C5_FIRMWARE_VERSION = 31;
