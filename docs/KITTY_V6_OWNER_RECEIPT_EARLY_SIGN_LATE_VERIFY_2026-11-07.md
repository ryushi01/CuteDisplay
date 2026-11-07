# Kitty V6 — early signed S3 receipt, late exact-byte verification (2026-11-07)

## Goal and baseline

Continue merged PR #21 (`4aa8769`), preserving the working realtime gateway, S3/C5 firmware, iPhone setup, Mac AI/TTS and approved shared recall. Close the **10-second voice proof versus idle SD snapshot** timing gap without extending the private-recall grant or allowing an unverified speaker to become the owner.

## Design

There are **two distinct events** that must not be conflated:

1. **Receipt issuance / queueing:** While a 10-second voice speaking-turn ticket and call-bound owner grant are still valid, the trusted gateway checks its *authenticated S3 device socket* and original provider item against the SD-worker `kitty.memory.owner_archive.ack`. A new `issue_provisional_owner_receipt` function can sign the existing `owner-v1` receipt fields using the ACK's archived-row SHA-256 and the *exact signed transcript digest*, **without first reading a delayed snapshot**. The existing per-call correlator provides `receipt_from_authenticated_ack(item_id)`, which consumes the pending item once. The expected output is the existing `kitty.memory.owner_archive.receipt` event; only the S3 SD worker appends this opaque row to its microSD. No signing key goes onto the device.
2. **Actual owner attribution:** The already implemented `read_verified_owner_receipts` later opens the finalized, S3-origin snapshot and checks the receipt HMAC, the archived row's **exact offset, SHA-256 and transcript digest**, and the receipt format. Only a matching actual SD archive row becomes a derived verified-owner index row. A forged, missing, changed or mismatched S3 row grants **nothing**. The receipt alone cannot unlock owner-private recall, authorize future turns, or write `facts.tsv`.

This permits later SD synchronization without keeping a long-lived voice grant or private conversation database on Ubuntu. The signed receipt is a conditional cryptographic assertion from an authenticated S3 ACK, **not** a claim that the snapshot was already verified. Owner voice risk remains the explicit opt-in policy described in PR #20; replay/clone-resistant human authentication is *not* established by these receipt changes.

## Important trust boundaries

- An ACK from the ordinary client message path or S3 JSON sidecar is never trusted. Only the gateway's **authenticated device receive loop**, tied to the same socket object and call session, can feed the correlator.
- The issuer still requires separate protected signing keys, a valid session grant and an exact audio-bound, fresh `purpose=turn` owner ticket; guessed speaker names, 0.960 familiarity scores or learning tickets never qualify.
- The existing gateway correlator rejects duplicates, out-of-range offsets, timestamp mismatch, stale epoch/session effects (by fresh adapter per call), consent revocation, guest interruptions and failed signatures.
- The receipt must be delivered to the **same authenticated S3 connection** while that call and capability negotiation remain active. No retry by accepting a stale device credential or replaying a cached ACK.
- On corrupt archive or failed delivery, records may remain unverified; that is preferable to silently assigning an unverified conversation to the owner.
- The S3 already supports the optional tenth `owner_turn_receipts_v6.tsv` snapshot file and original nine-file fallback. **No firmware modification or flash is included here.**

## Source-only implementation and tests

- `server/kitty_owner_sd_receipts_v6.py`: new opt-in signer for authenticated SD ACKs. Original finalized-snapshot signer retained.
- `server/kitty_owner_archive_gateway_v6.py`: new one-use `receipt_from_authenticated_ack()`, with the original `receipt_from_finalized_snapshot()` kept for compatibility.
- `server/test_kitty_owner_provisional_receipt_v6.py`: delayed snapshot, hash/row tampering, untrusted ACK, guest, expiry, revocation and once-only tests, including the existing SD read verifier.
- `.github/workflows/kitty-private-v6-focused.yml`: new regressions in the privacy CI suite.

## Still not deployed

The new source is **not connected** to the deployed Open WebUI gateway. The gateway must integrate the private issuer, authenticate the S3 ACK source, send the receipt on the existing socket and confirm the S3 SD worker accepts it, all off the realtime audio path. Owner-only recall must remain disabled until these and real owner/guest/replay/voice-clone hardware trials pass.

No Ubuntu durable private-memory authority is created, no server secrets are printed, no services restarted and no S3/C5/iPhone image changed.

## Remaining operational caveats

An ACK may arrive **after** the signed 10-second voice ticket expires; this route intentionally refuses it. Receipt delivery may fail or the S3 SD file may exceed its bound; those do not create an owner record. Additional future tests should cover actual ACK queue latency, S3 receipt-write confirmation, snapshot revision consistency and source-provenance authenticity before enabling owner-private recall.