# Kitty V6 — resume after November 2 frozen checkpoint (2026-11-04)

The canonical frozen baseline is [KITTY_V6_CHECKPOINT_2026-11-02.md](KITTY_V6_CHECKPOINT_2026-11-02.md). The `main` baseline at the start of this pass was `c821b16c`. Latest post-freeze work is **read-only deployment inspection only**. It does not modify firmware behavior, authorize any private memory, change Docker, modify live Ubuntu services, or require a C5/S3 flash.

## What remains physically verified

- ESP32-S3 automatic idle SSE summary HTTP 200, `accepted=1 summary_stage=6`; microSD acknowledgement `2578 → 2878`.
- One call: zero recorded mic/speaker sample drops, 2,596-byte loop-stack headroom, but ~52 KB minimum internal heap, cumulative speaker underruns, three UART ACK timeouts and an unexpected WebSocket disconnect. Do not infer causes from counters alone.
- Explicitly approved shared-memory cross-call recall ("Mochi Planet") worked in earlier hardware tests. **Private owner recall and long-call rolling continuity are not deployed**.
- C5 v38, Mac model/TTS, S3 SD archive, UART/24 kHz realtime audio and the live Open WebUI VM remain untouched.

## Read-only live Ubuntu preflight added

Run from the existing clean Ubuntu checkout (no branch switch, worktree edits, service reload or flash):

```bash
cd ~/kitty-v6/private/kitty-sync-deployment/live-sync-build
git fetch origin main
git show origin/main:server/kitty_live_readiness_v6.py | python3 -
```

The script queries only a user-service state/PID, the local `/health` endpoint, and the on-disk live memory/gateway source for **fixed marker presence**. It prints predefined status labels, never the source text, environment, token values, transcript, keys, memory contents, private file paths or process argv. It does not mutate them.

**Interpretation:** source-marker `present` does not prove that the running Python process loaded that revision; `absent` does not rule out a differently structured patch. `unknown` means runtime introspection was not possible. The preflight is strictly diagnostic. No source-only result establishes trusted human speaker authorization.

Safe outputs to share: `KITTY_V6_READ_ONLY_PREFLIGHT` statuses. Never paste secrets, service environment dumps or raw memory files.

## Remaining work in the original six-priority order

1. Authenticate the owner with the enrolled iPhone key **and** bind private memory access to a server-trusted, independently verified spoken turn. Phone presence or a probable voice match alone is insufficient. Never loosen `ownerVerified=0` for unknown turns to make tests pass.
2. Stage the bounded extractive long-call continuity buffer with independently verified session and item IDs, maintaining isolation and no additional Mac GPU jobs. Do not inject unverified private history into session-global prompts.
3. Measure S3 internal heap fragmentation after any future consolidated S3-only image.
4. Verify 10 KiB loop-task stack headroom during longer calls.
5. Compare S3 UART ACK, ignored ACK, retransmit/timeouts, dropped audio, underruns and unexpected disconnect timestamps. Keep C5 firmware/audio timings unchanged pending evidence.
6. Audit the **actual deployed** private Open WebUI gateway and legacy nondelegated BrainAI memory path; all generated Ubuntu diffs must be staged and tested before deployment.

The new preflight is source/test only and is not a production deployment. The first action after reading its results is a **read-only comparison of live Ubuntu runtime state with checked-in modules**, not a speculative flash or gateway patch.

## Actual Ubuntu read-only preflight observation — November 4

Operator ran the original `kitty_live_readiness_v6.py` via `git show FETCH_HEAD:...` in the existing private Ubuntu worktree (without switching its branch). The original `origin/main` reference was missing because the remote fetch went to `FETCH_HEAD`; `FETCH_HEAD` resolved correctly.

Observed on actual Ubuntu VM: `memory_service_state=active`, `memory_http_health=ok`, `memory_owner_grant_gate=absent`, `memory_owner_challenge=present`, `memory_private_semantic_endpoint=present`, `memory_shared_context_endpoint=present`; **all six gateway markers returned unknown**. The service file currently resolved through its running PID is thus missing the exact owner-grant guard marker present on GitHub `main`; this does not by itself prove that a service module wasn't monkey-patched at runtime. **Do not enable private automatic recall** until the live service's authorization is confirmed. An API bearer token alone is not human identity.

The initial gateway scan could not distinguish a missing Docker permission/container/source file from a Python command/JSON probe failure. A revised source-only preflight tests Docker inspect and Python/Python3 with a fixed diagnostic status, and still prints no secrets, environment variables, raw Python source or personal memory. The offline preflight unit tests were expanded to cover no-Docker and missing-source cases.

Next operator action (still read-only; command does NOT switch branches, update services, flash, or modify source files):

```bash
cd ~/kitty-v6/private/kitty-sync-deployment/live-sync-build
git fetch origin main
git show FETCH_HEAD:server/kitty_live_readiness_v6.py | python3 -
```

Review `gateway_inspection` alongside gateway marker statuses. If Docker access fails, diagnose local container privileges separately before touching live audio. If source was readable, inspect a source-only diff privately to stage the missing owner gate. Do **not** replace the existing memory service wholesale, restart Open WebUI, change the C5 v38 firmware or deploy automatic owner recall based solely on these marker scans.

## Actual Docker and gateway confirmation — November 4

The operator's `docker info` failed as the ordinary user and noninteractive `sudo -n` also failed (interactive password needed), causing prior `gateway_inspection=docker_inaccessible_or_container_missing`. Interactive `sudo docker ps` confirmed `open-webui` **running and healthy for two days**; `open-terminal` also runs. Read-only `sudo docker exec -i open-webui python3` read the actual `/app/backend/open_webui/routers/audio/realtime.py` and found:
- `kitty.memory.refresh`: present
- `KITTY_INITIAL_PUBLIC_PROFILE_V6`: present
- `KittySpeakerObserver`: present
- `kitty.speaker.result`: present
- `kitty.memory.semantic`: present
- `KITTY_CANDIDATE_CONTEXT_ITEM_V6`: **absent**

