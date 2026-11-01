# Kitty V6 checkpoint — 2026-10-31 (JST)

**Continuation branch:** `feature/kitty-semantic-v6-cpu`  
**Repository:** `ryushi01/CuteDisplay`  
**Ubuntu checkout:** `/home/ryushi/kitty-v6-validation`  
**Server:** `ryushi@ai-server` (Ubuntu)  
**Goal:** Continue working speaker-aware semantic memory, preserving real-time voice, expressive C5 face, and OTA.

## Current working system — do not regress

- Dual-board: LILYGO T-Display-C5 (C5, firmware v35) renders full-screen kitty emotions and talking animations; Freenove ESP32-S3-WROOM CAM N16R8 (S3, S3-only firmware v5) runs Wi-Fi, audio (INMP441 microphone, MAX98357A speaker), camera hardware, microSD, and UART to C5.
- Real-time voice works responsively, no cut-outs in last successful test. **Do not flash either board** unless truly needed.
- Open WebUI domain `https://ragnarok-project.com`; Docker service/container `open-webui`; image previously `cutedisplay/openwebui:kitty-v6-https-ota-prepared`.
- Animations, `kitty.memory.refresh`, and HTTPS OTA Update Center were functioning before semantic integration.
- OTA prior issue: staged download overflowed loopTask; S3 v5 moved staging into a dedicated 24KB worker. New staging not yet fully end-to-end verified.
- GitHub code on this branch contains CPU semantic index / client, snapshot and attribution code and gateway patch script.

## Completed semantic-memory work

1. Existing Ubuntu memory service `kitty-memory-v6.service` (systemd **user** unit) listening on host loopback `127.0.0.1:8766` is healthy. Its config is `/home/ryushi/kitty-v6/private/memory-service.env`. `KITTY_MEMORY_DB=/home/ryushi/kitty-v6/private/memory.sqlite3`, `KITTY_SD_SNAPSHOT_ROOT=/home/ryushi/kitty-v6/private/snapshots`.
2. 104 snapshot directories, 103 `speaker_claims_v6.tsv` files; latest `speaker_claims_v6.tsv` size 0. Latest exported `voice_profiles_v6.json` size 0; host `/home/ryushi/kitty-v6/private/voice_profiles_v6.json` holds `{"version":..., "speakers": {}}` (zero enrolled).
3. Built `/home/ryushi/kitty-v6/private/semantic/memory-v6.sqlite3` with `server/kitty_sd_semantic_index.py build --sd-copy /home/ryushi/kitty-v6/private/snapshots/snapshot-s3_1793437898_6e00e6ab --db /home/ryushi/kitty-v6/private/semantic/memory-v6.sqlite3`. Result: **49 indexed / 49 embedded**, model `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`; every index entry `speaker_id='unknown'`, `provenance='unverified'`. **Do not falsely assign records to the owner**.
4. Added `KITTY_SEMANTIC_DB=/home/ryushi/kitty-v6/private/semantic/memory-v6.sqlite3` to memory-service env, backup `memory-service.env.backup-semantic-v6`, and restarted `systemctl --user restart kitty-memory-v6.service`; subsequent `curl http://127.0.0.1:8766/health` gave `{"ok": true, "pending": 0}`.
5. Derived patched Open WebUI gateway using `python3 server/patch_openwebui_memory_refresh.py --source-root /tmp/kitty-memory-check --apply` from the running gateway. Full-size patched `realtime.py` and `kitty_semantic_async_client_v6.py` saved under **`/home/ryushi/kitty-v6/private/semantic-gateway/`**, not necessarily committed in this GitHub repo; `realtime.py` changed import to `from open_webui.kitty_semantic_async_client_v6 import semantic_context`.
6. Live server semantic client additionally patched to support private Unix HTTP endpoint `unix:///run/kitty-semantic/memory.sock` (original GitHub client only accepts `http://127.0.0.1:`); `kitty_semantic_async_client_v6.py.backup` holds pre-bridge version. A host-side `memory_socket_bridge.py` forwards a shared volume Unix socket to host `127.0.0.1:8766`; systemd user service `kitty-semantic-bridge.service` enabled and active, socket at `/home/ryushi/kitty-v6/private/semantic-gateway/memory.sock`.
7. **Deployment:** Compose override `/home/ryushi/kitty-v6/private/kitty-sync-deployment/kitty-semantic.override.yaml` sets `KITTY_SEMANTIC_SERVICE_URL=unix:///run/kitty-semantic/memory.sock`, supplies `KITTY_MEMORY_TOKEN` from private env, mounts patched gateway `realtime.py`, semantic client module, and private socket directory. Applied with four Compose files:
   - `/home/ryushi/docker-compose.yaml`
   - `/home/ryushi/kitty-v6/private/kitty-sync-deployment/kitty-sync.override.yaml`
   - `/home/ryushi/kitty-v6/private/kitty-sync-deployment/kitty-ota.override.yaml`
   - `/home/ryushi/kitty-v6/private/kitty-sync-deployment/kitty-semantic.override.yaml`
   via `sudo --preserve-env=KITTY_MEMORY_TOKEN docker compose ... up -d --no-deps open-webui`. Do not omit an override on later Compose calls.
