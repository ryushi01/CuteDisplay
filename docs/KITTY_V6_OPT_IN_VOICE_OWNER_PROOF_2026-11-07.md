# Kitty V6 — opt-in voice owner proof (source only, 2026-11-07)

## Decision

The owner asked for automatic recognition from their voice instead of iPhone
approval on every call. The \`0.960\` x-vector score remains a **conversational
hint** and a spoken "I'm Shana" remains a **self-claim**; neither alone unlocks
the S3 private archive.

An owner may **explicitly opt in** to a separate voice-authentication policy.
On a later call a trusted, isolated Ubuntu issuer examines three distinct,
consecutive, fresh S3 microphone turns associated with actual provider item
IDs and final transcripts. It accepts a *pinned* enrolled-owner model only if
each confidence score and enrolled-other-speaker margin passes explicit
operator-calibrated policy thresholds. The name may corroborate conversational
identity but does not reduce the voice verification requirement.

On the third passing turn and on subsequent passing turns, the issuer produces:
- a 45-second call-bound \`person:owner\` grant;
- a 10-second exact provider-item/transcript **and audio SHA-256** attestation;
- no general session-wide permission to query arbitrary private memories.

The private-recall path additionally checks the transcript, item, audio hash,
signed grant, and signed speaker turn before returning read-only **S3-derived**
owner records. An unrelated or unknown speaker, audio overlap, playback active,
missing microphone attestation, stale/duplicate item, duplicate audio,
voice-score mismatch, invalid model, gap, disconnect, or opt-in revocation
clears the pending voice evidence. A previous grant without a new, exactly
signed turn cannot authorize a later guest question. Normal shareable recall
is unaffected.

## Where code lives

- \`server/kitty_owner_voice_auth_issuer_v6.py\`: opt-in issuer class.
- \`server/kitty_attested_live_call_v6.py\`: optional exact-audio hash verification
  and propagation to owner history.
- \`server/kitty_semantic_async_client_v6.py\`: forwards the hash only when
  present (legacy signed turns stay compatible).
- \`server/kitty_semantic_authorization_v6.py\`: rejects mismatched/missing
  hashes for audio-bound tickets.
- Two offline tests cover default off/consent, rejection boundaries, signed
  grant and audio-bound private recall.

The issuer has NO public HTTP handler, startup side effect, live gateway
hook, persistent local owner database, firmware change, iPhone changes, or
profile mutation. Existing auth paths remain unchanged unless explicitly
given an audio-bound ticket and hash.

## Opt-in and deployment requirements

1. Explicitly enroll and consent the owner's immutable, pinned model profile
   (no enrollment by merely speaking a name). An issuer-owned protected profile
   loader must require \`voice_owner_auth_consent=true\`,
   \`owner_enrollment_id=person:shana\`, \`memory_authorization=false\`,
   >=3 protected anchor embeddings, a pinned \`model_id\`, calibrated
   \`voice_owner_auth_min_score >= 0.970\` and
   \`voice_owner_auth_min_margin >= 0.10\`. These are **hard minima, not
   calibrated recommendations**. The usual 0.960 threshold is never enough.
2. Deploy an isolated trusted issuer with a *private* S3 microphone capture
   lookup and local CPU scorer; it must read an authenticated session's
   provider item, final transcript, WAV, capture timestamp and provenance
   from internal state. Neither JSON sent by the device nor the guest's
   spoken name may supply an approval or score. Run CPU inference off the
   audio-forwarding loop and keep the inference queue bounded.
3. Ensure isolated grant and turn signing keys are distinct and protected;
   the S3 must never contain signing keys. Configure memory service to
   independently verify both signatures. The caller must supply the
   exact microphone audio hash when submitting an audio-bound ticket.
4. Before enabling in the live gateway, run real owner / guest / playback /
   voice-clone / noisy-room / interruption trials with a pre-agreed
   false-accept ceiling. Consider a fresh spoken random challenge or
   stronger anti-spoofing before granting access to highly sensitive facts.
   Then wire authenticated issuer result to the existing \`AttestedLiveCall\`
   lifecycle with strict cancellation/expiry and test the SD receipt handoff
   end-to-end before one consolidated S3 firmware flash.

**Threat-model caveat:** voice biometrics alone are not strong proof of live
human presence. Three distinct audio files and a timestamp detect some simple
duplicates, not playback through the microphone or modern voice cloning.
The owner has deliberately requested an opt-in *voice-based* risk policy, not
a second independent physical factor; distinct signing keys do not make it
multi-factor authentication. Until enrollment, calibration, anti-spoof testing,
and trusted gateway wiring are done, private owner memory must remain disabled.

## Validation status

Offline unit tests cover identity, revoked opt-in, threshold/margin, repeated
audio, echo, forged/mismatched metadata, exact session/item/transcript/audio
binding, time limits and fallback. They do not demonstrate real-world FAR
or speaker liveness. Source changes are staged in GitHub for CI; the live
Ubuntu gateway, C5/S3 firmware, iPhone app and microSD were NOT modified.