A marker's absence is **not proof** that an alternate implementation does not exist. Working realtime AI, shared memory and C5 v38 are to remain untouched; there is no demonstrated gateway malfunction.

Live memory service status remains `active` and HTTP health `ok`, but its source lacks the new `authorized_semantic_speaker(data,OWNER_PROOF)` marker. This creates a **candidate private-semantic authorization gap**, pending exact live-handler audit. The current GitHub `server/kitty_memory_service.py` enforces signed owner grants before private `/semantic` and `/semantic/context` lookup. Do not replace the entire private service or restart it without a scoped compatibility plan and rollback, and do not treat device API bearer or voice candidate as human authentication.

**Prepared read-only handler-only comparison:** `server/kitty_owner_guard_plan_v6.py` examines the live PID's Python service source, uses GitHub `FETCH_HEAD` as the target version, verifies the legacy split semantic endpoint layout and a generated replacement in memory, checks sibling helper file presence and prints only fixed statuses. It **does not write a candidate or change any service**. CI adds `server/test_kitty_owner_guard_plan_v6.py`, which validates fail-closed compatibility, and keeps the separate S3/C5 compile gate intact.

One next Ubuntu command:

```bash
cd ~/kitty-v6/private/kitty-sync-deployment/live-sync-build
git fetch origin main
git show FETCH_HEAD:server/kitty_owner_guard_plan_v6.py | python3 -
```

Read `candidate_compiles`, `live_semantic_handlers`, and `dependency_*`; no patch should be applied or service restarted based on this command alone. If the live handlers differ, adjust the proposed patch to the actual private source in a staged, test-only manner with no transcript or token disclosure. Next steps after confirmation: prepare a single targeted backup + patch + offline test + explicit operator-controlled restart/rollback; then verify health and private 403 fail-closed behavior. There is no owner identity issuer wired into actual realtime spoken turns yet.

## Private semantic owner guard deployed — November 4 (operator-confirmed)

**This supersedes all pre-deployment instructions in the earlier November 4 sections above.** The operator fetched GitHub `main` into `FETCH_HEAD` from the existing private Ubuntu worktree and ran:

```bash
git show FETCH_HEAD:server/kitty_owner_guard_deploy_v6.py | python3 - --apply
```

The actual live deployment output was:

```text
KITTY_V6_PRIVATE_OWNER_GUARD_DEPLOY
backup=created
offline_private_guard=passed
deployment=completed
memory_health=ok
private_semantic_403=verified
shared_audio_gateway=unchanged
```

**Confirmed by the installer and operator:** original live memory service backed up; exact legacy split `/semantic` and `/semantic/context` handlers replaced by GitHub's combined, signed owner-grant handler; two missing helper modules copied; offline owner grant/guest deny tests passed; user `kitty-memory-v6.service` restarted and its localhost `/health` returned OK; both private semantic endpoints rejected an unverified request with HTTP 403 using the service bearer; rollback state retained. The installer intentionally did **not** patch Docker/Open WebUI, S3/C5 firmware, SD archive, audio or Mac AI/TTS. This last point describes code scope, not a separate end-to-end audio test.

**No further service deployment or checks are needed for this identified guard gap.** Do **not** re-run `--apply` on the same installation; it is a one-time transaction. Backups and a strict `--rollback` mode remain available if later needed, but no rollback is indicated by the successful output. Do not display or copy private backup contents or service environment into GitHub.

**Unfinished:** the deployed gateway does not yet have independently verified owner-per-spoken-turn binding. An enrolled phone key and signed, session-bound grant cannot alone establish who uttered a microphone turn; X-vector candidates, self-introduction and device bearer remain non-authorizing. Private automatic cross-call recall and owner fact writing stay gated; approved shared-memory recall and normal automatic SD summarization are separate established features. No new S3 flash or C5 v38 change. Next engineering priority is a per-item trust issuer integrated with the actual realtime flow and user-presence/enrollment policy, tested on a staging gateway before any live enablement; one consolidated deployment and one meaningful conversation test rather than repeated status loops.

## Signed per-turn continuity bridge — November 4 (source-only, NOT enabled)

The first November 4 Ubuntu deployment is complete and remains the **only** service update in this continuation: the operator explicitly confirmed `backup=created`, `offline_private_guard=passed`, `deployment=completed`, `memory_health=ok`, `private_semantic_403=verified`, `shared_audio_gateway=unchanged`. Do **not** reapply that patch.

**New source-only work on GitHub `main` (no Ubuntu deployment, iPhone changes, flash or macOS AI/TTS changes):**

- `server/kitty_attested_live_call_v6.py`: optional `AttestedLiveCall` tracks a gateway-created random call ID and upstream-observed `speech_stopped` / completed transcription item IDs. It stores only bounded in-RAM transcripts/rolling excerpts, caps total item IDs per call at 2,048 and rejects any prior item ID replay. A per-turn attestation must be HMAC signed by an **independent trusted speaker-verification issuer**, bound to exact call ID, item ID and SHA-256 of the completed transcript, with at most 15 seconds validity. Guest and owner roles are isolated. The local speaker pseudonym for the verified owner is never stored in the guest historical index. An owner also needs the separate enrolled-key session grant; neither a session grant alone, phone BLE pairing, a spoken name nor a `voice_probable` score can authorize a turn. Unknown speaker, invalid/late proof, cancellation or disconnect revoke private continuity. This is a *protocol consumer* and offline fixture signing contract, not an actual human-authentication implementation.
- `server/kitty_turn_context_v6.py` now includes an opt-in `attested_voice_turn_context()` for already verified turn objects. It returns bounded same-call decision excerpts without additional inference/HTTP. Optionally, and only for a verified owner with a still-valid session grant, it can fetch owner SD-derived history via the existing loopback-only async client. After every `await`, it rechecks whether the original item is still current; barge-in/new speaker or disconnect discards the result.
- `server/kitty_live_rolling_context_v6.py` now retains item replay state across long calls (not only the previous 48 items) and clears notes on unauthorized speaker reads. Its extractive buffer remains 1,000 bytes by default with 10 pinned explicit decisions and four recent turns; it is **not** model-generated comprehensive rolling summarization.
- The opt-in bridge and adapter have regression tests in `server/test_kitty_attested_live_call_v6.py`, `server/test_kitty_attested_turn_context_v6.py` and `server/test_kitty_live_rolling_context_v6.py`. Firmware CI runs them before S3/C5 compile. Tests use a **synthetic independent signer**; passing tests does not demonstrate real speaker verification.

