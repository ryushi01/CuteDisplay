# C5 v21 French Latin accent composition — experimental

User wants the original chat ASCII font size and thickness, with accented French capitals matching the underlying letter exactly. Prior whole-font boldening was rejected.

## Implementation
- The normal 5x7 ASCII bitmap renderer (display scale 2) is unchanged.
- New `firmware/CuteDisplay/C5LatinAccent.h` maps uppercase precomposed A/E/I/O/U/C/N/Y accented letters to the original ASCII base letter + a small diacritic drawn separately. Includes French À Â Ä Ç É È Ê Ë Î Ï Ô Ö Ù Û Ü Ÿ; also common related Western Latin accents.
- `decodeChatLatin()` uppercases and composes supported Latin base + Unicode combining acute/grave/circumflex/diaeresis/tilde/cedilla/ring sequences before layout and drawing. This is deliberately **limited French/Western-Latin composition**, not full Unicode NFC implementation.
- `richWidth`, AI text wrapping, and `richText` use matching decoding where updated. Unmodified Japanese/emoji/other Unicode lookup paths remain intact.
- Accents may extend a few pixels above or below the original ASCII glyph; underlying letter body is pixel-identical. Ligatures (Œ, Æ), characters outside the mapping, and unsupported combinations retain the pre-existing Unicode font behavior.
- UART packet-size negotiation and physical GPIO wiring inherited from v17-v20 and unchanged.

## Verification
- CI compilation/flash-size checks must succeed before installation.
- Hardware check: `M'ENTENDRE ? ÉTÉ, ÈVE, ÊTRE, ÇA, À BIENTÔT !`
- Test both NFC/precomposed and decomposed e + combining accent, and verify text wraps without an extra blank cell.
- Confirm ASCII `M` is normal size; test French capital diacritics at the top of the speech bubble for clipping, and cedilla at the bottom of a line.
- Regression-test Japanese, C5 emoji, AI streaming, BLE, and OTA success.
- Do not call this stable until the user verifies on the C5 screen.
