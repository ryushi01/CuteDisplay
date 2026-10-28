# C5 Unicode display font coverage (development branch)

The **C5 itself** decodes received UTF-8 and renders glyphs. The S3 sends the original text unchanged; neither Open WebUI nor the iPhone app needs to generate fonts.

## Built-in 16×16 bitmap font
The combined build generates a flash-resident, sorted glyph table from the installed Noto CJK JP font. Coverage includes:
- Latin-1, Latin Extended A/B and additional Latin characters: French accented characters such as À Á Â Ä Æ Ç È É Ê Ë Î Ï Ô Œ Ù Û Ü Ÿ à â ç é è ê ë î ï ô œ ù û ü ÿ, along with Spanish, German and others.
- Greek/Coptic/Cyrillic alphabets and common phonetic/Latin extensions.
- Japanese hiragana, katakana, JIS X 0208 and BMP CJK Unified Ideographs / Extension A / compatibility ideographs.
- Common BMP punctuation, curly quotes, bullets, mathematical operators, currencies, arrows, box drawing, geometric shapes, dingbats, fullwidth forms and common compatibility characters.

The existing `richText` / `utfWidth` path uses reduced cell width for Latin accented letters and full CJK cell widths for Japanese; missing glyphs show `?` instead of disappearing. The existing dynamic glyph cache and smooth glyph machinery remain.

**Limits:** Full Unicode cannot be implemented by this 16-bit BMP lookup alone. Supplementary-plane emoji and historic scripts, multi-codepoint emoji sequences, bidirectional/shaped writing and fully correct combining-mark positioning still require separate rendering work. Some glyphs may not exist in the source font. This change intentionally improves broad everyday coverage without claiming every Unicode sequence renders faithfully.

## Deployment and verification
- Development branch `feature/c5-unicode-font-coverage`, C5 firmware v14. Wait for GitHub Actions `Build combined S3 + C5 firmware` to succeed before flashing; check compiled binary fits the configured OTA slot. Do not overwrite the hardware-tested C5 v13 fallback.
- Use combined firmware artifact's `CuteDisplayBrain/CuteDisplayBrain.ino` on S3; S3 UART OTA updates C5.
- Hardware test: French `Éléphant, déjà vu ! À bientôt, où est l'œuvre ? Ça coûte 15 € — « très bien »…`; Japanese `こんにちは。日本語の漢字、東京、𠮷野家。` (the supplementary `𠮷` is expected to use fallback); symbols `© ® ™ € £ ¥ → ← ± × ÷ ≠ ≤ ≥ ∞ ★ ✓ ♥`.
- Source-only changes to the C5 on this branch; unrelated production TTS pipeline and S3 firmware unaffected.
