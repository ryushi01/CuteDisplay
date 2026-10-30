# Kitty V6 voice + SD integration progress — 2026-10-30

## Architecture decision
S3 microSD remains the **canonical source of personal memories, attributed conversation archive and consented voice template exports**. Ubuntu MS-01 runs CPU speaker recognition and semantic search on disposable private snapshots. Mac retains Qwen3.5 9B, Whisper STT and Qwen3-TTS.

## Newly connected in source
- S3 `KittyMemory::queueAttributed(question, answer, speaker, source)` carries a bounded, sanitized probable speaker ID through the existing background SD queue and writes `turn_sources.tsv` keyed to the archived byte offset. Old `queue()` remains supported; unknown is default. This code does not affect the realtime microphone task, and a voice match **never** sets `ownerVerified`.
- `server/kitty_voice_profiles_sd_v6.py` specifies a consent-based `/kitty/voice_profiles_v6.json` record (three or more enrollment vectors) that can travel with verified SD snapshots. Voice templates are sensitive biometric information; they require privacy controls, revocation and explicit consent. JSON profile data on SD is not encrypted by the current implementation.
- Ubuntu snapshot allowlist now supports `voice_profiles_v6.json`, and the local voice-ID service loads the same versioned profile format.
- `server/kitty_voice_gateway_adapter_v6.py` converts a bounded **completed** 24 kHz PCM16 microphone utterance to 16 kHz and requests isolated Ubuntu speaker recognition asynchronously, returning unknown on failure or timeout. Model computation stays on Ubuntu, not ESP32.
- Offline regression tests added for waveform conversion, fallback, voice profile schema, and matching outcome. Code and CI committed; no real hardware tests confirmed.

## Honest remaining connection blockers
- The **existing live Open WebUI gateway does not yet capture completed microphone utterance audio for this adapter**; the adapter is not called from the gateway, nor does it emit an identity event per transcript.
- **The S3 realtime handler still calls the legacy `KittyMemory::queue()`**, so speaker IDs do not yet reach the SD queue from actual voice conversations. It must receive a bound per-turn speaker result, match the result to the exact transcript ID, and call `queueAttributed()` on the SD worker path, handling results that arrive after the transcript.
- The existing voice service has no user-facing consent/enrollment workflow or automatic upload of voice embeddings to microSD. The schema and calculation helpers exist, but enrollment persistence and revocation are not wired.
- The S3 uploader for sending complete, consistent microSD memory snapshots to Ubuntu remains pending. The server receives checked snapshots but the S3 does not yet originate them.
- Until there is a separate verified identity authorization mechanism, a voice match is **probable**, not trusted proof for modifying protected owner profile facts. On this feature branch the S3's `ownerVerified` remains false, so do not flash it or merge to main yet.

## Safety/performance requirements
- No extra network or SD work on the realtime I2S task.
- Never allow an enrollment or semantic lookup to stall voice playback.
- Cache expensive CPU inference; timeout and default to unknown/local memory when overloaded.
- Keep full raw audio only in volatile RAM for the duration of recognition. Don't log audio or biometric vectors.
- Production storage on Ubuntu is only a protected derived export; purge stale snapshots and enforce speaker-deletion propagation.
- Run actual CI, firmware compilation, on-device reboot/SD durability tests, and real English/French/Japanese multi-speaker acceptance before deployment.

## Next engineering actions
1. Instrument the pinned gateway to capture **only completed** microphone utterances and call the asynchronous adapter; persist association with provider transcript `item_id`.
2. Add server-to-S3 speaker result delivery with turn ID and update the queued memory row / sidecar without risking misattribution from late replies.
3. Implement SD-worker-owned voice-profile enrollment/import/export, deletion and consistent snapshot upload over authenticated TLS.
4. Add stress tests for guests, spoofed playback, recognition ambiguity, packet loss and audio latency; then stage deployment.
