# V6 changed-voice and spoken-introduction fallback — 2026-10-30

## Decision
Kitty should remain friendly if Shana sounds tired, ill, hoarse, farther from the mic, or speaks a different language. An introduction such as “Hey, this is Shana”, “Bonjour, c'est Shana”, or “私はシャナです” is a useful **claim**, not biometric proof.

## Implemented on experimental branch
- `server/kitty_voice_claims_v6.py`: explicit first-person Shana introductions in English, French and Japanese; rejects questions and incidental mentions. Conservative patterns, not a full language understanding model.
- `server/kitty_realtime_voice_v6.py`: reconciles a transcript self-claim with a probable voice result. A strong acoustic match takes precedence, and conflicting claims are flagged. An explicit introduction still yields `confidence=claimed` if the utterance is too short for voiceprint matching.
- `server/patch_openwebui_voice_v6.py`: passes the completed transcript to the reconciliation helper, keyed to provider item ID.
- `firmware/CuteDisplayBrain/BrainRealtimeDirect.h`: opt-in `kitty_voice_v6` during auth, and accepts `claimed` as source `explicit_introduction` separately from `voice_probable`.
- `firmware/CuteDisplayBrain/KittyMemory.h`: archives claimed identity source on microSD and can retain associated personal statements as tentative `speaker_claims_v6.tsv` records, without granting verified-owner permission. No update to protected owner facts from a voice claim.
- `server/test_kitty_voice_claims_v6.py`: multilingual claimed-identity, incidental mention, conflicting voice match and short-utterance test cases.

## Desired conversation
User: “Hey, this is Shana.”
Kitty: “Hi, Shana! Your voice sounds a little different today.” (*only mention difference if really warranted and avoid medical guesses*)

Kitty may tentatively personalize a conversation based on the explicit claim, but should not silently treat it as secure authentication. If a different confidently recognized speaker claims to be Shana, retain the acoustic attribution and resolve the contradiction naturally. If neither the claim nor the voice match is reliable, answer without falsely assigning the owner.

## Important outstanding tasks
- No deployed gateway/ESP32 firmware; actual identification accuracy and live end-to-end timing not tested.
- Add natural conversational response context, not merely archival attribution. The recognizer currently sends metadata to the S3 archive; a response-time identity context hook is still needed to influence Kitty's spoken greeting.
- Implement a reliable, consent-based voice enrollment UX and SD-canonical profile persistence/sync, secure incremental SD uploader, and pinned-version gateway patch verification.
- Calibrate speaker matching with the actual INMP441 microphone across EN/FR/JA, illness/hoarseness and distance; enroll multiple speaking conditions with permission.
- Voice alone or “I am Shana” must not unlock high-trust owner-specific actions or protected fact overwrites.

Stable main remains unchanged. Do not flash V6 until full compile, tests and hardware validation succeed.
