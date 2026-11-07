# Kitty V6 — gateway-local owner SD receipt correlation (2026-11-07)

## Baseline

Continue from merged PR #20 (\`76c4489\`) and S3 receipt handoff PR #18.
Working realtime voice, Mac AI/TTS, approved shared recall, S3 memory
archiving, C5 display and phone setup must stay unchanged.

## Source-only change

\`server/kitty_owner_archive_gateway_v6.py\` stages a **per-call**, RAM-only
\`OwnerArchiveGatewayCorrelator\` for a future authenticated gateway.

The gateway must supply all of these **from trusted internal sources**:
- A new, gateway-created session ID and a unique, authenticated S3 WebSocket
  connection *object*, never a string supplied by the device or a browser.
  An adapter instance is single-call-use to prevent a delayed ACK crossing
  into a newly opened call on the same connection.
- Explicit owner consent (rechecked throughout) and three **separate**
  protected signing secrets: voice turn issuer, session grant, SD receipt HMAC.
- The final transcript and fresh **audio-hash-bound** owner proof produced by
  the opt-in issuer in PR #20, tied to the exact provider item ID.
- A read-only callback that returns row bytes from an **immutable, finalized,
  verified S3 SD snapshot**, keyed by the exact original archive timestamp and
  offset. A live mutable file or untrusted S3 JSON echo is NOT a verified
  snapshot source.

Upon authenticated gateway session setup, the adapter can prepare an
opt-in \`kitty.memory.owner_archive.capabilities\` message. The trusted
gateway—not an untrusted client—must decide if/when to send it.

A passing voice turn is registered as pending (bounded to 8). When the same
authenticated S3 connection later emits
\`kitty.memory.owner_archive.ack\`, the adapter checks item ID, 32-bit offset,
timestamp, hash, duplicate state and still-valid exact owner grant/ticket.
It **does not** treat ACK data as speaker authentication.

A separately scheduled snapshot check reads original SD-exported bytes at
that offset, compares both the verbatim user question and SHA-256 with the
device's ACK, then rereads the frozen row under an injected validator.
Only then does \`issue_owner_receipt\` independently verify all signatures
and return a \`kitty.memory.owner_archive.receipt\` event containing the
opaque, signed \`owner-v1\` row. The actual S3 SD worker remains the only
durable writer, and Ubuntu uses verified snapshots as derived read-only data.
No private owner facts are written based on a probable voice match.

Malformed ACKs burn the pending item; duplicate items/offsets cannot mint
multiple receipts; barge-in, unknown speaker, cancellation, consent
revocation, disconnect and a new call invalidate outstanding evidence.
The component performs **no HTTP calls, no model inference, no firmware
updates, no filesystem writes, and no event-loop modifications**.

The existing \`GatewayTurnAdapter\` and \`KittyPassiveTurnBridge\` now
forward an *optional* trusted \`audio_sha256\` to
\`AttestedLiveCall.verify_turn\`, preserving legacy signed guest behavior.

## Known time-window / availability blocker

The owner speaking-turn ticket lasts **10 seconds**. The S3 archive ACK can
arrive during a call, but the verified snapshot export is normally deferred
to idle time. This implementation does **not** bypass the ticket expiry to
invent persistent owner provenance. If the immutable snapshot is unavailable
before ticket expiry, it returns **no receipt**.

This is a source-contract and privacy stage, **not** a guarantee of automatic
cross-call owner-memory persistence. A future safe delayed-receipt protocol
must explicitly preserve a cryptographically bound, short-lived original
verification at the time of the utterance without turning stale voice scores
or a cached grant into a general bearer credential. It also needs export
revision/epoch correlation and durable S3-only storage.

## Offline validation

\`test_kitty_owner_archive_gateway_v6.py\` covers: exact SD row receipt
roundtrip, delayed snapshot, forged device socket, bad ACK fields,
tampered answer/hash, expired ticket, consent off, guest/cancel/disconnect,
old-session replay, and mutable-snapshot detection. The gateway adapter test
covers exact audio-digest forwarding. These run in the focused CI job.

**Deployment:** no new capability message is emitted by any existing live
gateway code. No Ubuntu services, S3/C5 firmware, iPhone app, private key or
SD records are changed. Keep owner-private recall **disabled** until real
hardware owner/guest/replay tests, gateway integration, source provenance,
bounded CPU latency, and the snapshot timing gap are resolved.
