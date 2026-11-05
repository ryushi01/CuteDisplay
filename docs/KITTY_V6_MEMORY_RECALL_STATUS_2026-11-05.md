# Kitty V6 memory recall status — 2026-11-05

## Non-negotiable architecture

- Freenove ESP32-S3 microSD is the **only durable memory authority**.
- Ubuntu stores disposable SD-derived snapshots/indexes only, not independently
  accumulated personal memories. A temporary same-call working set may use RAM
  but must be bounded and cleared when the WebSocket closes.
- Do not issue owner-private recall from device credentials, names in speech,
  probabilistic xvector/ECAPA matches, BLE pairing, or `speaker_claims_v6.tsv`.
- Do not reapply PR #6's provider `session.update` injection: its first live
  test caused a provider rejection / closed call. The original gateway was
  restored with `--rollback` and verified healthy; subsequent baseline call
  succeeded. Exact rejection origin was not demonstrated.

## Verified 2026-11-05 diagnostics (read-only)

- Snapshot: present and recent, `auto_refresh_enabled=true`.
- `conversations.tsv`: nonempty; `speaker_claims_v6.tsv`: nonempty;
  `shareable_memories_v6.tsv`: nonempty.
- `facts.tsv`, `dated_plans.tsv`, `summaries.tsv`: empty in export.
- `unverified_summaries_v6.tsv`: **missing from export BY DESIGN**, not
  evidence of missing on-device summaries. S3 writes unverified summaries
  to this private file; S3's canonical nine-file `EXPORT_NAMES` excludes it.
- Derived semantic index: 373 rows; 373 attributed; 0 `person:owner`,
  0 `session_verified`, 47 `voice_probable`, 3
  `explicit_introduction`. Thus indexed records are not automatically
  releasable as verified owner memories.
- The Open WebUI gateway contains approved shared-context injection and
  persistence through client `session.update` / `response.create`.
  The experimental RAM hook is absent. No trusted per-turn speaker issuer
  is deployed. Owner-private history remains disabled.
- Past S3 summary journal advanced and queues drained; earlier saved=6 was
  observed. This validates accepted summary processing but does not license
  exposing their private content to unidentified callers.

## Two bounded corrections in this change

1. **S3 speaker-claim TSV second-clause fix.** An utterance containing a second
   independent preference could be written with double-escaped `\\t` and
   `\\n` in the second `scoped2.printf()`, damaging that record and
   potentially adjacent rows. Replace with actual C++ tab/newline escapes.
   Add a source-contract regression. Existing SD bytes are never rewritten;
   this source fix only takes effect after a deliberate future S3 firmware
   update/flash, preferably batched with other planned fixes.
2. **Ubuntu approved-shared context first-fit improvement.**
   `kitty_shareable_memory_v6.shareable_context` previously `break`ed
   when a shared item exceeded remaining 520-character budget, suppressing
   smaller *already approved shared* items appearing later. Now skip that
   oversized item and continue. No owner-private data source or SD writes
   were added. The change takes effect only when the server-side source is
   deliberately deployed to the active memory service.

## Remaining implementation work

1. Design and install a **trusted independently attested owner session and
   exact provider-item/transcript proof**. Only that issuer may unlock
   owner-private SD history; test owner/grant expiration, guest transitions,
   multi-person calls, barge-in, replay, and session cancellation.
2. For long same-call continuity, use the **already supported existing
   client command/response path** with a bounded ephemeral in-memory summary.
   Validate true provider protocol compatibility and prevent untrusted
   transcripts from becoming privileged instructions. Avoid another
   automatically generated provider `session.update` injection.
3. Determine whether approved shared entries reach the actual model on a
   live query; a present file and gateway source markers are not end-to-end
   proof. The approved shared budget remains 520 chars server-side and
   approximately 480 bytes S3 side; do not claim all approved items are sent.
4. Verify speaker-claim parsing and historical recovery in a separate,
   read-only project stage before any SD migration. Do not silently promote
   historical `voice_probable` claims into verified owner facts.
5. Keep firmware reflash count minimal. Do not alter S3 SD memory or voice
   profiles while proving the live recall path.

## Safe operational state

- Stable Open WebUI resumed after rollback; no PR #6 live patch.
- No firmware, audio path, SD contents, memory authorization or identity
  permissions were changed by these GitHub edits.


## 2026-11-05 response-bound same-call continuity increment (SOURCE ONLY)

The first experimental volatile RAM feature in blocked PR #6 sent an
unsolicited upstream \`session.update\` and was rolled back after the first
live-call failure. The exact provider rejection source was not proven.
**Do not redeploy that feature.**

The new source-only module \`server/kitty_response_bound_call_context_v6.py\`
holds a bounded extractive, unverified **call-shared** scratchpad in one
per-WebSocket Python object. It only observes completed authenticated
provider-side transcript events. It does not create a global transcript log,
persistent store or any new network request. It is not a speaker verifier.

The new pure gateway transformer
\`server/kitty_gateway_response_bound_patch_v6.py\` requires the previously
deployed passive-provider and approved-shared response markers, and fails
closed on unexpected AST scope/forwarding. It has a **read-only** \`--check\`
command that prints only fixed compatibility statuses. **No apply command is
provided**: runtime remains unchanged until the exact live route has passed
this check, the provider behavior has been verified without disrupting audio,
and a fully reversible deployment is independently reviewed.

Unlike PR #6, the proposed route never sends any extra provider event:
it can only append bounded, quoted, untrusted references to the existing
\`response.create.response.instructions\` field, **if that field already exists
as a string**, leaving the model persona, approved shared context and all
other message fields unchanged. If the field is absent, the helper does
nothing. This is designed to avoid speculative provider protocol commands,
but compatible source topology plus passing tests are **not** proof of
end-to-end behavior on the Mac inference delegation path.

A quote from an unknown speaker cannot unlock SD owner memories, assign
a trusted speaker or persist new facts. Call-shared continuity is visible to
all participants in the current call; do not confuse it with verified
speaker-private memory. Confidential statements are filtered on a best-effort
basis only; the helper must never be reused across calls or accepted as a
privacy boundary for speaker-specific facts.

Offline integration tests simulate provider-to-client forwarding, one original
client-to-provider response command, context binding, deduplication,
expiration, sensitive-input filtering and no additional provider sends.
The existing S3/C5 realtime firmware and private Ubuntu host gateway are
unchanged. No flash, SD migration, model change, new disk data or live
service restart is part of this increment.
