# Kitty V6 — realtime + SD sync work checkpoint (2026-10-30)

## Implemented on feature branch, NOT on live hardware or server
- An isolated, authenticated Ubuntu snapshot receiver accepts resumable per-file uploads and validates SHA-256. No live ESP32-S3 sender calls it yet.
- CPU semantic index supports speaker-attributed results, incremental generation replacement and multilingual vector search.
- Async bridge `bounded_semantic_context` caps the lookup at 180 ms by default and falls back to existing S3-local context on timeout or backend error.
- New guarded, opt-in Open WebUI patch `server/patch_openwebui_semantic_v6.py` integrates **one** semantic query at **realtime session startup only** when the client sends `kitty_semantic_v6=true` and a short `kitty_semantic_query`. Ordinary clients are unaffected. The existing S3 firmware does not yet send these fields. Live Open WebUI remains unchanged.
- Identity helper classes distinguish self-declared speaker claims from authenticated owner identity, but no trustworthy authenticated human-speaker session signal is available in today's microphone path. An authenticated device does not establish who is speaking. Owner-fact extraction remains legacy in running firmware.

## Not completed — do not claim full end-to-end V6
1. A dedicated ESP32-S3 uploader that reads only on the SD worker, transfers on a separate network task, rate limits sends while audio is active, authenticates over TLS, resumes interrupted chunks, and ships a complete consistent snapshot manifest.
2. A trusted explicit identity event from authenticated iOS control/session, per-turn source provenance and owner-fact gating in S3 extraction/corrections, with backward-compatible memory retention.
3. Per-turn query-aware semantic lookup in the live Open WebUI realtime tool/transcript path; currently only an opt-in **startup** hook exists. Needs compatibility tests on the pinned provider protocol.
4. Ubuntu deployment, secured storage paths, secret management, private network restrictions, snapshot cleanup/retention, CPU/RAM benchmarking and index refresh scheduling.
5. Successful CI, firmware compilation and acceptance tests in EN/FR/JA plus real audio under load.

## Safety
- Keep production `main`, Mac Ollama 16K Open WebUI context, Kitty voice/face/persona and server Docker image unchanged until verified.
- Do not install the patch directly in an unreviewed `realtime.py` container. It must be applied in a staged image with its dependencies available and tested against the exact running Open WebUI version.
- Index and snapshot copies contain personal data, not just anonymous vectors. Use private permissions, retention/deletion propagation and an authenticated transport; don't commit private SD records.
- System has additional disk work on iSCSI for model weights, indexes, snapshots and Python dependencies. Embedding inference is CPU/RAM-oriented, not disk-free.
- No voice biometrics. Spoken identity is only a claim, and must not grant owner write privileges.

## Rollback
All changes are currently code-only on `feature/kitty-semantic-v6-cpu`. No rollback on live devices is needed because no live service has been changed.
