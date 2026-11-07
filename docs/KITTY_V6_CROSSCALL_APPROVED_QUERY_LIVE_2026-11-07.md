# Kitty V6 — approved-only cross-call query rollout (2026-11-07)

## Confirmed baseline
- Phone setup/BLE pairing already working. No new iPhone configuration or keys.
- User confirmed memory_service=active, response_bound_hook=present, response_bound_helper=present, approved_shared_hook=present; no changes were made by the check.
- Physical ESP32-S3 SD is permanent memory authority; C5 v38/audio and gateway are working.
- 373 attributed semantic index rows, 0 verified-owner rows in last probe. Probable voice ID is never human authentication.

## Scope of source changes
- The optional ApprovedLiveQuery object belongs to a single realtime WebSocket. Only authenticated-provider completed user transcriptions trigger a local, token-protected /shared/context query.
- The query only searches exact shared visibility entries in the latest finalized S3 snapshot. It never reads speaker claims, conversations, private summaries, facts or owner semantic history.
- No extra upstream provider command, session.update, audio frame, model call or permanent database is added. If the background query is not ready, the original response goes through untouched.
- Results are bounded, included as untrusted quoted data only on an existing response.create with string response.instructions, and discarded when superseded or expired. No owner grant or voice confidence is involved.
- Open WebUI realtime.py is NOT modified. The existing per-call response-bound helper gets an optional local query helper. The memory-service endpoint supports the optional public query from PR #12.

## Guarded rollout
With Kitty idle, from ~/kitty-v6/private/kitty-sync-deployment/live-sync-build:

    git fetch -q origin main
    git show FETCH_HEAD:server/kitty_public_recall_rollout_v6.py | python3 - --check
    git show FETCH_HEAD:server/kitty_public_recall_rollout_v6.py | python3 - --apply

The rollout fails closed on unexpected source hashes, conflicting modules, missing local service URL/token or unhealthy services. It backs up the exact two previous host memory-service sources and the existing response helper in private mode-0600 files. It restarts memory service and Open WebUI, checks health and source hashes, and automatically attempts full restoration after failures. Never run during a call.

Successful output must include memory_service=active, open_webui=healthy, approved_public_query=installed, voice_gateway_route=unchanged, owner_private_recall=disabled, sd_firmware_iphone=unchanged.

Manual rollback (using the same pinned version of the script):

    git show FETCH_HEAD:server/kitty_public_recall_rollout_v6.py | python3 - --rollback

The rollback fails closed rather than overwriting an independent local edit. If automatic rollback reports requires_manual_review, stop rather than blindly replacing a private bind-mounted route.

## Minimum validation
1. One normal voice call (audio and responses still working).
2. A fresh subsequent call asking about the previously approved Mochi Planet shared memory. It must be recalled, but this could still come from the existing startup shared context; do not claim that alone proves the new async lookup.
3. A discriminating test needs a separately approved public note beyond the startup context budget. Never promote an unverified private historical record just for testing.

## Not included
Private owner memory, guest-specific recall, trusted speaker-ticket issuance, iPhone key enrollment, S3 or C5 flash, SD rewrite and additional permanent Ubuntu storage. Historical voice_probable rows remain unverified.