**Critically not implemented:** A trustworthy external issuer that independently confirms which human produced a specific observed microphone turn; gateway registration, per-item attestation exchange and safe provider-context injection; app-based enrollment/call control wiring; durable owner-verified SD writes. Those must be built and security-reviewed before any private automatic recall is enabled. The live gateway's public memory refresh, candidate speaker observer, realtime audio, C5 v38 and Mac model/TTS are intentionally unchanged. No live turn should be labeled verified just because a model guesses a voice or the owner signs in somewhere.

**Next integration step:** inspect the exact private running `realtime.py` turn-event branches using a read-only source-shape report (no raw source, secrets or transcripts) and identify the independent speaker-verifier trust interface. Stage a version-checked, disabled-by-default patch against a copy before enabling any context injection; CI alone cannot validate the private running gateway. Prefer one staged deployment and one realistic multiperson conversation test when the independent issuer actually exists. No further memory-service command or S3 flash is currently needed.

## Live gateway integration shape preflight — November 4

A final status-only, read-only gateway probe was added: `server/kitty_gateway_turn_shape_v6.py` and `server/test_kitty_gateway_turn_shape_v6.py`. It inspects the **actual** private Open WebUI `realtime.py` inside the existing container for nested async turn event loops, provider/client forwarding counts, VAD + completed transcription event markers and any current attestation bridge reference. It never prints source, transcripts, credentials, environment or client message payloads, and performs no import/patch/restart. The CI test runs before any firmware compile.

The Ubuntu operator uses one grouped command, without changing the checkout branch:

```bash
cd ~/kitty-v6/private/kitty-sync-deployment/live-sync-build
git fetch origin main
git show FETCH_HEAD:server/kitty_gateway_turn_shape_v6.py | sudo docker exec -i open-webui python3 -
```

The resulting `KITTY_V6_GATEWAY_TURN_SHAPE_READ_ONLY` status output is safe to share for version-matched staging design. **Do not assume** that a source marker means a working runtime issuer, or deploy the attested bridge merely because the source parses. The external independently trusted identity-verifier/signer is still not installed, and owner-only private recall remains off. Do not reflash either S3 or C5 for this Ubuntu-side analysis.

## Gateway source-shape results and no-VAD adapter (2026-11-04)

**New operator-confirmed facts from the actual Ubuntu `open-webui` container**, obtained using the approved read-only `kitty_gateway_turn_shape_v6.py` inspection (no source, secrets or transcripts exposed):

```text
source=readable
python_syntax=valid
function_client_events=once
function_upstream_events=absent
function_kitty_speaker_sink=once
client_to_provider_event_forward=absent
provider_to_client_event_forward=multiple
public_memory_refresh=present
public_profile=present
speaker_observer=present
speaker_result=present
semantic_request=present
upstream_speech_started=absent
upstream_speech_stopped=absent
upstream_transcription_complete=present
owner_grant_reference=absent
trusted_turn_issuer=absent
legacy_voice_gate=present
trust_issuer_operational=not_verified
safe_to_enable_owner_history=no
```

Markers reflect literal source strings and AST declarations, **not runtime proof** of which provider events are received. In particular, `provider_to_client_event_forward=multiple` is a whole-file string count, and `upstream_speech_started=absent` only means there is no explicit literal event handler in this revision. It does not establish that the provider never sends VAD events. **Do not apply** any older patch expecting a unique whole-file `await ws.send_json(event)` or an `upstream_events()` function; that shape does not match this deployment.

To handle the actual observed shape, added source-only `server/kitty_gateway_turn_adapter_v6.py`, tested in `server/test_kitty_gateway_turn_adapter_v6.py`. The passive adapter consumes only **authenticated upstream-provider** transcription events, supports explicit VAD events when present, and falls back to the provider's own completed item ID when no explicit VAD stop is present. It never derives a speaker identity from those items, and ignores user/S3-provided `kitty.speaker.result` and `kitty.memory.semantic` claims. A separate external trusted issuer must sign the exact randomly generated call ID, item ID and transcript; without that signer, the adapter cannot return private context. Unknown, cancelled, replayed, changed-speaker and disconnected turns revoke authorization; 120-turn rolling notes are covered by offline tests. No other inference worker, filesystem storage, or direct changes to the existing realtime socket forwarding are introduced.

**Current remaining blocker:** There is no real independently trusted speaker-to-microphone-turn attestation issuer or live per-item owner-grant transport; the gateway also lacks `owner_grant` and `AttestedLiveCall` references. Source-only tests generate synthetic signatures and cannot validate real human identity. Adding a signature whose issuer only believes a `voice_probable` match would be a privacy regression. Do not enable owner-private automatic recall, persistent owner fact writing or a live gateway patch until the trust issuer and exact provider event forwarding scope have been reviewed on a *staged* gateway copy.

**No Ubuntu commands are required for this source-only checkpoint.** Preserve the working `kitty-memory-v6.service` owner-grant 403 protection, Open WebUI realtime voice, C5 v38 BLE, S3 SD authority and Mac AI/TTS. The next safe engineering action is to build a trusted speaker-proof issuance channel and version-checked, opt-in integration in staging. If a code checkout for the real gateway is needed, obtain it without printing personal prompts, service environment, bearer tokens or entire private `realtime.py` in chat.

