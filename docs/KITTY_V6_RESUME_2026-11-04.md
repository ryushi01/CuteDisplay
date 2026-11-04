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
