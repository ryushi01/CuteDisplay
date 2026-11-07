# Kitty V6 — private cross-call memory: signed-turn gate (2026-11-07)

## Confirmed working hardware state
- The latest approved public-memory repair (PR #15) was applied on Ubuntu with `approved_public_recall=repaired`, `call_helper_nonroot_import=verified`, `memory_service=active`, and `open_webui=healthy`.
- The user verified Kitty speaks back normally and remembers/explains previously approved shared `Mochi Planet` across calls. This validates shared recall but not new private recall or targeted query retrieval.
- Preserve existing iPhone pairing, S3 realtime audio/microSD, C5 v38, Mac AI/TTS, approved shared recall, and live Open WebUI route. No firmware flash, SD format or repacking.

## Security gap repaired in source
The old memory-service `/semantic` and `/semantic/context` authorized an owner-private query with a valid signed owner-session grant alone. That proves an enrolled session but NOT which human is speaking now. A copied still-live grant could be used as a private history bearer credential. Voice confidence, self-introduction, connected device and Bluetooth pairing are not owner authentication.

Both private routes now require, *in addition to* the existing authenticated local memory service bearer token:
1. An enrolled-key owner session grant for the current server-created session.
2. An independently issued signed *human speaker attestation* with `role=owner`, `speaker=person:owner`, `purpose=turn`, and the same session ID, upstream provider item ID and exact completed transcript digest.
3. The search `query` must exactly equal that authenticated completed transcription, so the owner ticket cannot authorize arbitrary unrelated searches. The issuer secret must be independent of the owner grant key.

All missing, expired, replayed-for-another-session, wrong-item, changed-transcript, wrong-role, learning-only or unsigned requests fail closed with no semantic index read. An optional owner history request carries the exact current signed ticket from `AttestedLiveCall`, which still cancels stale replies on subsequent speech, barge-in, owner switch or disconnect.

## S3 source provenance
- The S3 SD is permanent memory authority; existing Ubuntu semantic index is a derived, disposable reader.
- An SD-editable `turn_sources.tsv` guest row with `speaker_id=person:owner` is now rejected (owner-role sidecars were already rejected). `speaker_claims_v6.tsv` probable owner rows are not indexed as owner.
- Derived semantic owner search and context require the owner role and session-verified provenance. No legacy guessed speaker claims or unverified S3 summaries are silently upgraded to an authenticated owner memory.

## Important: live deployment is NOT authorized yet
At the last measured checkpoint, there were **0 independently verified-owner indexed records** and no deployed independently trusted human speaker attestation issuer. The owner key/grant secret setup was also reported as absent. Thus the new private endpoints remain **disabled by design**. Existing iPhone setup/Bluetooth pairing cannot replace proof of the human speaker.

Only the independent signer that actually verifies the person for each provider-captured turn should ever hold `KITTY_TRUSTED_TURN_ISSUER_SECRET_HEX` (also provisioned locally to the memory verifier). Never create it automatically from the device API token, model speaker score, `speaker_claims_v6.tsv`, name spoken aloud, or inferred phone owner. Secret provisioning is deferred; no keys need to be pasted into chat.

To complete end-to-end *live* private recall later, the system still needs a trusted turn issuer (and independently enrolled owner proof), a verified-owner record writer on S3 that cannot be forged via SD-editable sidecars, and a bounded response-bound gateway consumer with live privacy and interruption tests. Do not deploy the source-only gate over the working production memory service before verifying the whole trusted issuer and store path; the current working approved-shared system should remain untouched.

Offline tests exercise forged, guest, learning, expired, wrong-session/item/transcript/query, missing credential, malformed derived index and private owner context filtering. The secure default is **no private recall**, not a false claim that private speaker memory already works.