## Progressive owner voice familiarity — November 4 (SOURCE-ONLY)

**User requirement:** The more the enrolled owner naturally speaks with Kitty, the easier it should become for her to recognize their voice. This is a convenience/recognition improvement, not a claim that a voiceprint alone proves a human is present. No repeated manual `memory ai on` phrases, daily re-enrollment or concurrent Mac model work should be required.

**New code on GitHub main, not yet deployed to the live Ubuntu gateway or memory service:**

- `kitty_attested_live_call_v6.py` supports an optional SHA-256 audio digest inside a trusted short-lived, session+item+transcript-bound independent speaker attestation. Only an independently authenticated, consented owner utterance with a matching microphone WAV can enter learning. Signing with a guessed X-vector voice label is **never** proof.
- `kitty_voice_learning_v6.py` validates signed owner speech + separate enrolled owner session grant + explicit `adaptive_learning_consent=True` and pinned model/profile ID, validates bounded clean 16k mono WAV, checks similarity to immutable protected enrollment anchors (and margin to any separately enrolled speaker anchors), refuses duplicate audio, wrong model, wrong role and clipping, and returns only a candidate adaptive profile. It does not persist WAVs or run on the realtime audio event path.
- `kitty_owner_voice_postcall_v6.py` retains **at most one** bounded verified WAV in RAM per active call. When a call ends, one CPU worker processes it; no PCM changes or extra Mac AI/TTS inference during conversation. It checks explicit consent before holding audio, again on commit; voice capture and adaptation are discarded on unknown identity, revocation, cancellation, concurrent profile edits, invalid signed proof or CPU busy. No WAV or transcript survives successful processing in the profile file.
- `kitty_owner_voice_profile_store_v6.py` provides protected, original-unchanged ECAPA profile compare-and-swap via the existing memory-service `MODEL_LOCK`.
- `kitty_xvector_adaptive_store_v6.py` provides 0600 mode, an exclusive file-lock / atomic write and compare-and-swap for the dedicated X-vector shadow profile. `kitty_owner_voice_learning_factory_v6.py` offers **disabled-by-default** factories for both encoders.
- `kitty_voice_adaptation_policy_v6.py` now supports pinned 192-dimensional ECAPA or 512-dimensional X-vector embeddings but never mixes models. Original anchors are immutable; adaptive samples are capped at **six**, spaced at least **24 hours** apart and expire after **90 days**. Three independently verified adaptation samples must exist before they form an active cohort. This means recognition can progressively improve over multiple ordinary days/calls, not instantly after a single uncertain phrase.
- `kitty_voice_adaptive_scoring_v6.py` computes candidate-only similarity from a verified recent cohort while retaining a conservative original-anchor resemblance floor. The live X-vector shadow worker can opt in with `KITTY_XVECTOR_ADAPTIVE_CANDIDATE=1`, but the default is OFF. The old X-vector identity thresholds are NOT reduced, and an adaptive match still returns only `probable` / candidate, never a trusted `person:owner` for memory authorization.
- `kitty_xvector_shadow_worker_v6.py` adds bounded post-call 512-D embedding generation and a private profile-refresh cache, with no extra audio-frame work and no model loading/downloads on S3.

**CI:** Synthetic owner proof, microphone binding, false-voice/guest denial, owner consent, replay, 120-turn continuity, poor-quality microphone rejection, 192D/512D model mismatch, X-vector threshold benefit, protected template writes and cancellation races are covered by dedicated Python tests in the combined S3/C5 workflow. No true false-accept/false-reject rate (FAR/FRR) is yet established from live recordings, voice clones, noisy rooms or guest interruptions; synthetic passing tests are not a biometric accuracy benchmark.

**Important activation prerequisites (not yet satisfied):**
1. A real independent, microphone-turn-bound speaker-verification issuer must exist. The existing X-vector voice probability, a spoken claim, S3 key or paired iPhone are insufficient. The older Secure Enclave proof helper and short-lived owner session grant are not wired into actual realtime calls. If a challenge/liveness step is needed, use it only as an extra factor, not a guarantee against cloned speech.
2. The private owner voice profile must explicitly enroll and separately consent to adaptive learning, with an exact pinned local model identity. Current existing profiles lack some of these opt-in metadata fields, and the X-vector shadow profile remains intentionally non-authorizing. Never automatically treat legacy recordings or unverified SD summaries as owner samples.
3. Stage the gateway integration with bounded upstream audio capture, verified per-item attribution and a **post-call-only** CPU queue. Test on the actual deployed gateway layout; do not patch its multiply forwarded event loops by a broad string replacement or block WebSocket forwarding. Keep Open WebUI on the existing Ubuntu VM and Mac model/TTS unchanged.
4. The Ubuntu voice adaptation profile is a *derived* private cache; the S3 SD remains the durable Kitty memory authority. Do not silently overwrite S3 voice profiles or copy voiceprint vectors to public GitHub. Future SD portability/consent revocation requires its own explicit sync/erase design.

**Deployment status:** NO deployment of this progressive voice-learning batch, no firmware flash or C5 v38 change, no owner identity issuer, and no live authentication guarantee. The previously successful `kitty-memory-v6.service` owner-grant guard, HTTP 403 denial and working voice pipeline remain as established. Do not re-run the owner guard installer or enable X-vector adaptive candidate config based only on offline tests.

### Calibration refinement — verified adaptation vs live recognition

X-vector enrollment and current live X-vector candidate recognition thresholds must remain separate from safe learning admission. Prior physical genuine voice scores near 0.94–0.97 would not all clear a 0.965 training floor, even after independent proof. For a **separately verified owner utterance only**, `kitty_voice_learning_v6.py` supports an explicitly pinned `verified_learning_floor` as low as **0.92** for the X-vector shadow profile, while preserving its original `min_genuine_floor >= 0.965` and live candidate thresholds (0.960 conversational hints / at least 0.965 default identity threshold). A probable X-vector score without independent owner proof, a forged transcript, wrong audio hash or unconsented profile never trains.

