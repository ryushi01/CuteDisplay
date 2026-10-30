# Kitty V6 — Voice-first speaker recognition (Ubuntu + Mac), 2026-10-30

**Decision:** The phone app is NOT the source of speaker identity. The ESP32-S3 records speech; a separate Ubuntu CPU service recognizes enrolled voices; Open WebUI and Ollama/STT/TTS remain on the existing Ubuntu/Mac path.

## Committed code
- `server/kitty_voice_id_v6.py`: mono 16-kHz WAV validation, CPU SpeechBrain ECAPA speaker embeddings, consent-based multi-sample enrollment helper, open-set matching returning UNKNOWN on weak or ambiguous evidence.
- `server/kitty_voice_service_v6.py`: standalone localhost-only opt-in service on port 8772, receiving bounded PCM16 WAV with separate bearer token; returning speaker_id, confidence (probable/ambiguous/unknown) and raw similarity score. It does not persist microphone audio, run on S3, or directly modify memories.
- `server/test_kitty_voice_id_v6.py`: offline matching and unknown-safety regression tests, no model download needed.
- Existing experimental iPhone Secure Enclave files are now *out of scope* for speaker personalization. Do not deploy phone owner grants as the voice identity mechanism.

## Real runtime design (not yet connected)
S3 mic -> existing realtime transport -> Ubuntu gateway receives same 16k PCM frames/utterance capture -> speech transcription continues on Mac unchanged; **copy completed utterance** into bounded background voice-ID queue (not I2S thread) -> Ubuntu `kitty_voice_service_v6` computes voice embedding -> map to locally enrolled speaker profile -> attach source metadata (recognized/unknown, confidence, reference utterance ID) to the appropriate user turn -> S3 SD worker persists speaker-aware record -> semantic Ubuntu index handles speaker-specific recall.

Do NOT infer a speaker from STT words, name claims or ChatGPT TTS alone. For overlapping voices, use diarization first: pyannote Community-1 can run CPU but requires separate testing and possibly Hugging Face model access. A single-utterance matcher does not handle overlap or multiple people talking simultaneously.

## Voice enrollment
Explicit consent required. Collect at least three clean 2–8 second utterances per speaker through the same microphone, at different distances and with different content; label with the person's chosen name. Store only normalized embeddings in a *private*, revocable profile JSON or microSD source-of-truth as a later implementation. Do not store raw voice samples unnecessarily. The current enrollment helper is a computation primitive; there is no completed interactive enrollment workflow or S3 voice-profile sync.

## Limits
- The default similarity threshold 0.72 and margin 0.10 are conservative **initial placeholders, not calibrated identification accuracy**. Validate FAR/FRR using same-room speakers and speaker playback from a remote AI, noise, distance, French/English/Japanese, TTS overlap, and different dates.
- Matching a voice is not secure human authentication and must never automatically unlock owner-only sensitive memory modification.
- Until speaker-aware turn metadata and the S3 archive/fact writer are wired, current V6 firmware still gates all protected owner writes behind an unconnected verification flag. **DO NOT FLASH** this feature branch.
- The model uses CPU+RAM and *also* disk for cached weights and local profiles. Run in a separate bounded process with CPU/memory limits; protect stored biometric templates.
- Do not run SpeechBrain and pyannote on the S3; add voice recognition on Ubuntu without moving your existing Ollama/STT/TTS Mac services.
- The dedicated WAV endpoint is for trusted local gateway usage only. Use TLS/reverse proxy, rate limits, and a separate token before network exposure; currently has no production streaming or hard capacity bound.
- Never inject recognition scores or guest voiceprints as verified owner facts.

## Staged next steps
1. Test actual S3 24 kHz audio sample framing, resample clean speech to mono 16k (voice model input), and add a nonblocking utterance queue in the Ubuntu realtime gateway.
2. Deploy only in a private/staging service after `free -h`, `nproc`, `df -h /` confirm Ubuntu headroom. Warm model once, run p50/p95 recognition latency under actual load.
3. Implement consent-based voice enrollment and profile storage, ideally microSD canonical with controlled derived cache on Ubuntu; support deletion and re-enrollment.
4. Pass matched identity per turn to S3 archive, separate speaker vs subject, and avoid rewriting owner facts unless appropriately confirmed; keep existing good name recall.
5. Test voice changes in the same conversation, ChatGPT/guest distinct from Shana, reboot persistence, cross-language questions and fallback to UNKNOWN with zero audio glitches.
6. After hardware acceptance, remove unused phone owner-verification experiment from branch and promote proven components to stable main.

## Local experimental install (not yet deployed)
```bash
python3 -m venv ~/kitty-voice-v6-venv
~/kitty-voice-v6-venv/bin/pip install numpy torch torchaudio speechbrain
# Cache/model download on first actual speaker embedding; model licensing/reproducibility must be checked.
# Copy a consented test profile file to a private path; no production sample files here.
```
