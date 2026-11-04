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
