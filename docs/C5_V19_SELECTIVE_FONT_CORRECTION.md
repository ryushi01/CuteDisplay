# C5 v19 — restore original chat look, selectively improve accent weight

User feedback after trying v18 on hardware: all characters looked strange and too thick. User preferred the **previous** ASCII display text size and thickness and only wanted a few visually inconsistent accents/special letters adjusted. Preserve existing v17 UART OTA improvement.

## Changes
- Restored `firmware/CuteDisplay/lcd.ino` renderer exactly from `feature/uart-ota-fast-v17`. Regular ASCII uses the familiar 5x7 bitmap at scale=2 again; non-ASCII continues via embedded 16x16 font, same width/height and layout as v17.
- Restored `tools/generate_c5_japanese_font.py` from v17, plus **stroke_width=1 only for Latin accented/extended code points** U+00C0–U+024F and U+1E00–U+1EFF, not for ASCII. Narrow accent spacing and existing height normalization stay as before. This is a targeted attempt to match ASCII stroke weight, not a universal boldening.
- C5 firmware version raised from v18 to v19. Combined CI workflow runs on `feature/c5-v19-selective-font-fix`.
- All v17 fast UART negotiation is preserved: C5 advertises 160-byte maximum OTA chunks; S3 falls back to legacy 40 bytes when required; original UART 921600 baud, SHA256 and dual OTA safety remain.
- v16 procedural emoji, Unicode and French uppercase mapping remain.

## Acceptance gates
Do not call this stable until build succeeds and user examines physical C5 screen. Test with `BONJOUR, ÇA VA ? TRÈS BIEN ! À BIENTÔT !` plus Japanese and emojis. Confirm that ASCII glyphs look exactly like the pre-v18 style and that accented capitals are no longer too thin (nor overly thick). Inspect missing accented letters and wrapping.
The v18 user-accepted checkpoint is retained as historical, **superseded by later user feedback rejecting the bold text appearance**. Do not overwrite other immutable fallbacks.
