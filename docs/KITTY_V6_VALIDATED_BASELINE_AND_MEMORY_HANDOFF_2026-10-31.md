# Kitty V6 — hardware-tested baseline and next-chat memory handoff (2026-10-31)

## Status: working runtime, NOT fully functioning long-term memory

**Repository:** `ryushi01/CuteDisplay`
**Development branch:** `feature/kitty-semantic-v6-cpu`
**Ubuntu checkout:** `/home/ryushi/kitty-v6-validation`
**Firmware commit tested:** `cf507454edb5379001479364301ca043430ecc89`
**GitHub Actions combined firmware build:** [run 41199575994](https://github.com/ryushi01/CuteDisplay/actions/runs/41199575994), completed successfully.
**Compiled artifact:** `CuteDisplay-CombinedFirmware` → `CuteDisplay-CombinedFirmware.bin` (S3 application + embedded C5 v36).
**Installation:** User successfully flashed the *generated combined S3 sketch via Arduino IDE* (not the staged OTA updater). The S3 automatically recognized C5 v36.
**Do not reflash, reformat microSD, reset voice profiles, or change realtime audio just to begin the next investigation.**

### Observed working behavior (device logs / user confirmation)

- S3 booted normally after a manual restart. `reset_reason=1`; `running=app0 offset=0x00010000 selected=app0` at boot. Firmware banner remains `CallFace-v23-dev` and does **not** uniquely identify the new release.
- C5 UART connected at 921600 baud (S3 TX GPIO47/RX GPIO21). `[S3 OTA] C5 reports v36, OTA slot=6553600 bytes` and `C5 already current`. Thus the C5 v36 firmware is confirmed running.
- S3 joined Wi-Fi, established WebSocket realtime calls, and used 24 kHz I2S duplex: BCLK=41, WS=42, microphone=1, speaker=2.
- Voice call alternated `CALL_LISTENING`, `CALL_THINKING`, `CALL_SPEAKING` normally; audible response was indicated by nonzero output peaks. No panic/reboot during the reported calls. User previously reported realtime audio was responsive; **no separate quantitative latency validation** was performed with this release.
- C5 received activity/status messages. **Full-screen caption presentation itself was not separately verified in user report**, although v36 is running.
- S3 reported `[CALL MEMORY] live_refresh=1` and `[CALL MEMORY] context refresh accepted`: gateway supports session memory refresh, but this alone does not confirm speaker preference recall.
- SD card mounted: `[MEMORY] indexed=81 entries, SD-only archive`, total about 959 MB. Index survived S3 restart. This is not proof any particular name or color was written as a retrievable fact.
- Logs recorded `[MEMORY] Realtime user transcript received` and `[MEMORY V6] unverified turn archived; owner fact writes skipped`. This is expected for unverified voice, not an SD failure.
- User reported Kitty recalled name and favorite color **within the first live conversation**, but **forgot after S3 restart**. Same-session answer can come from model short-term conversation context and is **not evidence of durable fact retrieval**.
- Memory-critical realtime readings roughly 31–38 KB free internal RAM, largest contiguous block ~16–29 KB; do not add large workers or synchronous SD calls on audio/WebSocket callback path.
- `[MEMSYNC] disabled: HTTPS endpoint/token/CA not configured` on S3. SD local persistence works separately from remote snapshot sync.
- Serial C5 status reported `ble=1;wifi=1`; don't infer from this alone that the C5's own radio is enabled, because these values reflect system/Brain state.

### Known unresolved memory issues — next-chat priority

Make **one consolidated fix** covering all of the following, rather than repeatedly flashing:

1. Robustly extract introductions and preferences from natural multi-clause spoken sentences (e.g., `Hi Kitty, I'm Shana. Please remember that my favorite color is purple.`). Existing `selfIntroducedSpeaker` relies on `extractFact` and rejects compound introductions.
2. Persist explicitly requested, non-sensitive speaker-attributed preferences to microSD, with confirmation of successful writes and bounded queue handling. Review `speaker_claims_v6.tsv` format and actual saved contents. The `unknown` voice boundary must remain safe.
3. Request asynchronous recall at call start or after introduction, **and after new preference writes**. Existing code requests claim context only when recognizing an introduction, risking stale empty context.
4. Inject eligible recalled preferences into the *direct realtime AI response* as well as the delegated BrainAI chat path. Currently only delegated requests receive `introducedClaimContext` in `BrainRealtimeDirect.h`; `kitty.memory.refresh` carries separate owner facts and may not expose unverified speaker claims. Avoid putting one speaker's memories into long-lived shared system instructions, and clear scoped state on speaker changes/call end.
5. Preserve strict privacy: unverified self-introduction and probabilistic voice match are **not** verified owner authentication. Never give private owner facts to a voice claim. Only allow an explicitly scoped, revocable non-sensitive claim experience without silent privilege elevation.

### Useful code locations

- `firmware/CuteDisplayBrain/BrainRealtimeDirect.h`: `selfIntroducedSpeaker`, `introducedSpeaker`, `introducedClaimContext`, `flushPendingSpeaker`, `kitty.speaker.result`, `conversation.item.input_audio_transcription.completed`, delegated tool path, `kitty.memory.refresh`.
- `firmware/CuteDisplayBrain/KittyMemory.h`: `extractFact`, `queueAttributed`, SD worker, `speaker_claims_v6.tsv`, `requestClaimContext`, `takeClaimContext`.
- `firmware/CuteDisplayBrain/KittyMemoryContextV6.h`: bounded context snapshot.
- `firmware/CuteDisplay/C5CallFace.h`, `C5FirmwareVersion.h`: v36 full-screen rolling text.
- `firmware/CuteDisplayBrain/BrainAI.h`: low-internal-heap delegation guard.
- `docs/KITTY_V6_CHECKPOINT_2026-10-31.md`: server-side private semantic setup and its uncommitted components. **Recheck live server files before editing gateway**.

### Update/deployment constraints

- The local Kitty Update Center at `http://127.0.0.1:8890/` (SSH tunnel from Mac) is currently **quarantine/preflight only**, not an installer.
- Staged release ID `20261031T121713Z-49adbe40adc3`, target S3, 4,179,712-byte `CuteDisplay-CombinedFirmware.bin`, remained quarantined; user instead flashed with Arduino.
- Do not claim HTTPS OTA deployment works end to end; `docs/KITTY_V6_RAGNAROK_443_ONLY.md` explicitly requires a future S3-initiated signed 443-only transport.
- Realtime gateway is Open WebUI at `https://ragnarok-project.com`; private local overrides and memory service must not be committed into public GitHub. Preserve existing Compose overrides when modifying the live server.
- GitHub combined build workflow `.github/workflows/build-s3-with-c5-update.yml`; source changes require another successful build and a deliberate new firmware installation.
- If a subsequent change is needed, keep the existing C5 v36 and working voice/audio implementation intact unless a specific defect warrants modifying them.

### Suggested first actions in a new chat

1. Inspect current code and confirm this handoff before proposing edits.
2. Diagnose claim-file contents without disclosing private SD archive or tokens. Use narrow redacted logs or counts; never upload personal transcript dumps to public issues.
3. Fix same-session saving, post-restart recall, and direct realtime injection in one reviewable change set; run focused regression tests on access boundaries and event order, then one combined build and one device test.
4. Preserve the known-good current working firmware as fallback.

**Success criteria:** say a name and harmless favorite once; see evidence that the preference was durably saved; reboot S3; begin a new call, explicitly self-introduce without re-stating favorite; Kitty correctly recalls it in the *direct realtime response*. Unknown/different speakers must not access private owner memories.
