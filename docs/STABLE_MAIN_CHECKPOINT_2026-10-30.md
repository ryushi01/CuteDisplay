# CuteDisplay — stable configuration and promotion checkpoint (2026-10-30)

This checkpoint records the **user-tested Open WebUI/Ollama chat performance configuration**, plus the status of the broader CuteDisplay repository when promoting the feature line to `main`. It supplements [validated hardware checkpoint](VALIDATED_SYSTEM_CHECKPOINT_2026-10-29.md) and does not supersede its unresolved issues.

## Topology
- ESP32-S3 brain + LILYGO T-Display-C5 Kitty face; S3 microSD is canonical persistent memory.
- Ubuntu `ai-server` runs the Open WebUI/realtime gateway.
- Open WebUI uses **Mac-hosted Ollama**, model `qwen3.5:9b`. Do not confuse this with any Ollama server installed on Ubuntu.
- A separate Mac realtime speech application can call the Mac Ollama OpenAI-compatible endpoint directly, independently of Open WebUI's model-level parameters.
- No live server, Mac service, device, secrets or microSD files are modified by this GitHub documentation/promotion.

## User-tested model settings (2026-10-30)
| Setting | Effective / selected value | Notes |
| --- | --- | --- |
| Open WebUI model | `qwen3.5:9b` | Mac Ollama backend |
| Open WebUI model `num_ctx (Ollama)` | **16384 (16K)** | Explicit override for this model's Open WebUI requests |
| Ollama Mac app default context | **65536 (64K)** | Applies to calls that do not provide a request-specific override |
| Temperature | **0.7** | Preserve conversational personality |
| top_p | **0.9** | Retain existing model setting |
| Think | **disabled** | Preserve responsiveness |
| Persona | unchanged | Multilingual Japanese/English/French Kitty-chan オネエ voice |
| Keep-alive observed | approximately 30 min | `ollama ps` showed model resident; verify actual per-request options for other clients |

The user initially changed Open WebUI from 4096 to 32768, experienced slow responses, and then settled on **16384**. After a fresh session/warm-up, Open WebUI chat became fast again and the user explicitly confirmed it works well. Do **not** attribute the transient slowness exclusively to context size: prompt/history processing, startup and caching were not independently benchmarked. A new chat and a long historical chat may behave differently.

## Reproduced Mac diagnostic readings
- `ollama ps`: `qwen3.5:9b`, **7.7 GB**, **100% GPU**, **CONTEXT 16384**, **runner mlx**, ~29-minute remaining residency.
- `GET http://127.0.0.1:11434/api/ps`: `context_length: 16384`, `runner: mlx`, `size_vram: 8759736808`.
- Direct `POST /api/chat` using a simple 22-token French user message, `think:false`, `num_ctx:16384`, `num_predict:80`: total **2.52 s**, load **0.05 s**, prompt evaluation **0.15 s**, generation **0.57 s** for **14 output tokens** (**24.7 tok/s**).
- This benchmark is a **short direct Ollama request**, not an Open WebUI end-to-end latency benchmark. It confirms good warm GPU inference but does not benchmark long prompts or realtime audio.
- Mac sample after unloading prior large-context model: **24 GB** physical RAM in use, **7424 MB** unused, **5154 MB** compressed, swap **3515.75 MB** used; these figures are point-in-time, not requirements.

## How to verify and troubleshoot
1. Check the selected Kitty model in Open WebUI > Workspace > Models > Parameters; `num_ctx (Ollama)=16384`. Check other global/chat parameter overrides if behavior differs.
2. Send a brief message in a new Open WebUI chat, then on Mac run `ollama ps`; confirm `CONTEXT 16384` and `100% GPU`. `ollama ps` is empty when no model is resident.
3. If slow, compare a new chat with an established long chat before changing more variables. Large actual prompts can take longer even with a fixed 16K limit.
4. To isolate Ollama backend from gateway overhead, benchmark a short `/api/chat` call with `num_ctx:16384`, `think:false` and inspect `total_duration`, `load_duration`, `prompt_eval_duration`, `eval_duration`, `prompt_eval_count`, `eval_count`.
5. The Mac's separate speech service can use another context value; do not assume Open WebUI's override governs that client.
6. Keep persona/temperature unchanged. A context cap is **not** Kitty's persistent memory store; reboot-safe facts/conversation archives live on S3 microSD.

## What “stable main” means here
- The user validated their currently running Kitty conversational setup and the above Open WebUI chat behavior, and requested promotion of the feature branch to `main`.
- Source carried over includes iterative SD memory, realtime audio/memory refresh and diagnostic changes. **Do not interpret the branch promotion as independent CI, device flash, memory retention, or live-server deployment validation of every individual commit.**
- `docs/KITTY_MEMORY_V5_ROLLOUT.md` documents **optional/not-yet-deployed** semantic indexing and calendar services. Their integration, runtime validation and security checks remain future work even though the source is tracked on `main`.
- Known realtime issues from earlier testing, including provider request rejection, occasional microphone queue drops, and heuristic memory extraction limitations, are retained as investigation history; do not claim they were individually regression-tested away.
- The previous feature branch and dated checkpoints remain useful rollback references. Never erase the microSD or change production Ubuntu Docker image as part of a repository-only promotion.

## Next development policy
Start future risky changes in a new feature branch, keep `main` as this accepted baseline, and promote changes after focused hardware/server testing. Confirm build artifacts and staged deploy steps before any firmware flash or server upgrade.
