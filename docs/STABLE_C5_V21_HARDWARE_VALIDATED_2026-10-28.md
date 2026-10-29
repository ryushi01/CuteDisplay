# Stable checkpoint — C5 v21 French accents (user hardware validated)

Date: 2026-10-28

## User acceptance
The user flashed and tested the C5 v21 firmware on the physical display and explicitly confirmed **"it works perfectly !"** after testing the targeted French/Latin accent fix. This supersedes the earlier v18/v19/v20 experimental typography results.

## Frozen software behavior
- Original C5 chat ASCII 5x7 font rendering and its preferred size and stroke weight are preserved.
- Supported uppercase French accented Latin glyphs are drawn from the same base ASCII letter bitmap plus a diacritic, so e.g. É uses the exact E shape and Ç uses the C shape.
- Both supported precomposed and decomposed Latin accented inputs render consistently through a narrow C5-side composition layer. This is **not** full Unicode NFC.
- Japanese Unicode and emoji renderer paths remain as they were.
- Existing optimized UART OTA packet negotiation (legacy 40 bytes / new receiver up to 160 bytes at 921600 baud), UART wire assignments, and SHA-256 verified dual-slot OTA retained. User explicitly requested **no additional UART optimization**.
- S3 audio/voice, iPhone BLE interaction, server integration and hardware configuration are not modified as part of this checkpoint.

## Recovery / development policy
- The stable branch is an immutable hardware-tested source snapshot. Do not commit experiments to it.
- All subsequent CuteDisplay features should branch separately from this stable source, and must preserve v21 glyph rendering and UART behavior unless user explicitly asks otherwise.
- The existing previous recovery branch `stable/2026-10-28-wav-uart-autorecovery-hardware-tested` remains available.
- Hardware acceptance is specifically for the user-observed font fix. Do not infer or claim that a new OTA performance benchmark, exhaustive Unicode coverage or all regression tests were independently performed.

## Source implementation
- `firmware/CuteDisplay/C5LatinAccent.h`: accent bases and combining-mark composition.
- `firmware/CuteDisplay/lcd.ino`: C5-only chat text composition/drawing.
- `firmware/CuteDisplay/C5FirmwareVersion.h`: v21.
- `firmware/CuteDisplayBrain/BrainC5OTA.h` and `firmware/CuteDisplay/C5UARTOTA.h`: negotiated UART OTA.

Reference: `docs/C5_V21_LATIN_ACCENTS.md`.
