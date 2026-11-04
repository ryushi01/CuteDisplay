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