The candidate matcher includes adaptive observations only after three verified, 24-hour-spaced entries and only if its original anchor resemblance is at least 0.90. This can improve *candidate* sensitivity but does not establish that the voice is human, live or certainly the owner, and never authorizes private memory by itself. Before enabling, evaluate independent impostor/voice-clone false-accept results and user genuine holdouts; no FAR/FRR has been measured on live Kitty recordings for this work. The existing shadow profile is **not** automatically opted in by a repository update.

## 2026-11-04 continuation — reviewed voice learning and safe familiarity

**Objective:** Normal Kitty conversations should make future recognition of the owner's voice easier, without accidentally training on guests or ChatGPT's playback, and without silently enabling private owner-memory access.

**Status:** The signed-grant private memory-service fix from earlier November 4 remains successfully deployed and returned HTTP 403 for unverified private semantic requests. Everything in this section is **source-only on GitHub `main`**, not deployed into the running Ubuntu memory service, live `open-webui` gateway or iPhone binary. No S3/C5 firmware flash, Mac model/TTS deployment, SD memory write, Docker restart, or voice profile modification took place.

### Review-based verified adaptation (optional bootstrap)

- **Audience separation** in `kitty_attested_live_call_v6.py`: default `purpose="turn"` attestations are the only type accepted by per-turn private-context logic. `purpose="learning"` receipts require a specific microphone audio SHA-256 digest and are cryptographically distinct. A reviewed training sample cannot become a private-memory authorization ticket, and a private-memory ticket cannot be used to train the voice profile.
- **`kitty_owner_voice_review_issuer_v6.py`**: a source-only, finite one-time owner review challenge for a completed, gateway-observed S3 microphone item. A callback supplied by the trusted gateway returns the *actual* audio and final transcript; request JSON/SD speaker claims must never supply that callback. It checks 16 kHz/mono PCM quality, source provenance, no overlap/playback, explicit biometric-learning consent, and validates an enrolled owner's P-256 signature over exact session ID, upstream provider item ID, audio SHA-256, transcript SHA-256 and nonce. It returns a **learning-only**, 10-second HMAC receipt. Pending review state is memory-only and single-use. A user-approved clip is not magical voice liveness proof and should never be mistaken for permission to expose owner-private historical memory.
- **`ios/CuteDisplay/KittyOwnerProofV6.swift`**: an optional Secure Enclave `signVoiceLearningReview` helper with `reviewedAndConsented` validation. The iPhone app does **not** yet expose a review/playback UI, register an enrolled owner key, or connect to the issuer endpoint. Do not treat BLE pairing as enrollment.
- **`kitty_owner_voice_review_workflow_v6.py`**: pure coordinator that takes the one-time human-reviewed receipt, retrieves the same trusted gateway microphone item, validates an independently issued owner session grant and queues at most one bounded sample to the existing `PostCallOwnerVoiceLearner`. CPU ECAPA/X-vector embedding and compare-and-swap profile update run only *after* the call; original enrollment stays immutable. Cancellation, revoked consent, changed audio or mismatched owner grant drop the sample. End-to-end synthetic tests cover owner approval through successful protected profile update and fail-closed cases.

### Natural in-call candidate familiarity

- **`kitty_voice_familiarity_hints_v6.py`**: a bounded, in-memory streak of multiple independently observed *CPU candidate* speaker scores. Three consistent items at the existing 0.960 floor can produce a stronger **candidate-only** greeting hint; unknown/guest/ambiguous/echo or playback turns, cancellation and timeout clear the streak. Its output explicitly always says `owner_authenticated=False`, `private_memory_authorized=False`, `profile_learning_authorized=False`. No voiceprint writes occur in this path.
- **`kitty_realtime_speaker_v6.py`** passes only a bounded CPU candidate similarity score, and **`kitty_realtime_gateway_observer_v6.py`** may generate a harmless `candidate_familiarity` label when explicitly enabled. The existing deployed gateway does **not** enable this; no live source was modified. It never changes the speaker ID from `unknown` to owner.
- **Legacy private recall hardening in GitHub source:** `KittySpeakerObserver.authorized_recall()` and `complete_recall()` now fail closed regardless of a `voice_probable` x-vector match, so the old nominally "authorized" voice-match gate cannot release historical snippets. The deployed memory service independently continues to deny private requests lacking owner grants, but the live gateway has not been upgraded to this source yet. The separate, independently attested turn bridge remains disabled until a real trusted issuer is integrated.

### Test status and remaining blockers

Targeted GitHub Actions steps **`Verify secure owner-voice adaptive learning from confirmed turns`** and **`Reject voice-probable private recall and validate candidate-only familiarity transport`** passed in workflow run `41769506357`; the combined firmware build was still ongoing at last check. Earlier red intermediate CI runs after introducing audience separation were due to a test expecting an audio-less learning ticket to be constructed. The safer issuer now correctly rejects such tickets at issuance; that assertion was fixed and the updated targeted tests passed.

**Remaining for actual everyday behavior** (do not misstate source tests as deployed functionality): independently verified microphone identity (real positive/negative impostor evaluation), a trusted bridge between actual provider item and corresponding microphone bytes, optional reviewed owner enrollment/consent UI and server endpoint, and safe opt-in staging in the private Open WebUI gateway's observed event-loop shape. Current human-reviewed per-sample training is **not hands-free**; ordinary probable recognition can provide safe familiarity hints but cannot silently update verified owner profiles or authorize private facts. Do not enable owner-private automatic recall, grant issuing from `voice_probable`, or a background automatic learner without trusted provenance.

