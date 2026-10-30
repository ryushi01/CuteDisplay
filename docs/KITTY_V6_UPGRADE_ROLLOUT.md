# Kitty Semantic Memory V6 — staged upgrade rollout
Date: 2026-10-30
Status: **candidate source branch, NOT production-ready**. Never flash or apply to live Open WebUI until the mandatory gates below pass. Stable `main` and the known-good combined firmware remain the rollback targets.

## Target deployment
- S3 microSD is canonical for `conversations.tsv`, `turn_sources.tsv`, `speaker_claims_v6.tsv`, `facts.tsv`, dated plans, summaries and consented `voice_profiles_v6.json`.
- Ubuntu VM on MS-01: existing Open WebUI + new separate CPU-only voice-ID service (localhost :8772) + CPU semantic-memory index and private SD snapshot receiver. Prevent inference and HTTP upload from blocking voice event loops.
- Mac M4: **no change** to existing Ollama/Qwen3.5 9B, Whisper STT or Qwen3-TTS.

## Optimization pass (completed in source)
- Realtime voice worker accepts only one CPU recognition job at a time; excess work falls back to UNKNOWN instead of creating CPU backlog.
- Ubuntu voice HTTP service also refuses concurrent inference with HTTP 503, protecting realtime gateway latency during overload.
- Gateway stores up to three completed utterance buffers for rapid speech, rather than overwriting one pending sample.
- The guarded Open WebUI patch's event-relay newline construction and regular expression were corrected. **No production image has been patch-verified.**
- A timeout is not a hard cancellation of the already-running thread; keep model CPU service isolated and benchmark under load.

## Gate A — secure backup and sizing
1. Record current S3/C5 versions, the combined firmware artifact ID, branch and Open WebUI container image digest; take a full **read-only copy** of the S3 SD `/kitty` tree before any firmware change.
2. Check Ubuntu `free -h`, `nproc`, `df -h /`; document baseline CPU, available RAM, iSCSI free capacity, current WebUI API and model response latency. Do not size based solely on the presence of Ubuntu.
3. Back up the *running* `realtime.py` and take a Docker configuration and volume snapshot. Never overwrite the existing Open WebUI production Python source in place.
4. Inspect pinout and confirm S3 24k PCM input and audio frame format are identical to the tested stable build. Mac stays untouched.

## Gate B — isolated Ubuntu voice pilot
1. Install Python dependencies in a dedicated venv, with locked versions in the deployed environment. Initial CPU model download needs temporary outbound internet and sufficient storage.
2. Build a private voice profile from at least three **consented** 16k mono PCM16 audio samples per speaker, each 2–8 s, made with Kitty's microphone. Use `server/kitty_voice_enroll_v6.py`; stage the resulting `voice_profiles_v6.json` as a private candidate for S3 SD canonical storage; no raw WAV commit.
3. Start `server/kitty_voice_service_v6.py` on **127.0.0.1:8772**, with a strong independent `KITTY_VOICE_TOKEN`, `KITTY_VOICE_PROFILES_V6` path and restrictive service account. Do not bind this endpoint publicly.
4. Verify recognition on fresh recordings not used for enrollment, including changed voice, French/Japanese/English, guests, noisy rooms, speakerphone playback. Calibrate model threshold and margin empirically; fallback UNKNOWN rather than misattribution.
5. Run offline V6 tests: `python -m unittest discover -s server -p 'test_kitty_*v6.py' -v`. Run `python -m compileall -q server`. The GitHub CI workflow is not evidence of passing unless its run explicitly succeeded.

