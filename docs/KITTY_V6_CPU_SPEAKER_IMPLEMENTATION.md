# Kitty V6 — CPU speaker recognition rollout

Branch: `feature/kitty-semantic-v6-cpu`. This is a **backend implementation**, not a claim that live realtime identification or AI per-turn recall is already enabled.

## Implemented

- `server/kitty_speaker_cpu_v6.py`: explicitly opted-in local enrollment from **three or more** independent 16 kHz mono PCM16 WAV utterances per speaker, CPU SpeechBrain ECAPA embeddings, local private profile storage, conservative comparison and unknown fallback.
- `server/kitty_memory_service.py`: opt-in authenticated `POST /speaker/identify`, accepts bounded `audio_wav_b64`, returns `speaker_id`, `confidence` (`probable` or `unknown`) and accepted score. It neither records audio automatically nor authorizes an owner.
- `server/kitty_refresh_finalized_v6.py`: keeps **all** finalized snapshots and staging on automatic refresh. `KITTY_SEMANTIC_AUTO_REFRESH=1` is still required on the existing service for refresh queueing.

## Private host setup (manual, one-time)

Install compatible CPU `torch`, `torchaudio`, `speechbrain`, `numpy` in the **existing memory service's actual Python environment**, not in Open WebUI. Pin/test the dependencies for that environment first. Download the SpeechBrain `speechbrain/spkrec-ecapa-voxceleb` model separately into a private root-readable local directory while preparing deployment; the HTTP handler **must not** fetch a model dynamically. Set `KITTY_SPEAKER_MODEL_DIR` to that local model directory and `KITTY_VOICE_PROFILES_V6` to an access-restricted JSON profile file, currently `/home/ryushi/kitty-v6/private/voice_profiles_v6.json`. Never commit the model, embeddings, sample WAVs or credentials.

After explicitly obtaining informed consent from each enrolled person, locally enroll each `person:ID` with e.g.:

```bash
KITTY_SPEAKER_MODEL_DIR=/private/local/ecapa KITTY_VOICE_PROFILES_V6=/home/ryushi/kitty-v6/private/voice_profiles_v6.json \
 python3 server/kitty_speaker_cpu_v6.py --enroll person:example --wav /private/voice/a.wav --wav /private/voice/b.wav --wav /private/voice/c.wav
```

Start the service with `KITTY_SPEAKER_CPU_ENABLED=1` only after the model, dependencies, profile permissions and test enrollment are ready. Realtime gateway and audio upload remain disabled/unintegrated until a valid per-item sample source exists.

**Important:** existing `{"speakers":{}}` means zero enrolled users. Unknown voices must remain unknown. The original 49 memories are unverified and must remain inaccessible to new enrolled speakers until their source attribution is independently established.

## Integration contract — pending

The WebUI gateway must capture a bounded audio segment mapped to the exact upstream transcription `item_id`, dispatch to the identification endpoint in a separate executor and emit `kitty.speaker.result` with the same `item_id`, `speaker_id` and `confidence`. Never block upstream audio transport while the CPU model runs. No result after timeout should be treated as unknown. S3 currently only accepts matching pending item IDs. Confidence is `probable`, never `claimed` unless using a separately verified, explicit speaker claim protocol.

For AI recall, wait until the identity for the **same** item is established, retrieve only that person's verified and authorized context, and insert disposable context into the correct response sequence. Clear before the next utterance, barge-in, speaker change or reconnect. Do not modify session-global instructions with guest memories. The existing `kitty.memory.semantic.result` display side channel is not sufficient for AI-turn recall.

## Deployment precautions

Do not reflash S3/C5, replace the working audio WebSocket handler, or omit any of the four Docker Compose files specified in `docs/KITTY_V6_CHECKPOINT_2026-10-31.md`. Preserve local Ubuntu commit `9b82e97`. GitHub branch changes made in this phase do not automatically update running Ubuntu code. Rebase the **local** work onto remote after making a backup branch; do not use hard reset, force push or delete snapshots.

Snapshot auto refresh: the user service uses `KITTY_SEMANTIC_AUTO_REFRESH=1` to enable queueing after `/snapshot/finalize`. This must be checked in the private env. Semantic index rebuild uses an atomic active generation; no history pruning is performed in the updated code.