**Safety/operation:** Keep original SD archive, voice anchors, BLE on C5 v38, current S3 realtime and Open WebUI running. No hardware flashing or new full service rebuild is requested for this checkpoint.

## Ubuntu voice-safety stage applied successfully — 2026-11-04

The operator ran the single-use `git show FETCH_HEAD:server/kitty_v6_voice_stage_deploy.py | python3 - --apply` on the live Ubuntu VM and received exactly:

```text
KITTY_V6_VOICE_SAFETY_STAGE
backup=created
candidate_identity_guard=patched
optional_helpers_staged=14
memory_service=healthy
private_403=verified
candidate_only_safety=staged
live_owner_auto_learning=off
open_webui_audio=untouched
esp32_firmware=untouched
```

**Supersedes any earlier suggestion to run this installer:** the transaction is installed. Do not rerun `--apply`, which intentionally refuses a prior installed transaction. Private transaction backup remains in the operator's Ubuntu state directory. No rollback indicated. GitHub Actions run `41770785455` completed with success (including targeted deployment/rollback, owner voice, and X-vector security tests, plus firmware build), but CI does not constitute a physical firmware flash or live biometric accuracy test.

Live memory-service owner grant/403 authorization remains operational, X-vector experimental voice matching is candidate-only, and the 14 new optional modules are present. **No Open WebUI gateway integration, private historical recall, hands-free verified learning, consented owner review UI or S3/C5 firmware change occurred.** This is a reliable release checkpoint, not end-to-end V6 completion.

Next work, in priority order: (1) integrate bounded extractive same-call context into the private gateway with exact provider item tracking, without private lookup or model/audio changes; (2) establish real speaker-independent, per-turn authorization and optional owner review via trusted microphone audio binding; (3) gated private history recall and consenting adaptive learning, after real guest/playback/liveness tests; (4) one uninterrupted multiperson long call with log/heap/UART acceptance. Avoid repetitive server status checks, new firmware flashing, or re-installation of the completed voice safety stage.

## C5 v39 transparent captions and passive gateway staging — November 4

**Current source:** latest `main` includes a passive gateway observer `server/kitty_passive_turn_bridge_v6.py`, regression tests `server/test_kitty_passive_turn_bridge_v6.py`, and `server/kitty_gateway_provider_scope_v6.py` plus safe-source-shape tests. The bridge is **not yet installed in Open WebUI**. It can retain an early decision across 120 test turns only when independently signed exact-turn provenance exists; without a real issuer, it intentionally returns no owner-private context. It never modifies working audio transport. The actual private gateway event receive scope remains unverified. One safe Ubuntu command for a status-only result is in [KITTY_V6_C5_V39_AND_GATEWAY_TEST_PLAN_2026-11-04.md](KITTY_V6_C5_V39_AND_GATEWAY_TEST_PLAN_2026-11-04.md). Do not run older whole-file source replacement patches.

**C5 v39 display code prepared:** `firmware/CuteDisplay/C5CallFace.h` now renders two lines of conversation subtitles in **black glyphs directly over the Kitty-chan face**, located at y=40 and y=56, preserving width-aware UTF-8, animation and PCM lip-sync. The opaque 320x34 black bottom caption bar and separate black status capsule were removed. The status text is also drawn directly on the background. `C5FirmwareVersion.h` is **39** so C5 can receive a version-checked OTA after the corresponding S3 update, or v39 can be flashed to the C5 alone via USB when accessible.

The new v39 caption tests and revised previous display contract are green as of current CI. Full C5/S3 compile is a separate gating step; no C5 firmware has been flashed by ChatGPT. **The live C5 is still v38.** Do not flash a public CI S3 image without the private `KITTY_SYNC_PRIVATE_HEADER`: the package's default public build omits private sync credentials. For a display-only trial, direct C5 USB flash of the matching verified project avoids unnecessary S3 changes; alternatively use the existing locally built S3-to-C5 UART OTA with private config preserved.

GitHub release/test details: [KITTY_V6_C5_V39_AND_GATEWAY_TEST_PLAN_2026-11-04.md](KITTY_V6_C5_V39_AND_GATEWAY_TEST_PLAN_2026-11-04.md).

**Still incomplete for V6:** real gateway provider turn hook, trusted per-turn human speaker issuer and iPhone enrollment/review UI, consented live voice-learning path, live long-call continuity and owner cross-call privacy acceptance. The previous Ubuntu memory-service owner grant/HTTP403 and 14 staged modules are confirmed; no need to re-install them. Current source-only tests are not a live acceptance certificate.

## Live provider decode hook confirmed — gated Ubuntu deployment ready

Operator output from the active Open WebUI container (Nov 4): one `provider_events` async function, one `async for ... in upstream` receive path, one JSON event decode, and one browser `ws.send_json(event)` call inside that function; a separate `client_events` handler exists. The newer probe reported `event_decode_hook_candidate=yes`. The older broad whole-file `passive_hook_safe=no` remains expected because other forwarding sites exist. No live changes were made by either probe.

New main-source rollout: `server/kitty_gateway_decode_hook_patch_v6.py` injects one passive observer immediately after a structurally verified upstream JSON decode. This observes only limited event types and never changes any WebSocket forwarding, session prompts, private owner authorization, speaker enrollment or background learning. Ambiguous/customized sources fail closed.

`server/kitty_gateway_passive_rollout_v6.py` is a one-command HOST installer: pins FETCH_HEAD, privately backs up the actual live realtime.py outside GitHub, stages eight exact-matched optional Python modules into open-webui, atomically replaces only validated source, restarts only open-webui, checks Docker healthy and attempts hash-checked rollback on failure. No prior Ubuntu memory service owner-guard installer is rerun. Source, secrets, bearer tokens, transcripts and voiceprints must never be uploaded to GitHub.

Operator command (when Kitty idle):

