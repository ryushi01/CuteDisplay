# C5 v18 — user hardware acceptance (2026-10-28)

## Acceptance statement
The user installed the combined firmware and inspected the C5's AI-chat fonts and characters on the physical display. User explicitly reported: **"I have checked the fonts and characters and they are fine now so lets validate. no need to improve uart more."**

**Accepted:** current C5 v18 chat font appearance and character rendering, including the unified visual weight/size changes and retained French accented uppercase, Unicode, and emoji rendering from prior work. Do not revisit or further tweak character appearance unless the user reports a new defect.

**UART decision:** user explicitly declines further UART optimization. Retain the existing UART GPIO mappings, 921600-baud serial and v17 negotiated 40/160-byte OTA implementation as packaged with v18. No dual UART, higher baud, binary transport or SPI project work requested. Stop the SPI idea and avoid further UART changes.

## Proven vs not proven
- **User-verified on hardware:** chat text font/character appearance acceptable after firmware upload.
- **Not independently confirmed from user's message:** OTA speed improvement, reliable 160-byte negotiated transfer after an additional subsequent update, final full CI job conclusion, or complete long-term regression results. Do not claim faster transfers were demonstrated.
- Firmware acceptance pertains to C5 display fonts and characters, not a new validation of MacBook/Ubuntu realtime TTS service.

## Release references
- Source branch: `feature/c5-uniform-chat-font-v18`.
- C5 firmware version: v18; inherits v17 UART packet negotiation, v16 pixel-art emoji, v15 accented uppercase sizing, v14 Unicode coverage.
- Preserve hardware-tested fallback `stable/2026-10-28-wav-uart-autorecovery-hardware-tested` and don't overwrite without an explicit request.

## Future workflow
Treat the current C5 text renderer as the accepted visual baseline, document any next changes on their own feature branches. Avoid adding unrelated transport or typography experiments to this checkpoint.
