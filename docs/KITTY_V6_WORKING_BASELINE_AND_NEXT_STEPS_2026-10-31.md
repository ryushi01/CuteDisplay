# Kitty V6 hardware-validated checkpoint — 2026-10-31

**Resume branch:** `feature/kitty-semantic-v6-cpu`
**Repo:** `ryushi01/CuteDisplay`
**Ubuntu checkout:** `/home/ryushi/kitty-v6-validation`
**Validated firmware source commit:** `cf507454edb5379001479364301ca043430ecc89`
**GitHub Actions:** [successful run 41199575994](https://github.com/ryushi01/CuteDisplay/actions/runs/41199575994), artifact `CuteDisplay-CombinedFirmware` (S3 application image embeds C5 v36). This is a *source/build reference*, not an assertion that end-to-end memory recall works.

## Confirmed working on actual hardware

- S3 sketch was flashed using Arduino IDE from the successful **combined** release artifact; user reports successful flash and subsequent normal boot.
- Dual-board S3 ↔ C5 UART operational at 921600 baud. Boot log: `[S3 OTA] C5 reports v36` followed by `[S3 OTA] C5 already current`. C5 v36 is installed and responsive. v36 source introduces full-screen conversation text; *exact on-screen visual behavior was not separately confirmed by the user*.
- S3 Wi-Fi connected and realtime conversation ran: `CALL_CONNECTING`, `CALL_LISTENING`, `CALL_THINKING`, `CALL_SPEAKING`. Audio is functioning; no Guru Meditation crash or speaker queue overflow in the supplied logs. Avoid claiming zero audio drops: diagnostic `mic_drops` rose to 231 over the test.
- SD mounted and indexed after S3 restart: `[MEMORY] indexed=81 entries, SD-only archive`, total ~959 MB. Existing conversation archive persists. This **does not** prove that speaker preference claims are correctly saved or recalled.
- Live gateway indicated `[CALL MEMORY] live_refresh=1` and `context refresh accepted`, which confirms protocol support/acknowledgement, **not** success of preference lookup.
- During one continuous session, Kitty answered the user's name and favourite colour correctly. Following S3 reboot, Kitty could not recall them. Model conversational context may explain within-session success; persistent personalized recall is **unresolved**.
- Current firmware preserves existing microphone/speaker hardware and voice profiles. User plans a dedicated follow-up chat for memory work. **Do not alter this working firmware just to produce this checkpoint**.

## Known issues — highest priority in next chat

1. Robust natural multi-clause introductions and preferences, including `I'm Shana. Please remember my favourite colour is purple`. Current `selfIntroducedSpeaker()` uses `extractFact()` and can reject a multi-clause name.
2. Persist explicitly requested facts with a clear SD write acknowledgement, trustworthy speaker attribution scope, and distinct verified-owner vs unverified claim handling. Current log `[MEMORY V6] unverified turn archived; owner fact writes skipped` is expected and does not mean the unverified claim was stored in `speaker_claims_v6.tsv`. Check that file via safe export/inspection.
3. Asynchronous recall at call start, after introductions and after successful writes. Existing `requestClaimContext` is triggered only at introduction and can race against queued SD writes.
4. Feed only eligible, properly scoped recalled context to the **direct realtime AI**, not merely `BrainAI::startCallDelegation`. Ensure per-speaker isolation, expiry, and never allow spoken name claims or probabilistic voice matches to authorize owner-private memory.
5. Improve CPU voice recognition consistency over time (mic differences from Mac enrolment vs S3, evaluate data quality, enrollment and model behavior; do not relax auth thresholds or silently relabel unknown).
6. Avoid unbounded accumulation of snapshot folders, backups and other files on the Ubuntu AI server. Design quotas, retention limits, atomic cleanup, idempotent upserts and avoid archiving duplicate exports. **Protect voice profiles, live SQLite DB, needed rollback data and active snapshots**. Check actual mounted paths/volumes and service policies before deleting anything.
7. Keep working realtime 24 kHz duplex audio and C5 expression/OTA behavior intact. S3 reported ~31–38 KB free internal heap during calls and ~16–28 KB largest free block. Reuse existing queues/workers; avoid additional large internal-RAM task stacks.

## Safe follow-up workflow

- Begin with this checkpoint plus `docs/KITTY_V6_CHECKPOINT_2026-10-31.md`, checking historical instructions against actual firmware and private server configuration.
- Gather one minimal, targeted SD speaker-claim inspection and one example transcription; don't request repeated full reflashes or lengthy voice tests.
- Implement the memory fixes in a single change set; validate firmware build via GitHub Actions; deploy only when appropriate.
- Never format the SD, erase S3 flash, overwrite private server env or voice enrollment profiles, expose the local memory service publicly, or put credentials in GitHub.
- Update Center at `http://127.0.0.1:8890/` via SSH tunnel is **quarantine/preflight only**; it does not activate staged releases. User flashed successfully through Arduino IDE. OTA production rollout remains separate work.
- The `[MEMSYNC] disabled: HTTPS endpoint/token/CA not configured` boot message may affect server sync; verify actual active private configuration without exposing secrets before interpreting server-side recall.
- The two large log excerpts in the preceding conversation contain a duplicated pre-reboot segment; do not count it as two separate tests.

## Resume objective

**Preserve the hardware-validated Kitty V6 baseline.** In the next chat, solve persistent recall, speaker recognition accuracy, and server storage hygiene as a coordinated project, then run one concise end-to-end test: explicit preference save → confirmed SD persistence → reboot → verified scoped retrieval in direct realtime AI.
