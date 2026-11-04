# Kitty V6 — C5 v41 full-screen delegated AI transport fix

## Latest operator checkpoint — v41 flashed and Kitty working

**2026-11-04 — user confirmed:** The private combined S3 + C5 v41 firmware has been flashed and Kitty works in conversation. Treat this installed version as the **new accepted working baseline** for subsequent changes. C5 firmware source version is `41` on GitHub `main`; the full v41 GitHub Actions combined firmware run [41809097567](https://github.com/ryushi01/CuteDisplay/actions/runs/41809097567) passed.

**Validation limits:** This is a direct report of successful flash and normal operation, not a fresh diagnostic log confirming the C5 UART OTA version banner, all five caption rows, physical button stop latency, absence of every delegated `NACK CALL_ACTIVE`, private memory sync completeness, or automatic personalized recall. Keep those as targeted follow-ups instead of reopening the already-working firmware baseline. The earlier v40 failure evidence remains below as a historical diagnostic, not the current installed state.

**Privacy / rollback:** Keep the known working v41 private build and earlier v40 rollback build offline. The released local S3 sketch and binary embed private synchronization credentials; never push them to GitHub, upload public CI artifacts, or attach them to support tickets/chats. Preserve microSD authority, NVS, iPhone BLE, voice profiles and existing gateway/AI/TTS topology. Future source changes require a new C5 OTA version only if the C5 image itself changes.

## Operator hardware results (S3 + C5 v40 combined private release)

- C5 v40 UART OTA was validated by the physical board: `[S3 OTA] C5 reports v40, OTA slot=6553600 bytes`, then `[S3 OTA] SUCCESS: new display firmware confirmed after reboot`.
- After C5 restarted, STATUS showed LCD/BLE/Wi-Fi all 1 and battery 100%. S3 entered `CALL_LISTENING`, `CALL_THINKING`, `CALL_SPEAKING`; multiple responses played with nonzero output_peak.
- Realtime I2S remained at 24 kHz and mic drops and dropped audio stayed zero throughout the provided log. S3 loop task stack-free ~6088–6172 bytes. When AI TLS was active, internal_free dipped to ~56312–57740 and largest internal to ~31732 bytes; these are headroom measurements, not observed allocation failures.
- Four back-to-back `[AI] UART rejected packet N: NACK CALL_ACTIVE` errors (packet IDs 52001–52004), including a request that had `[AI] Request finished: HTTP=200 transport=0`, `[AI PERF] Generated UART bytes=0 acked=0 packets=0 total=19503ms`, `[AI] Stream ended with an error`. Another request showed the same NACK with HTTP 200 and 17039 ms elapsed. The operator reports that Kitty sometimes says phrases like "sorry, I cannot proceed." Those phrases are **not verbatim attributable to a specific tool result in the log**; the observed packet failures can explain at least some failed delegated answers, but additional unrelated model/gateway failures remain possible.
- Local SD unverified turns were archived and owner fact writes correctly skipped; a `speaker=person:shana` record is only an unverified speaker claim, not authentication. No change to memory authority, shared/private separation or semantic access gating is authorized.

## Root cause and corrective change

C5 v40 responded `NACK CALL_ACTIVE` to the S3's **normal `AI_BEGIN`/`AI_END` and `AI_DATA` UART streaming packets whenever full-screen Call Mode was active**. This was intended to suppress the legacy AI chat bubble but accidentally broke S3 `BrainAI::onAck`, which expects `ACK AI` for streaming flow-control. On a matching NACK the S3 sets `failed=true` and the HTTP SSE event handler ignores subsequent data (`!failed` guard), even if the server returns HTTP 200. As a result the delegated chat model's answer can be lost and the realtime caller may return a failed tool result.

C5 **v41** preserves the fullscreen five-line transparent caption drawing and old bubble suppression but instead responds `ACK AI` to valid `AI_BEGIN`, `AI_DATA`, `AI_END` UART packets during a Call Mode or pending stop. It does **not** mutate the normal bubble buffer, start AI typewriter, or redraw a hidden panel in this case. Outside calls, legacy regular AI display streaming still updates the bubble normally, and malformed/out-of-state traffic continues to receive NACKs as before.

No S3 BrainAI or Open WebUI streaming behavior changed. Version was bumped from 40 to **41** to allow one version-checked C5 UART OTA from a new **private combined S3+C5 firmware** (private sync header embedded and preserved locally, never shared in public release).

## Regression and acceptance

- `server/test_kitty_c5_ai_uart_ack_v41.py` ensures all three AI_* cases acknowledge in call mode without rendering, version=41, S3 flow-control dependency preserved, and bubble still suppressed.
- Existing v40 call-stop and five-line UI contracts now expect v41 and remain in CI with the new test; C5 firmware compile and combined S3 build remain required.
- Hardware validation still needed: after a **single** new combined firmware upload via S3 (no full-flash erase, preserve NVS/microSD, C5 OTA v41), verify `[S3 OTA] ... v41 ... SUCCESS`, that responses no longer trigger `NACK CALL_ACTIVE` nor `[AI] Stream ended with an error`, and that ordinary chat remains absent during fullscreen Call Mode but resumes on a new normal message after exit. Also retest physical C5 stop, five-line captions, iPhone BLE and S3 memory sync (`memory sync status`).
- If AI still sometimes says it cannot proceed without the UART errors, diagnose separately from new short `[AI]`, `[CALL]`, `[CALL NET]` metadata surrounding the occurrence; do not remove safety gates or reset SD data.

**Release checkpoint:** The operator has since confirmed a successful v41 combined firmware flash and normal Kitty operation. This does not establish exhaustive hardware regression success; targeted checks above remain relevant. Build future private combined releases only with the canonical local sync header; public CI binaries omit credentials.