## Gate C — gateway compatibility (staging image only)
1. In a disposable copy of the exact pinned Open WebUI container image, run `python server/patch_openwebui_voice_v6.py --source-root /app --check`. If it refuses an anchor, **STOP**. Do not force replace.
2. Ensure `kitty_realtime_voice_v6.py`, `kitty_voice_claims_v6.py`, `kitty_voice_gateway_adapter_v6.py` and resampling dependencies are importable by the container. Apply guarded patch only in this isolated image and run actual Python compile/tests and a local WebSocket handshake.
3. Confirm `kitty_voice_v6` opt-in works, `item_id` association survives asynchronous recognition, stale responses are dropped, and S3 remains responsive if the Ubuntu voice service is unavailable. The existing fallback transcript path must persist UNKNOWN.
4. Confirm acceptable p50/p95 first-audio and recognition latencies, no queue growth under overlapping calls, no regression to emotions/stop/retry/delegated model tools.
5. Note: the patch currently relies on a **single exact upstream forwarding anchor**, which may not match the deployed Open WebUI version. Compatibility is unverified until Gate C.

## Gate D — SD persistence/sync (mandatory; currently NOT COMPLETE)
1. On the S3, test `queueAttributed` and sidecar writes with actual firmware, verifying no audio callback performs SD operations.
2. Implement and test the **S3-originated uploader** (not yet available) so a consistent SD-worker-produced snapshot is sent over authenticated TLS to Ubuntu; server-side resumable receiver alone is insufficient. Full-file snapshots are acceptable initially; incremental transfer is an optimization.
3. Enforce SHA-256, deletion/revocation propagation, retry after Wi-Fi loss, storage bounds, cleanup of old Ubuntu snapshots and no raw audio retention.
4. Implement consented enrollment's write-back to S3 SD and a revocation path. Current enrollment CLI writes to a local file only; canonical transfer is not automatic.
5. Verify `voice_profiles_v6.json`, `speaker_claims_v6.tsv`, and full conversation archive survive S3 reset and rebuild the Ubuntu indexes. Never replace or format the existing SD to install V6.
6. Speaker similarity and “Hey, this is Shana” produce probable/claimed identity for **personalization only**, never trusted human authentication; owner fact writes are deliberately gated. Do not deploy a build where normal owner's memory learning silently stops without a mitigation.

## Gate E — acceptance
- Same enrolled voice recognized in English, Japanese and French, including varied tone; another speaker's voice kept separate.
- Self-introduction still lets Kitty converse naturally when biometric matching is weak; a spoofed claim never gains owner privileges.
- Attributed conversation and tentative facts are on SD after reboot; legacy SD records still readable.
- Offline/slow Ubuntu: streaming speech, STT, TTS and C5 expressions work unchanged; memory falls back to SD local.
- No surprise S3 reset or dropped voice calls under 30 min extended test; check heap/PSRAM use and file count/SD free.
- Delete a speaker's consent/profile and verify snapshots and semantic indexes stop returning their deleted voice data.
- End-to-end semantic retrieval in live gateway is **separately gated**: current V6 semantic startup helper is not per-turn realtime semantic retrieval.

## Rollout and rollback
1. Build tagged **candidate** artifact on feature branch and have CI/test reports attached. Do not promote `main` prematurely.
2. Stage Ubuntu services, verify health locally, deploy gateway *staging container* and run fake-audio tests. Keep production container routing unchanged.
3. Back up S3 SD, flash staged S3 candidate, keep C5 firmware exactly as-is unless changed; perform initial connection and acceptance with SD backup in hand.
4. Only after all gates pass, switch production gateway to vetted image during a maintenance window. If recognition fails, disable opt-in `kitty_voice_v6` or revert gateway container. If firmware breaks recall/audio, reflash the previously validated combined S3 image and restore only from the verified SD backup if any data is corrupted.
5. Promote branch to `main` only after explicit owner acceptance of working EN/FR/JA voice recognition, recall and no latency regression.

## Open blockers, not to be ignored
- No S3 microSD snapshot uploader / profile write-back.
- No verified deployed Ubuntu voice recognition service or Open WebUI gateway compatibility.
- No completed end-to-end S3/Ubuntu integration/hardware compilation.
- Per-turn semantic retrieval is not live; semantic index exists on derived snapshot only.
- Owner profile write authorization remains separate from probabilistic speaker matching.

**Therefore this document prepares a safe upgrade path; it does not constitute a completed deployable upgrade.**
