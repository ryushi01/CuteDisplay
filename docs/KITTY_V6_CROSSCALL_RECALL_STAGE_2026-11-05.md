# Kitty V6 cross-call recall — approved-only query stage (2026-11-05)

## What is already configured

- iPhone app pairing, BLE setup and everyday Kitty calls are working. **Do not request another iPhone setup, Secure Enclave public key copy, password, API key or firmware flash** for this stage.
- `kitty-memory-v6.service` was last observed active; approved shared-memory first-fit selection was installed.
- Physical S3 microSD is the durable memory authority. Ubuntu's finalized snapshot and SQLite semantic index are disposable derived state.
- A read-only November 5 probe counted 373 attributed indexed rows, 0 verified owner entries, 47 probable voice and 3 self-introduced entries.
- An enrolled owner public key, grant secret and trusted speaker-ticket issuer were **not** configured. Existing Bluetooth pairing and voice probabilities cannot authenticate private history.

## This source-only change

`server/kitty_shareable_memory_v6.py` adds an optional `query`
argument to existing `shareable_context()`: ranked, bounded lexical lookup
only within exact `shared` rows of `shareable_memories_v6.tsv`. No query
retains the formerly deployed call-start behavior. A query with no relevant
match returns an empty result rather than unrelated context.

The existing authenticated `POST /shared/context` can now take an optional
string `query` (1–300 chars), preserving legacy request `{}`. The
lookup reads only the newest finalized S3-derived snapshot. No new DB or
extra durable store, no SD write, no read of `facts.tsv`, `summaries.tsv`,
`conversations.tsv`, `speaker_claims_v6.tsv`, or private owner records.

`server/kitty_semantic_async_client_v6.py` has optional
`shared_context_for_query` for a future nonblocking gateway integration.
It only accepts a local memory service URL, uses the existing bearer
credential and a bounded timeout, and never authorizes owner-private recall.

Existing gateway imports and response dispatch are unchanged by these source
files. **No live voice gateway wiring or deployment has yet been performed.**
This stage creates the approved-only query retrieval path, not a claim of
fully working on-demand voice retrieval.

Offline regression tests verify approval boundary, late approved entries,
private archive and speaker-claim exclusion, bearer auth, invalid query
refusal, local transport restriction and fail-closed timeout.

## Remaining work

1. Deploy the small memory-service source change behind exact byte checks,
   known backup and immediate rollback, preferably while Kitty is idle.
2. Integrate optional async approved-only query lookup into the existing
   response-bound gateway path. It must not emit a new provider event or await
   network I/O in an audio event handler. Verify exact upstream event/item
   ordering and drop stale responses.
3. One short cross-call approved-note voice test is sufficient once integrated.
4. **Private speaker-specific recall still requires independent exact-item
   attestation and owner authentication.** Do not reclassify unverified
   historical archives or treat the configured phone as proof of speaker
   identity. A deliberate owner verification experience might be necessary
   for private facts, but do not demand new pairing or pasted keys.

The owner-enrollment prototype PR #11 is merged source, not configured on
Ubuntu, and its iPhone UI is not a prerequisite for this public-only work.
