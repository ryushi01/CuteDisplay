# Kitty — CuteDisplay AI Companion 🐱

**Kitty** is a physical, voice-first AI companion with an expressive animated face, two ESP32 boards, and long-term memory. Talk directly to Kitty—not through the phone. The iPhone app is for **initial setup, device settings, and management only**.

> **Frozen checkpoint — 2 November 2026:** Current Kitty S3/C5 realtime audio and C5 **v38** remain the working physical baseline. Automatic post-call summaries are now **hardware-verified** (`accepted=1`, SD journal acknowledgement `2578 → 2878`); approved shared memory (“Mochi Planet”) was previously recalled across calls. **Private owner recall, identity-bound long-call continuity and rolling live summaries are NOT deployed or end-to-end validated.** All accepted current source work and pending cross-AI documentation are consolidated on `main`. The repository does not contain private server credentials, SD contents, or the deployed private Ubuntu gateway. See [November 2 consolidation checkpoint](docs/KITTY_V6_CHECKPOINT_2026-11-02.md) and [detailed handoff](docs/KITTY_V6_CURRENT_HANDOFF_2026-11-01.md).

## What Kitty can do

| Feature | Status |
| --- | --- |
| Natural voice conversation via S3 microphone and speaker, with Open WebUI realtime AI | **Working on hardware** |
| Animated face, expressions and call states on LILYGO C5 | **Working**; C5 v38 preserved |
| Long-term conversation archive on S3 microSD | **Working**; S3 is authoritative |
| Nine-file SD snapshot synchronization to Ubuntu | **Working**; successful finalized snapshots |
| Recall an **explicitly approved shareable** memory across calls | **Verified** with Mochi Planet |
| Familiar-sounding voice hint (“sounds like Shana”) | **Experimental**; voice similarity varies |
| Verified owner identity, private cross-call recall | **Not yet validated**; candidate-only matching never authorizes access |
| Automatic post-call summaries for unverified speakers | **Hardware-verified** idle SSE parsing, microSD summary write and advancing ACK; unverified summaries remain isolated from owner facts |
| Long uninterrupted-call continuity and private recall | **Offline source prototypes only**; bounded extractive speaker-scoped context tests passed, but trusted item/session attribution and live gateway integration are not deployed |
| iPhone companion app for setup/settings | **Configuration role only**, not everyday conversation |
| S3-to-C5 firmware delivery via existing UART | **Implemented**; protect validated C5 build |

## How it works

```text
                 Talk naturally
                       │
           ┌───────────▼─────────────┐
           │ ESP32-S3 — Kitty brain  │
           │ mic / speaker / camera  │
           │ Wi-Fi, realtime, microSD│
           └──────┬─────────┬────────┘
                  │ UART    │ Wi-Fi / HTTPS
       ┌──────────▼───┐     ▼
       │ ESP32-C5     │  Ubuntu AI server
       │ Kitty face   │  Open WebUI realtime
       │ animations   │  snapshot receiver
       │ buttons / BLE│  semantic services
       └──────────────┘     │
                            └── read-only finalized
                                SD snapshot copies
```

The **microSD in the S3** is the durable source of truth for Kitty's archived memories. Ubuntu receives finalized snapshots and builds retrieval indexes; it must not silently become an alternate private-memory authority. The iPhone app configures and manages the companion through supported device interfaces. It does **not** act as the voice-chat client or automatically approve shareable memories.

### Memory and privacy model

1. **Conversation archive:** completed conversation turns are appended to the S3 SD archive, even if the current voice is unknown.
2. **Approved shared notes:** only explicitly approved non-secret entries in `/kitty/shareable_memories_v6.tsv` become global cross-call conversational context. Test entry: “Kitty's favorite imaginary planet is Mochi Planet.”
3. **Speaker-scoped data:** user-specific claims and semantic recall are kept separate. A *voice candidate* or spoken self-introduction is **not** an authenticated owner identity.
4. **Current limitation:** automatic summarization of unverified conversations is now validated on the S3, but those summaries are intentionally **not** copied to global owner context. Private later-call recall and ongoing same-call context require independently trusted owner/speaker binding; the optional bounded rolling-context helper is not connected to the deployed gateway.

## Hardware at a glance

