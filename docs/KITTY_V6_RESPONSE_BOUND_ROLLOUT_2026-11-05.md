# Kitty V6 — guarded response-bound RAM continuity rollout (2026-11-05)

## Last validated baseline

- S3 realtime duplex audio working, C5 v38 working, microSD authoritative.
- Ubuntu Open WebUI healthy after rolling back the incompatible PR #6
  unsolicited upstream `session.update` feature. Prior call crash logged
  provider request rejection with `ValueError`; specific cause unproven.
- `kitty-memory-v6.service` running and approved shared-memory first-fit
  selection already updated. Only approved shared notes are session-global.
- The operator ran read-only:
  `response_bound_compatibility=compatible`,
  `deployed=no`, `provider_new_commands=none`, `private_recall=disabled`.

## What this feature does (and does NOT do)

- A new `ResponseBoundCallContext` instance is scoped to each realtime
  WebSocket; it sees only authenticated provider completed transcript/error
  events. Recent snippets are bounded in RAM and vanish at call teardown or
  inactivity expiration. No SQL, files, disk cache, background thread, HTTP,
  or SD write is added.
- It *may* append call-shared, quoted, untrusted conversation references to
  an **existing** client-origin `response.create.response.instructions` value
  **only if** that response already has nonempty string instructions. It
  never creates another upstream request, provider `session.update`,
  conversation item, or audio frame. Existing approved shared-memory additions
  are left intact.
- It is NOT owner authentication, private history recall, long-term memory,
  or a promise that the actual provider will accept additional instructions.
  Multi-person callers share the active call context; it must never carry
  verified or person-private facts across guest transitions.
- Provider event hotpath is filtered before the optional helper to avoid
  processing audio delta frames.

## Safe operator commands (host Ubuntu; Kitty not in a call)

From `~/kitty-v6/private/kitty-sync-deployment/live-sync-build`:

```bash
git fetch -q origin main
git show FETCH_HEAD:server/kitty_gateway_response_bound_rollout_v6.py |
  python3 - --check
```

Expected: `gateway=healthy`, `gateway_hook=compatible`,
`source_bind=readonly_verified`, `changes=none`. **Do not apply** if
any of those are missing.

If this passes, with Kitty idle:

```bash
git show FETCH_HEAD:server/kitty_gateway_response_bound_rollout_v6.py |
  python3 - --apply
```

Expected: `preflight=passed`, `gateway_health=healthy`,
`response_bound_call_context=installed`,
`call_memory_storage=volatile_ram_only`,
`durable_memory_authority=S3_microSD`.

This stops and restarts **Open WebUI** only after exact host/container SHA
validation, writes the known original gateway source to a private 0600 backup,
preserves the existing read-only source bind inode, and checks health and
source checksums after restart. It copies optional Python **source code** into
the running container; **no conversation content** is copied to disk.
The installed SHA is saved privately for future rollback after `main` moves.

To rollback the gateway at any time:

```bash
git show FETCH_HEAD:server/kitty_gateway_response_bound_rollout_v6.py |
  python3 - --rollback
```

The rollback reuses the source version pinned in the private installation
state. It refuses to overwrite a gateway source that was independently edited.
If rollback prints `requires_manual_review`, stop and inspect rather than
running a blind replacement.

## Minimal two-call smoke test

1. With no conversations in progress, apply and confirm Open WebUI healthy.
2. Start a **short** normal voice call: "Hi Kitty, how are you?" Verify
   conversation still succeeds. If it fails, rollback and stop testing.
3. Start a new test call and say:
   - "We are planning a fictional planet called Crystal Moon."
   - "Crystal Moon has purple oceans and three suns."
   - "Remind me: what is the name of our planet and what color are the oceans?"
   Expect **Crystal Moon, purple**. This validates same-call behavior only.
4. End the call; a new independent call should **not** remember Crystal Moon
   from this RAM scratchpad unless it was separately and explicitly saved as
   approved shared SD memory.
5. Any `AUTH_OR_PROVIDER_ERROR`, provider request rejection or newly
   unstable audio requires **immediate rollback**. Do not flash S3/C5.

Note: A passing Python AST preflight and offline simulated provider events
do not certify the live model/provider behavior. If a real `response.create`
arrives without a string `response.instructions`, this feature intentionally
does nothing and the trial will not prove RAM recall is operational.

## Private memory remains restricted

There are 373 derived semantic index records from the latest checked snapshot,
but 0 verified-owner indexed records and no deployed independently attested
human speaker issuer. Do not enable owner/private lookup based on xvector
probability, self-introduction, BLE pairing, device tokens or SD sidecars.
Building a trusted exact-turn identity issuer remains a separate next stage.
