# Realtime Kitty voice and expression overhaul — 2026-10-29

## Reason
User confirmed earlier optimistic reports were not reproducible: overlapping user speech was missed, and multiple expressions were inconsistent. Treat both features as **unverified** pending physical testing.

## What changed
- S3 microphone previously sent zeros throughout Kitty audio unless a high threshold barge detector fired. That was why a natural question spoken over Kitty could be lost. Now the audio task continuously captures microphone samples during output; a reference-energy gate suppresses likely speaker-only leakage. This is still **not true acoustic echo cancellation**, so crosstalk remains possible.
- Overlap detector may still mark a near-end voice event for debug, but should **not automatically cancel Kitty**; microphone and provider VAD are responsible for creating/transcribing a user turn. Once a transcript completes during Kitty speech, S3 holds the latest item until the ongoing realtime response and speaker buffer are done, then invokes existing `bridge.respond`.
- Server extension adds expression tool to the post-animation continuation response when Kitty capability is enabled, rather than removing it after first expression. This makes sequential tool-initiated emotions more feasible, not guaranteed word-synchronized changes. Server instructions no longer expressly prefer a single emotion.
- Existing realtime audio, personality and C5 v25 face layout remain unchanged. Stable rollback remains `stable/2026-10-29-realtime-voice-hardware-validated` at `78d4abd9`.

## Installation order
1. On Ubuntu `ai-server`, fetch the current feature branch and use the version-guarded `server/upgrade_kitty_expressions.sh` deployment. Confirm Docker deployment checks. Do not replace Open WebUI manually if source guard fails; do not delete rollback images or persistent volumes.
2. Use the **successful** GitHub Actions combined firmware artifact built from this feature branch. On Mac Arduino IDE upload extracted `CuteDisplayBrain/CuteDisplayBrain.ino` to S3 using existing board settings, Erase All Flash OFF. No C5 version bump needed.
3. During an ordinary call, speak clearly while Kitty talks, let Kitty finish, and check for `[CALL] DEFERRED_VOICE: captured during reply` and `[CALL] DEFERRED_VOICE: processing saved utterance`. Lack of both indicates upstream transcription or overlapping speech suppression; speaker echo causing false transcription indicates a need for real AEC.
4. Ask Kitty for contrasting emotions sequentially. Check for multiple `[CALL FACE] AI set expression=...` logs; no assumption of synchronization to spoken words.
5. Preserve Serial Monitor logs without API keys or sensitive transcripts.

## Limitations
- This is a code change undergoing CI, not confirmed hardware acceptance.
- Because the INMP441 hears the speaker acoustically and hardware lacks calibrated AEC, the new gate is a compromise: false detections and missed quiet speech are possible.
- Open WebUI provider `local` may still not permit actual mid-stream audio/tool interleaving. Sequential expression tool continuations do not prove intra-sentence timing.
- Only the latest completed overlapping utterance is retained, not an unbounded conversation queue.