| Component | Purpose |
| --- | --- |
| Freenove ESP32-S3-WROOM CAM N16R8 | Brain, Wi-Fi, microSD, camera, audio orchestration |
| LILYGO T-Display-C5 (ESP32-C5) | Horizontal Kitty face, expressions, buttons, BLE |
| INMP441 I²S microphone | Speech input on S3 |
| MAX98357A I²S amplifier and speaker | Speech playback on S3 |
| Ubuntu host | Realtime/Open WebUI integration, read-only snapshot receiver and semantic indexing |

**Current S3 audio/UART wiring:** I²S BCLK GPIO41, WS GPIO42, microphone data GPIO1, amplifier data GPIO2; UART S3 TX GPIO47 → C5 RX GPIO1, C5 TX GPIO6 → S3 RX GPIO21, 921600 baud. Confirm exact hardware pin labels and power before wiring. See [breadboard drawing](docs/hardware/cutedisplay-s3-c5-breadboard.svg) and [hardware notes](docs/hardware/s3-c5-breadboard-plan.md).

## Repository map

- `firmware/CuteDisplayBrain/` — S3 brain, realtime calls, audio, memory, SD sync, OTA.
- `firmware/CuteDisplay/` — C5 screen and device control.
- `server/` — Ubuntu memory service, snapshot receiver, semantic/voice tools, tests, guarded gateway patch scripts.
- `ios/CuteDisplay/` — iPhone setup and management app.
- `docs/` — wiring, validation, deployment notes and historical checkpoints.
- `.github/workflows/` — build/test automation.

## Working deployment and safe updates

**S3 Arduino:** ESP32 Arduino core **3.3.12**, **16 MB flash**, **OPI PSRAM**, **Custom partition scheme**. Retain the existing correct `partitions.csv` and private settings; **do not erase all flash, format microSD, or flash the C5 sketch onto S3**. Normal source checkout may include an intentionally empty generated C5 image header—use the supported combined firmware workflow for OTA packaging.

**C5:** keep the hardware-validated v38 release unless explicitly preparing a tested upgrade. Existing UART OTA is separate from the S3 build and does not imply a C5 update is bundled.

**Ubuntu:** the user service `kitty-memory-v6.service` runs `~/kitty-v6/CuteDisplay/server/kitty_memory_service.py` with settings in a **private** `~/kitty-v6/private/memory-service.env`. The working realtime Open WebUI route has additional host bind-mounted patches in `~/kitty-v6/private/semantic-gateway/realtime.py`. GitHub tracks patch **scripts**, but it does **not** automatically export those deployed private runtime files. Read the [deployment and handoff guide](docs/KITTY_V6_CURRENT_HANDOFF_2026-11-01.md) before changing them.

**Voice-candidate threshold:** Ubuntu's active files currently use the locally tested candidate threshold **0.960**. GitHub `main` now represents that conversational threshold using `conversational_hint=True`, while retaining a stricter **0.965 minimum** for experimental identity matching. The two active Ubuntu files still use the older coupled check; see the [deployment audit](docs/KITTY_V6_CURRENT_HANDOFF_2026-11-01.md). Candidate-only matching never authorizes private-memory access. The host's patched gateway route and private environment are intentionally not published.

## Next improvement

Continue making **long conversations reliable regardless of voice identity** (the initial isolated-summary and session-batching source patches are merged, but end-to-end recall remains unfinished): always preserve complete turns, create bounded **conversation-scoped** summaries even when speaker is unverified, retrieve those summaries during the same call, and keep private owner facts protected. Scope/context must not leak to other callers or calls. Avoid disruptions to the validated realtime audio path.

**Start here:** [Kitty V6 current status + next-chat handoff](docs/KITTY_V6_CURRENT_HANDOFF_2026-11-01.md).

## Documentation

- [Current project handoff (2026-11-01)](docs/KITTY_V6_CURRENT_HANDOFF_2026-11-01.md)
- [Earlier V6 handoff](docs/KITTY_V6_HANDOFF_2026-11-01.md)
- [MicroSD sync and recall notes](docs/KITTY_SEMANTIC_V6_SYNC_AND_RECALL_2026-10-30.md)
- [Historical README and prior build notes](docs/README_HISTORY_THROUGH_2026-11-01.md)

**Safety:** Never commit private Wi-Fi credentials, API keys, tokens, owner voice samples, microSD memory snapshots, or personal memory datasets.
