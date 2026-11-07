# Kitty V6 — S3 private-owner archive handoff (source only, 2026-11-07)

## Established working baseline

The live Ubuntu memory service and Open WebUI are healthy after the guarded
approved-public-memory repair (PR #15); Kitty talked normally and recalled
approved Mochi Planet information on a subsequent call. **Do not redeploy
the earlier crashing gateway context patch**. Current S3 microSD is the
permanent memory authority. C5 firmware, iPhone BLE pairing, Mac inference/TTS,
S3 audio and already running gateway are not modified by this stage.

PR #16 implemented independently verified exact speaking-turn authorization.
PR #17 implemented a detached, authenticated `owner-v1` archive receipt
format and verified-owner SD-derived indexing. Neither is deployed live:
there is no independently trusted human speaker turn issuer and no enrolled
owner grant currently connected to normal calls.

## New opt-in S3 firmware source (no flash)

`KittyMemory.h` has two bounded PSRAM-backed mechanisms, neither active
until a gateway explicitly negotiates the new extension.

**Actual S3 archive ACK**: The existing SD task finishes an append to
`/kitty/conversations.tsv`, flushes it, rereads the exact bytes from
the original byte offset, computes their SHA256, and only then queues
`{item_id,stamp,offset,archive_sha256}` with an epoch and conversation
number. S3 never claims this proves the *human* speaker. The ACK is an
archival storage observation. Entries with no provider item or stale
session epoch cannot be forwarded. A bounded queue may drop an ACK rather
than block or disturb audio. If dropped, no private receipt may be minted
for that turn. The trusted gateway must match the ACK with the same
authenticated S3 WebSocket session, actual provider item, audio and
independently verified owner attestation; no caller-supplied JSON echo
can replace that check.

**Opaque signed-receipt append**: Only an explicitly opted-in gateway may
submit a bounded, ten-tab, ASCII receipt row with an `owner-v1` prefix.
The S3 does NOT possess the receipt signing secret. It stores the supplied
row append-only on its SD task. The Ubuntu snapshot index must independently
verify the HMAC, exact archive row and source role before granting private
memory recall. A receipt cannot mark `ownerVerified` on the S3 or write
to `facts.tsv`.

The handshake is deliberately **not** advertised in the ordinary S3 auth
event. An upgraded gateway must deliberately send a trusted custom
`kitty.memory.owner_archive.capabilities` event with `enabled=true` after
its own authentication and verification. Until then
`ownerArchiveSupported=false`, and NO new client event is sent.

For future gateway integration, the protocol (source only) is:

- Gateway → S3: `kitty.memory.owner_archive.capabilities`, `enabled=true`.
- S3 → gateway (only if enabled and ACK ready):
  `kitty.memory.owner_archive.ack`, `item_id`, `stamp`, `offset`,
  `archive_sha256`. The gateway must bind these to its trusted session
  and **verify against actual finalized SD export bytes** before using them
  as receipt issuance evidence.
- Gateway → S3 (only after independently verified owner grant, trusted
  human speaking-turn ticket and accepted SD ACK):
  `kitty.memory.owner_archive.receipt`, `line` holding the literal
  signed `owner-v1` TSV row including its final newline.
- On disconnect, call end, or optional send failure, capability is cleared.
  An old epoch cannot authorize a new session.

Snapshots now export an **optional tenth file**
`owner_turn_receipts_v6.tsv`. All existing nine files remain in the
original order. The existing Python snapshot receiver already accepts
the optional name (PR #17), but the *deployed* receiver must be checked
before ever flashing a new S3 image. Each receipt revision participates
in frozen-size export validation and change detection; no mixed-revision
snapshot may be finalized.

## Constraints and caution

1. **Do not flash or deploy yet.** The running gateway does not emit the
   owner archive capability, has no authentic live human-speaker issuer,
   and has no verified-owner SD records. Source compilation is not proof
   of end-to-end secure private recall.
2. Existing phone setup stays intact. No public-key copy, credential paste,
   re-pairing or manual owner enrollment is requested.
3. No receipt can be produced merely from a voice confidence score,
   stated name, BLE identity or device API key. The S3 accepts only
   *opaque* receipts and the derived index validates independent proof.
4. The S3 truncates and sanitizes archived questions to 255 bytes. A
   future receipt issuer must compare the verified provider transcript
   to the exact archived question; nonmatching/truncated utterances are
   **not eligible** for durable owner receipts.
5. A successful SD write and ACK proves archival persistence, **not
   independent verification of who spoke**, microphone liveness, or
   permission to reveal personal information. The future gateway must
   still supply that distinct trust boundary. Owner/guest memory isolation
   must be hardware-tested before enabling the feature.
6. Source-side ACK and receipt queues are PSRAM-backed, bounded and
   fail closed on allocation/queue failure. They never wait on SD
   from the mic, speaker, WebSocket or Arduino main loop.

## Validation

GitHub CI runs the standard firmware compilation plus static S3 privacy
contract checks. The prior Python signed-receipt/index tests are retained.
No additional firmware flash or repeated live voice call is required
for this source-only stage.

## Next integration

Implement and independently verify the human owner turn issuer
(with a user-approved/authenticated enrollment path but no manual key
pasting or repeated BLE pairing); then implement the trusted gateway
session/item/ACK correlation and safe receipt delivery. Deploy receiver
first, then combine S3 changes into a single planned firmware flash.
Never enable the new feature on the current working gateway until
all dependencies and privacy tests pass.
