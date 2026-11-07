# Kitty V6 automatic owner voice authorization — opt-in source stage

## Updated user requirement

The owner wants Kitty to recognize their voice automatically without repeating
the existing iPhone setup or pasting a public key. A spoken self-introduction
should also help her recognize the owner. This changes the previous
app-presence-only proposal: a separately consented voice-based owner mode
is now a supported source-level authorization option.

**Important trade-off:** biometric similarity alone is vulnerable to replay,
recorded voice samples and impersonation. A spoken name is public knowledge.
This mode provides convenient automatic recognition, not the security
equivalent of cryptographic owner presence. Plain "I'm Shana" with an unknown
or nonmatching voice remains a conversational self-claim, never private access.

## Implemented on GitHub, not installed

- `server/kitty_owner_voice_auto_verify_v6.py` is an optional per-call
  trusted worker policy. It accepts only trusted provider-correlated, complete
  16 kHz microphone WAV, not a client-supplied speaker score or a BLE label.
- Standard automatic mode requires **two distinct locally computed owner
  voice matches** at score >= 0.970 within 45 seconds. Duplicate item
  IDs or identical audio fingerprints cannot count twice. An unknown/guest
  turn clears consecutive verification evidence.
- Explicitly selectable *named convenience* mode permits a real owner voice
  match at score >= 0.965 **combined with** an owner's self-introduction
  in English, French or Japanese on the same captured turn. Neither a name
  without an actual voice match nor the existing 0.960 conversational hint
  is sufficient.
- If configured with independently issued secrets and a protected consented
  owner profile, the trusted worker issues a 10-second exact-item signed
  owner attestation (including microphone-audio hash) and a 60-second
  conversation-specific owner grant. Both are cleared on call end; no audio
  samples, memory facts or recordings are stored by this policy.
- The memory-service source adds an **independent voice grant verifier** in
  addition to the existing optional iPhone enrolled-key proof. Both routes
  still require the separate signed exact-speaking-turn attestation. The
  audio digest must match the signed attestation before private SD context
  can be retrieved. Default is OFF.
- `KITTY_VOICE_OWNER_PRIVATE_OPT_IN=1` is required on the memory service,
  with a distinct `KITTY_VOICE_OWNER_GRANT_SECRET_HEX` and the path
  `KITTY_VOICE_OWNER_CONSENTED_PROFILE`. Profile mode must explicitly be
  `owner_voice_auto_auth_v6`, with the owner's consent recorded as
  `owner-accepts-voice-auth-spoofing-risk-v1`. A prior shadow-only profile
  is rejected. A separate `KITTY_TRUSTED_TURN_ISSUER_SECRET_HEX` is
  required. Do not print or paste these secrets into chat.
- No insecure name-only private authorization is enabled by default.

## What is NOT ready

This is **source-only**, not a working production auto-owner recognizer.
The gateway still needs to connect provider-correlated microphone audio
to a separate CPU worker that computes the score from the enrolled local
owner voice model and then hands only the resulting signed exact-turn
evidence to the private-memory helper. The private profile must be opted
in locally and checked against other enrolled voices to calibrate actual
false-positive rates; the 0.965/0.970 preliminary thresholds are NOT
validated security thresholds. Recordings/replay remain a threat unless
the deployed transport includes a suitable challenge/liveness approach.

Existing indexed records contain no verified owner archives. A positive
voice decision on a new call must not retroactively relabel old
voice_probable, explicit_introduction or unknown SD turns.

## Preservation and test policy

No iPhone pairing, BLE behavior, C5 firmware, S3 firmware, SD files, Mac
inference/TTS or live Open WebUI helper changes in this stage. The working
repaired approved-shared cross-call memory (Mochi Planet) remains active.

Offline tests cover:
- No opt-in, missing/wrong protected owner profile or reused secret.
- Valid two-turn voice proof and 10-second ticket/60-second grant expiry.
- Voice-plus-name convenience, rejecting name-only/0.960 probable guesses.
- Wrong/guest speakers, recycled audio, reused item, missing authenticated
  upstream capture, and speaker transitions.
- Owner-only memory-service HTTP reads with BOTH separate proofs, signed
  microphone hash, valid device bearer, and refusal of unsigned/wrong audio
  or arbitrary private queries.

The next safe implementation is the authenticated gateway CPU adapter,
provisioning/consent guard, and one owner-versus-guest hardware test,
without touching the current audio event path or live gateway until
the regression tests and rollback plan are ready.