```bash
cd ~/kitty-v6/private/kitty-sync-deployment/live-sync-build
git fetch origin main
git show FETCH_HEAD:server/kitty_gateway_passive_rollout_v6.py | python3 - --apply
```

Stop on `rollout_error` and share only fixed labels/rollback state. Test suites `server/test_kitty_gateway_decode_hook_patch_v6.py` and `server/test_kitty_gateway_passive_rollout_v6.py` passed in targeted CI before presenting the command. Expected successful labels: `gateway_hook=installed`, `gateway_health=healthy`, `provider_forwarding=unchanged`, `private_recall=disabled`, `automatic_voice_learning=disabled`, `firmware_and_SD=unchanged`.

**DO NOT mark V6 complete:** This establishes a safe upstream event observation point but not trusted human speaker verification, long-term private memory injection, automatic owner-learning, live long-call summaries or actual C5 v39 flash. C5 v39 caption and full S3/C5 compile passed in workflow run 41774229414; physical C5 stays v38 pending test. Keep the 403 memory-service guard and S3 SD authority unchanged.

Recovery and C5 test details: docs/KITTY_V6_C5_V39_AND_GATEWAY_TEST_PLAN_2026-11-04.md.

## Gateway rollout chmod failure and guarded recovery — 2026-11-04

Operator attempted the first `kitty_gateway_passive_rollout_v6.py --apply` inside the Ubuntu private checkout. It stopped at `os.chmod(backup,0o600)` on the root-owned file created by `sudo docker cp open-webui:/app/backend/open_webui/routers/audio/realtime.py <private-host-path>`.

The observed traceback was `PermissionError: [Errno 1] Operation not permitted` at line 255. This happened **before the gateway Python source patch, helper installation, transaction manifest write, or Docker container restart**. The existing live Open WebUI gateway was left unchanged by this attempt. The temporary, root-owned backup remains inside the invoking user's private local state directory and should not be uploaded to GitHub or arbitrarily deleted.

Fix committed to GitHub main: `server/kitty_gateway_passive_rollout_v6.py` now reads the existing container source through `sudo docker exec open-webui cat ...` without printing it, and saves the original bytes directly with the unprivileged host user's `os.open(O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW, 0600)`, fsync, and SHA-256 verification. No `sudo chown`, chmod of a root-owned Docker copy, or shell cleanup step is needed. Also catches host permission errors with a bounded error label instead of an unsolicited traceback.

Focused GitHub Actions test `server/test_kitty_gateway_passive_rollout_v6.py` confirms host-file ownership, mode 0600, single-use backup creation, invalid-source rejection, and unchanged recovery rules. The user should only retry from the newest fetched GitHub main after Kitty is idle:

```bash
cd ~/kitty-v6/private/kitty-sync-deployment/live-sync-build
git fetch origin main
git show FETCH_HEAD:server/kitty_gateway_passive_rollout_v6.py | python3 - --apply
```

Successful rollout still means **passive transcription-event observation only**, not live trusted human speaker authorization, owner-private automatic recall or hands-free voice learning. Preserve the working S3 SD/archive, the live `kitty-memory-v6.service` signed-owner 403 guard, C5 v38 hardware and the staged C5 v39 display code. If the corrected rollout reports `live_provider_layout_incompatible` or another fixed refusal label, stop and use that result to tighten the AST matcher; do not disable security gates or repeat old installers.

## Passive gateway rollout refused before mutation — live layout mismatch (Nov 4)

Operator's second `kitty_gateway_passive_rollout_v6.py --apply` attempt returned only:

```text
KITTY_V6_PROVIDER_PASSIVE_ROLLOUT
rollout_error=live_provider_layout_incompatible
```

This is the **intended fail-closed offline AST patch refusal**: the installer backed up the private host-only gateway source, but rejected it inside `module.patch(source)` **before copying helper modules, writing its transaction manifest, altering live realtime.py or restarting the Open WebUI container**. Thus no deploy/rollback action is needed. Existing memory-service signed-owner/HTTP403 protection and source-only C5 v39 caption change remain unaffected. No firmware flashed.

The previous read-only topology probe confirmed one provider_events handler, one async upstream loop, one event decoder and one provider forward in that loop, but it did **not** prove the stricter patcher's required specific placement and `json.loads(loop_item)` argument shape.

New `server/kitty_gateway_decode_preflight_v6.py` is read-only, prints a closed set of labels about decode call argument provenance (upstream item, upstream-item attribute, separate name, expression), assignment type, nesting/position, single-line status, and an inferred refusal category. It never prints the live gateway code, prompts, service paths, transcripts or tokens. Synthetic fixture CI test `server/test_kitty_gateway_decode_preflight_v6.py` passed.

Run exactly once when convenient (no service restart, backup or file writes):

```bash
cd ~/kitty-v6/private/kitty-sync-deployment/live-sync-build
git fetch origin main
git show FETCH_HEAD:server/kitty_gateway_decode_preflight_v6.py | sudo docker exec -i open-webui python3 -
```

Based on these fixed labels, build a precise source-shape-specific patcher with regression tests, then **only** attempt a gated rollout. Do not replace realtime.py wholesale or weaken private memory speaker authorization. This remains passive observation-only, not the final independent owner verifier or automatic memory-learning integration.

## Latest private gateway decode diagnosis and compatibility fix — 2026-11-04

Read-only diagnostic on actual Ubuntu `open-webui` reported:

```text
KITTY_V6_PROVIDER_DECODE_PREFLIGHT_READ_ONLY
provider_handler=one
client_handler=one
provider_loop=one
provider_forward=one
provider_loop_body=if
event_decoder=json_method
event_decoder_position=later_direct
event_decoder_input=other
event_decoder_assignment=direct_assignment
one_line_decoder=yes
source_python=valid
exact_patch_refusal=provider_decode_unrecognized
```