8. **Last verified state** after deployment:
   - `sudo docker inspect open-webui --format '{{.State.Status}} / {{if .State.Health}}{{.State.Health.Status}}{{end}}'` → **running / healthy**.
   - `sudo docker exec open-webui python -c 'from open_webui.kitty_semantic_async_client_v6 import semantic_context; print("Semantic client: OK")'` → **Semantic client: OK**.
   - `systemctl --user is-active kitty-semantic-bridge.service` → **active**.
   - Docker environment `KITTY_SEMANTIC_SERVICE_URL=unix:///run/kitty-semantic/memory.sock`, token configured (`True`). **No end-to-end authorized semantic lookup yet; bridge transport has not been proven with a real speaker request.**
   - Docker network `ryushi_ai-network`, container IP `172.19.0.2`, bridge gateway `172.19.0.1`. Existing container `open-terminal`, orphan `ryushi-kokoro-web-1`; DO NOT remove orphans or volumes.

## Known code path and actual blockers

- The S3 code `firmware/CuteDisplayBrain/BrainRealtimeDirect.h` listens for `kitty.speaker.result` with `item_id`, `speaker_id='person:...'`, `confidence='probable'|'claimed'`, queues attributed transcript and requests `kitty.memory.semantic` with speaker and provenance. Without a speaker-result event, transcript is queued as `unknown`.
- The deployed gateway `realtime.py` handles `kitty.memory.semantic`, schedules async semantic lookup, and sends `kitty.memory.semantic.result` to S3; **does not generate `kitty.speaker.result`**.
- Existing `server/kitty_memory_service.py` has `/speaker/identify`, but intentionally returns `speaker_transport_not_enabled` and has no enrolled voice samples. It cannot be enabled simply by setting a flag. Need actual bounded speaker enrollment + CPU voice embedding/matching and realtime per-item attribution.
- Semantic client timeout currently **0.35 seconds** including model startup. CPU first-load may take much longer; address by warm worker/preload, async execution, or safe timeout policy without blocking audio.
- `kitty.memory.semantic.result` is cached briefly by S3 and **not injected into the upstream Realtime AI response/session** to prevent cross-speaker leakage; normal realtime replies may never consume it. Need proper per-turn speaker-scoped context delivery and explicit expiry on speaker change; do not persist a guest's memories in shared system instructions.
- Snapshot sidecar `turn_sources.tsv` and `speaker_claims_v6.tsv`: S3 `KittyMemory.h` writes claims only with a non-unknown speaker, approved provenance and extractable fact. Historical 49 unverified entries must stay unassigned without evidence.
- Voice matching is *probabilistic*, not owner authentication. Never bypass owner proof or claim a registered speaker is verified owner.

## Next implementation priorities — fast path, not repeated diagnostics

1. Implement bounded, CPU-only speaker enrollment and recognition against opted-in voice samples; define transport from realtime WebUI to local service without disturbing WebSocket audio forwarding. Return `kitty.speaker.result` **bound to the correct `item_id`**; unknown/no match stays unknown. Keep voice data private; no automatic retention. Reuse existing voice-profile skeleton if useful.
2. Deliver retrieved memories to the AI **for that identified turn only** with strict session/speaker/turn binding and cancellation on new speech. Confirm API protocol sequencing before patching. Do not use session-global instructions for guest private data.
3. Ensure CPU model preloading and timeout policy do not interrupt or slow voice; test one real enrolled voice turn then one unknown/guest turn for leakage.
4. Confirm semantic service index update on subsequent finalized S3 snapshots; currently the service was restarted with `KITTY_SEMANTIC_DB` set, so future refresh worker may update the index.
5. Export/commit Ubuntu-only semantic integration files after reviewing for tokens and private data. **This checkpoint documents those host changes but does not itself commit their bytes.**

## Safe continuation commands (prefer consolidated blocks)

```bash
cd ~/kitty-v6-validation
git status --short --branch
systemctl --user is-active kitty-memory-v6 kitty-semantic-bridge
sudo docker inspect open-webui --format '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{end}}'
# Never print or commit KITTY_MEMORY_TOKEN, Compose private env, TLS keys, audio samples or private snapshots.
```

To recreate container use **all four** Compose files; export the token from private env only in process scope and unset afterward. Do not use `--remove-orphans`, `down -v`, or reflash S3/C5.

## Working style for next chat

The user wants **fast implementation**: deliver concrete code, bundled command blocks, minimal diagnostics, and one controlled restart rather than back-and-forth single checks. Run tools and make GitHub changes where authorized; do not claim server private files were committed unless the user actually runs a verified Git commit/push. Preserve existing functioning features; avoid exposing secrets.

## Resume prompt

> Continue Kitty V6 from `docs/KITTY_V6_CHECKPOINT_2026-10-31.md` in `ryushi01/CuteDisplay` branch `feature/kitty-semantic-v6-cpu`. Live Open WebUI is healthy with a Unix-socket semantic bridge, memory service has a 49-entry index but all speakers unknown. Implement actual speaker enrollment/identification and per-turn realtime semantic recall rapidly, with consolidated command blocks and minimal tests. Keep audio, expressive C5 face, OTA, private memories and existing volumes safe. Start by inspecting Git branch/current code and distinguishing remote from uncommitted Ubuntu deployment files.
