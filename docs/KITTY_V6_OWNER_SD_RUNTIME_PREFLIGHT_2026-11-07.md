# Kitty V6 — on-host owner microSD receipt readiness (2026-11-07)

## Known result from running Ubuntu gateway preflight

The operator ran the standalone, read-only gateway preflight on the running Open WebUI container. It found `source=readable`, `syntax=valid`, exactly one client handler, exactly one provider handler, and candidate provider decode, S3 receive and common-route scopes. **All deeper trust/provenance checks remained `not_verified`; `deployment_ready=no`.** This is a gateway shape observation, not authenticated S3 microphone or receipt-write evidence.

## Added read-only host-side diagnostic

`server/kitty_owner_sd_runtime_preflight_v6.py` checks that the DEPLOYED Ubuntu server source files, not just GitHub, include the optional tenth receipt snapshot support and derived owner verification components. It parses Python AST without importing/running services or reading the snapshot, SQLite database, environment or keys. The diagnostic reads only five named Python modules under the explicit `--server-dir`. It prints closed labels and queries only `systemctl --user is-active kitty-memory-v6.service`. It does not change any files or services.

From the same Ubuntu repository directory:

```bash
cd "$HOME/kitty-v6/private/kitty-sync-deployment/live-sync-build"
git fetch origin main
git show FETCH_HEAD:server/kitty_owner_sd_runtime_preflight_v6.py | python3 - --server-dir "$HOME/kitty-v6/CuteDisplay/server"
```

Expected on-disk labels from an up-to-date deployment:

- `snapshot_owner_tenth_file=supported_on_disk`: the snapshot receiver's canonical `FILES` set includes the tenth `owner_turn_receipts_v6.tsv` and has the required size and finalize guard symbols.
- `memory_snapshot_endpoint=present_on_disk`: the memory service sources use the snapshot chunk/finalize receiver and refresh helper.
- `signed_owner_receipt_verifier=present_on_disk`: existing signed `owner-v1` HMAC and exact SD archive verification functions are present.
- `semantic_owner_attribution=present_on_disk`: the derived attribution reader recognizes only verified owner receipts for the reserved owner identity.
- `semantic_index_receipt_binding=present_on_disk`: semantic indexing loads owner receipt verification and key generation binding.
- `kitty_memory_user_service=active`: the fixed user service reports active at inspection time.

`running_process_module_revision=not_verified` remains mandatory: AST of files on disk cannot establish which modules the running Python interpreter imported earlier. `owner_receipt_signing_keys=not_checked`, `owner_sd_receipt_written=not_verified`, `live_owner_private_recall=no` and `deployment_ready=no` are unconditional. A green on-disk result is never permission to enable private recall.

## Still blocked

1. No confirmed separately authenticated S3 gateway socket identity or trusted S3 microphone-to-provider item capture binding.
2. No independent owner/guest/replay/voice-clone calibration with the actual CPU speaker model.
3. No actual S3 firmware ACK / receipt write / finalized tenth snapshot roundtrip recorded from hardware.
4. No proof the live memory process loaded the on-disk revision, and no rollback-tested disabled-by-default live gateway hook.

Preserve current working voice, approved shared public memory recall, Mac AI/TTS, C5, S3 SD and Ubuntu service. Do not flash or restart during these diagnostics.