This clarifies the prior safe refusal: the provider loop contains an early `if` filter and later `event = provider_message.json()`-style method call, not the former narrow first-statement `json.loads(raw)`. Since the legacy diagnostic does not expose the method receiver, the patcher must still **verify it is exactly the async-for upstream message variable**. Never accept `browser_message.json()` or a decoder outside the upstream receive loop.

The new `server/kitty_gateway_decode_hook_patch_v6.py` accepts exactly one direct upstream-loop item `.json()` with zero arguments or a direct `json.loads(loop_item)` and tolerates preceding if-guards when they don't reassign the item or `event`. The injected hook still observes only five fixed provider event types; it doesn't change forwarding, model prompts, memory authorization, SD or C5. `server/test_kitty_gateway_decode_hook_patch_v6.py` covers the diagnosed if + later `.json()` layout, audio-event forwarding bit-for-bit, guards and unknown-source failures. GitHub targeted CI for this test passed.

The single transaction host rollout script `server/kitty_gateway_passive_rollout_v6.py` now returns a fixed, non-sensitive *specific* refusal code if any other private layout variation prevents the patch; it never echoes source or credentials. Because the last two installer attempts failed before creating the transaction manifest, neither changed the Open WebUI gateway, and **no rollback, source cleanup, firmware flash or memory-service redeploy is required**.

When idle, one attempt using the latest fetched `main` is appropriate:

```bash
cd ~/kitty-v6/private/kitty-sync-deployment/live-sync-build
git fetch origin main
git show FETCH_HEAD:server/kitty_gateway_passive_rollout_v6.py | python3 - --apply
```

Success markers: `gateway_hook=installed`, `gateway_health=healthy`, `provider_forwarding=unchanged`, `private_recall=disabled`, `automatic_voice_learning=disabled`. If it still rejects the private layout, do not rerun; copy only the `rollout_error` label. The C5 v39 black transparent-caption firmware remains source/CI-ready but no hardware flash has been performed. Long-call live memory, real per-turn owner authentication and hands-free voice learning are still release gates.

## Passive gateway source backup succeeded but staging failed — 2026-11-04

The operator's next guarded gateway rollout attempt printed:
```text
KITTY_V6_PROVIDER_PASSIVE_ROLLOUT
source_backup=created
rollback=no_gateway_change
rollout_error=deployment_failed
```

This distinguishes it from the earlier source-layout refusal. The strict source patcher accepted the live gateway and the host-owned source backup was created. The transaction failed **inside the staging/apply phase before the new realtime.py was atomically installed**. The installer explicitly reported rollback=no_gateway_change; no Open WebUI restart was reported. The old generic deployment_failed label hid whether the failure was helper copy, Python import, temporary candidate copy, or permission/atomic replacement. We cannot assert the precise stage without a stage-specific log.

Updated on main:
- `server/kitty_gateway_passive_rollout_v6.py` now emits only bounded fixed failure-stage labels (`copy_helpers`, `preimport`, `copy_candidate`, `atomic_replace`, `restart`, `commit_state`) rather than a generic label or traceback.
- The atomic replace and hash-verified staging-file cleanup now use explicit container uid 0 only for controlled on-disk operations. The regular Open WebUI runtime user and the preimport check remain unchanged. Exact original ownership/group/mode are preserved.
- A previous completed `rolled_back` manifest is allowed to identify and remove an orphan temp file **only if both the original gateway checksum and staged-file checksum match**; otherwise it refuses without deleting unrelated files.
- New offline tests cover exact-checksum cleanup and privileged-only atomic operations; the existing full audio-forwarding checks remain in CI.

Operator must not rerun the old revision. On a fresh FETCH_HEAD, an **idle-only** single retry with the updated host-side installer is the planned next operation; if it reports `deployment_failed:<stage>`, stop and provide the short stage string, without disclosing private source, logs, secrets or data. The standalone memory-service private 403 guard remains installed and should not be repeated. The currently operating C5 v38 is unchanged; C5 v39 black captions over Kitty-chan are code/CI-ready but not flashed.

## Atomic replacement blocked after successful staging — 2026-11-04

The next host-side Ubuntu gateway passive rollout returned:

```text
KITTY_V6_PROVIDER_PASSIVE_ROLLOUT
source_backup=created
rollback=no_gateway_change
rollout_error=deployment_failed:atomic_replace
```

The exact source patch and prerequisite staging succeeded far enough to reach `move_candidate()`; replacing the original private `/app/backend/open_webui/routers/audio/realtime.py` failed. The installer then checked the source checksum and reported `rollback=no_gateway_change`, with no Open WebUI restart. **Do not retry the same atomic replace path.** A Docker single-file bind mount would prevent `os.replace()` with an EBUSY error, but this remains a hypothesis until read-only mount checks confirm it.

`server/kitty_gateway_atomic_mount_probe_v6.py` now reports only fixed mount labels and container filesystem statuses: whether the exact file is its own bind mount, whether a parent directory is mounted, read-only flags, root directory writability, target mountpoint state, and stale staging-file presence. It does not print private paths, source contents, Compose secrets, mounts' host Source, credentials or transcripts. `server/test_kitty_gateway_atomic_mount_probe_v6.py` includes synthetic bind-mount, volume, overlay and confidentiality cases; the targeted CI step passed.

One **read-only host** command to distinguish file bind mount vs overlay/inode error:

```bash
cd ~/kitty-v6/private/kitty-sync-deployment/live-sync-build
git fetch origin main
git show FETCH_HEAD:server/kitty_gateway_atomic_mount_probe_v6.py | python3 -
```

Do not restart the container or edit the mount source before this status is available. If the target is an exact-file bind mount, replace the deployment strategy with a verified host-source transaction and safe rollback; never force a rename over the mounted file. If the target is an ordinary container overlay path, introduce a bounded errno-only atomic rename failure classifier, preserving original source and speaker permissions. The earlier separate Ubuntu memory-service 403 guard and C5 v39 compilation remain unchanged. Voice learning and owner history are still off.
