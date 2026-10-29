# Kitty Memory v2 — Experimental implementation (2026-10-29)

**Recovery baseline:** `main` commit `5458dd4d3f0e6a9744729ff1312e72898cf85b3d` and `checkpoint/2026-10-29-main-before-memory-v2`. New code lives on `feature/memory-v2-lifecycle`. Do not merge until full CI and hardware regression tests.

## 3. Corrections, confidence and supersession
- Added 256-entry PSRAM metadata for update timestamps, expiry and confidence, persisted in a **separate** `/kitty/factsmeta.tsv` snapshot. `/kitty/facts.tsv` remains the original two-column format for backward compatibility.
- Direct facts use confidence grade 100, AI-extracted proposals 70 (heuristic origin labels, not statistically calibrated probabilities).
- Explicit EN/FR/JA workday statements use canonical keys such as `routine_work_monday`. A later contradictory statement replaces the active value and records the old value in `/kitty/corrections.tsv`.
- Arbitrary natural-language contradiction handling is not yet comprehensive. Existing preference deduplication and same-key replacements continue working.

## 4. Permanent vs temporary
- Identity, preferences, jobs and undated notes remain permanent until corrected or removed.
- Time-qualified upcoming plans for today/tomorrow in English, French or Japanese receive a bounded 24–48-hour expiry. Other dates are intentionally **not guessed** and currently remain until corrected.
- Expired plans are filtered from structured and upcoming-plan recall but remain in the historical SD archive.
- Date classification is conservative, not a full calendar or natural-language date engine.

## 5. Compact conversation summaries
- The SD worker batches six bounded user utterances and enqueues one best-effort summary request. The existing low-priority AI analysis worker operates only after 20 seconds idle, never during realtime audio.
- Successful concise summaries are appended to `/kitty/summaries.tsv`; newest summary is restored at boot and injected into bounded AI / realtime authentication memory context. Old summaries expire from active context after seven days but remain historical records on SD.
- No additional Ubuntu model or memory database is required; uses existing Open WebUI/Ollama endpoint. Model timeouts or device activity may skip summary generation.

## 6. Live memory refresh — protocol included, deployment required
- The S3 now opts in with `kitty_memory_refresh=true` during authenticated realtime WebSocket setup. Older Open WebUI gateways silently ignore it, retaining original audio behavior.
- New server extension `server/patch_openwebui_memory_refresh.py` advertises `kitty.memory.capabilities` only to authenticated, opted-in Kitty sessions and accepts bounded, revisioned `kitty.memory.refresh` events.
- It replaces the previous current-memory system-context item in the **existing provider conversation**, without restarting the call; the S3 sends only during idle voice-output windows and waits for feature negotiation.
- The extension is version-guarded, fails closed on incompatible source, and is included in the optional Dockerfile. Offline protocol tests run in GitHub Actions. **The patch has not been deployed to the currently running Ubuntu/Open WebUI service; live refresh will not activate there until that deployment and end-to-end testing.**
- On a gateway without this extension, session memory remains the initial snapshot (delegated AI requests continue to use fresh SD memory on each request).

## Validation and safe rollout
1. Compile combined S3+C5 firmware, run `server/test_patch_openwebui_memory_refresh.py`, review GitHub Actions; retain checkpoint.
2. Verify existing SD facts load unmodified, and `factsmeta.tsv` survives reboot. Never format the SD card for this upgrade.
3. Test explicit workday correction across English, French and Japanese, plus `corrections.tsv` history.
4. Check only relative today/tomorrow plans expire, and older plans remain in the SD archive.
5. Say six factual project statements; leave idle; inspect `summaries.tsv` and reboot/session recall.
6. Test realtime voice, barge-in, lip animations, I2S stack and RAM headroom before any server change.
7. Only after matching server patch is installed on the **pinned running image** and a verified backup made: reconnect a call once for negotiation, teach a new fact during the call, let audio finish, confirm `[CALL MEMORY] context refresh accepted`, then ask about it in another language without reconnecting.
8. Roll back server image and feature firmware to the saved baseline if audio or provider errors occur.

Do not treat a successful CI compile as evidence of working hardware or a completed server deployment.
