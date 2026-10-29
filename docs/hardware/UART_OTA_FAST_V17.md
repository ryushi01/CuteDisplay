# UART OTA acceleration — C5 v17 experiment (2026-10-28)

**Status:** source implemented on feature branch, hardware validation pending. Never flash until combined GitHub Actions build succeeds. Preserve deployed working firmware and rollback.

## Why old OTA was slow
- S3 GPIO47 TX ↔ C5 GPIO1 RX, S3 GPIO21 RX ↔ C5 GPIO6 TX, common GND, 921600 baud.
- OTA_DATA carries only 40 firmware bytes per acknowledged packet; each byte encoded as 2 ASCII hex characters, causing high frame and ACK overhead.
- Per-frame CRC-8 and final SHA256 / dual OTA partition remain.

## v17 changes
1. Identical `CuteLink.h` protocol libraries on both boards now support bounded frames up to 512 bytes and payload up to 400 bytes; parser input budget raised to 768 bytes per poll. Default UART baud unchanged; no physical rewiring or new pins.
2. C5 `OTA_INFO` now responds `version,slot,160` to advertise a 160-byte maximum OTA_DATA block. C5 receiver validates and writes up to 160 decoded bytes per packet (hex encoding preserved). Update's SHA256 check, rollback, reboot and timeouts remain.
3. S3 parses original `version,slot` replies as 40-byte mode for legacy receivers and new `version,slot,160` as 160-byte mode. No new version handshake is required for old C5. This cuts acknowledged DATA packet count by up to 75% **only when a v17+ receiver is installed**; achieved speedup has not yet been measured.
4. C5 firmware version bumped **v17**. Source is derived from the C5 emoji/Unicode v16 development branch; retains its display improvements.

## Upgrade sequence
- First install v17 S3 bundled image while old C5 is v16 or earlier: old C5 supports only 40-byte OTA chunks, so **first v17 transfer runs at old speed** and brings the new C5 receiver online.
- For the next later C5 firmware update, receiver announces 160 and the paired S3 uses larger blocks automatically.
- Confirm `[S3 OTA] C5 agreed OTA block=160 bytes` in the S3 log and validate installed version after C5 reboot.
- To roll back to an older S3 firmware while C5 is v17, note that old S3 parser may reject the new three-field OTA_INFO response; test and plan recovery before production rollout.
- Performance counters and independent hardware stress tests are still required. This is not a binary transfer protocol; bytes remain ASCII hex, limiting the achievable speedup. A future binary OTA mode would require a new negotiated transport and stronger testing.

## Explicitly unchanged
- S3 ↔ C5 wiring and 921600 baud, text stream semantics, buttons, BLE, Wi-Fi, iPhone app, I2S audio, display fonts/emojis, C5 flash partitions, existing OTA integrity verification and fail-safe update logic.

## Acceptance checks
1. CI compilation and OTA partition size.
2. Successful bundled v17 upgrade from earlier installed C5; no reboot loops.
3. Send incremental new version (v18 or later), observe negotiated 160-byte blocks and measure elapsed OTA transfer time.
4. Inject UART interruption; verify previous bootable app remains and UART link recovers.
5. Regression-test C5 special characters, French uppercase, emojis, AI text display and voice buttons.

Build workflow: `.github/workflows/build-s3-with-c5-update.yml` on branch `feature/uart-ota-fast-v17`. Never merge before successful user hardware validation.
