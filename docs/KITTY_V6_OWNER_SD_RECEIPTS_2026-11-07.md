# Kitty V6 verified-owner SD archive receipts — source-only stage

## Why this exists

The working Kitty voice path and explicitly approved public memory recall are
hardware-tested. The latest owner-private semantic security gate (PR #16,
commit da54ebe) already requires independent owner grant and exact signed
speaker decision; the actual S3 SD archive still has **zero verified-owner
index rows** at the last observation. Probable voice recognition, "I'm the
owner" and existing iPhone Bluetooth pairing cannot upgrade an archival row.

This stage adds the missing *durable signed provenance format* that can be
validated across calls **without creating an alternate Ubuntu memory store**.
The S3 microSD remains the source of truth.

## Owner-only archival receipt format

Optional S3 file: `/kitty/owner_turn_receipts_v6.tsv`. A row contains a
version, archived timestamp and exact **byte offset** in
`/kitty/conversations.tsv`, server-generated gateway session ID, exact
provider item ID, hashes of the completed spoken transcript, trusted S3
microphone audio, archived TSV row and issued speaking-turn ticket, issuance
timestamp, and a long-lived HMAC signature. No raw private audio, text,
phone credential or server signing key is stored in the receipt.

A separate private archival receipt signing key must be configured locally
on the trusted Ubuntu verifier. **It must NOT be derived from** the device
bearer, owner grant secret, turn issuer secret, BLE pairing, a voice candidate
or a spoken name. No default key is generated.

Issuance is deliberately unavailable to external callers. Future live
integration must provide *all* of the following together:

1. A valid enrolled-owner cryptographic grant matching the same gateway
   session.
2. An **independent** signed owner turn attestation binding the same session,
   provider item, exact transcript and actual trusted S3 microphone hash;
   learning-only tickets cannot authorize owner history.
3. A **trusted S3 SD-worker append acknowledgment** bound to that exact
   provider item and containing the real archived byte offset and row bytes.
   The gateway must validate the ack independently, not trust caller JSON.
4. The user transcript must equal the actual stored S3 question field,
   preserving the existing firmware sanitation/truncation constraints.

Until all four are available, **no live receipt is minted**. A signed
receipt does not grant any new access to the live realtime provider; it only
labels an exact previously archived SD row for later owner-only indexing.

## Safe read-only derived index behavior

When rebuilding an Ubuntu semantic cache, an owner role is assigned only
if the optional S3 receipt file is present, nonsymlinked, bounded, has a
valid HMAC, and matches the exact timestamp, byte offset, question digest
and complete archive-row bytes. Duplicate receipts invalidate their record.
A guest or voice-probable S3 sidecar is not owner proof.

Missing, malformed, incorrect or rotated key → zero owner results. The
derived index records a one-way signing-key identifier. A subsequent owner
search checks that identifier against the current configured key, so
**revoking or rotating the receipt key immediately blocks stale indexed
owner data** even before refresh.

The existing 8-/9-file snapshot manifests remain accepted. The optional
tenth filename is allowlisted by the Python snapshot receiver but will not
be emitted by the *current* S3 firmware. No firmware source or live service
is changed by this stage. No SD formatting, flash, secret migration,
iPhone re-pairing, Open WebUI restart, audio-loop query or newly writable
Ubuntu memory database.

## Offline validation

The test suite constructs temporary S3-style conversations, signed owner
tickets and disposable SQLite indexes. It checks actual positive owner
retrieval after a valid receipt and negative cases for guest/learning
tickets, wrong audio, mismatched S3 bytes, forged offsets, repeated receipts,
wrong owner grant/session, missing keys, key revocation and symlinked input.

## Still required for live end-to-end private memory

- Independent, trustworthy human speaker issuer / owner verification.
  Candidate-only xvector similarity is inadequate.
- An already authenticated owner setup or explicitly approved bootstrap;
  the current phone connection alone does not establish owner proof. No
  manual public-key paste or phone re-pairing is requested by this stage.
- A firmware-compatible S3 worker acknowledgment and receipt **write** path,
  and optional tenth-file export (or an equivalent authenticated S3 write).
  These must be batched into a separate, deliberate future firmware change.
- Gateway integration that waits only outside the audio path and fails
  closed on missing or stale verification; one owner and one guest privacy
  hardware test after rollout.

**Status:** Verified-owner archival reader/receipt contract is staged in
GitHub source. It is **not installed on Ubuntu and private spoken recall
is not yet operational**. The existing repaired approved-public cross-call
recall remains the running baseline.
