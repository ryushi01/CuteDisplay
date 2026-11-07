# Kitty V6: call-start disconnect after approved public query rollout

## Report and suspected failure
- After PR #14 approved-only cross-call recall deployment, the user reported **Brain disconnected when starting a call**. No live provider/S3 error log is yet available, so the cause is NOT proven.
- PR #14 copied Python helper source into Open WebUI with 0600 permissions. Docker cp can make these root-owned, while the WebUI worker might be unprivileged. The helper is lazily imported as a call starts, so the container health check cannot reliably detect PermissionError. In addition, its optional import previously did not catch OSError.
- This hotfix retains the improved approved-only recall; it is not a rollback to the prior no-query feature.

## Source changes
- Only two container Python helper modules are changed. Optional recall import/observe/decorate/cleanup failures are fully isolated from the existing realtime voice connection.
- Code-source deploy permissions are 0644, while private backup/configuration and rollback state remain 0600.
- An explicit import smoke test runs as non-root UID 65534 inside Open WebUI before and after one controlled container restart; it loads both helper modules and instantiates the per-call context without opening a provider or reading private memory.
- Background public-memory lookup is now restricted to actual questions and explicit recall requests, not every greeting/utterance. It remains local-only and private semantic recall remains disabled.
- The --repair path checks the exact hashes of the currently deployed PR #14 transaction, keeps the host memory service and realtime.py untouched, updates two helpers, verifies health/import, and updates the existing transaction manifest to preserve its exact-hash protections. A failed hotfix automatically restores the installed improved source versions rather than reverting the feature.

## Ubuntu next step (Kitty idle)
After GitHub PR #15 merges and offline tests pass:

    cd "$HOME/kitty-v6/private/kitty-sync-deployment/live-sync-build"
    git fetch -q origin main
    git show FETCH_HEAD:server/kitty_public_recall_rollout_v6.py | python3 - --repair

Expected: approved_public_recall=repaired; call_helper_nonroot_import=verified; memory_service=active; open_webui=healthy; voice_gateway_route=unchanged; owner_private_recall=disabled; s3_c5_sd_iphone=unchanged.

If it reports an integrity/refusal status, stop; do not override custom or partially installed files.
One normal voice call is the only initial live test. If Brain still disconnects, collect a limited redacted error-category probe for Open WebUI, S3 and provider rather than making further speculative changes.

## Boundaries
- Do not re-pair the iPhone, request pasted public keys, change Bluetooth/C5 firmware, flash S3, move models or reset the SD.
- No trusted speaker issuer is connected; owner-private history stays inaccessible to voice-probable matches.
- A passing offline test and smoke import prove neither a full network call nor Mac-provider integration. The exact cause of the reported disconnect remains unverified until hardware/log observation.
