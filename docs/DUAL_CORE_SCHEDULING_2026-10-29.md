# Dual-core scheduling update (experimental)

Base checkpoint: `checkpoint/2026-10-29-semantic-memory` at `28c1982dfb1c2cf97023fe93bcdee06a6ed39db0`. Prior PSRAM checkpoint: `checkpoint/2026-10-29-memory-psram`. Validated `main` is untouched.

## Implemented
- Keep existing pinned realtime I2S worker on Core 0 at priority 3, memory/AI workers on Core 0 at priority 1, and Arduino loop and realtime WebSocket/C5 coordination on Core 1. No risky repinning or priority inversion.
- During indexed SD scans yield every 256 inspected entries, including candidates filtered out for an unrelated topic. Previously the yield was conditional on successful topic matching and could skip yields for most rows. This prevents long noncooperative low-priority loops on Core 0.
- Add `[SYS TASKS]` stack-high-water diagnostics to `system status` for pinned audio, SD, and AI tasks. Zero means task not present; it is not a CPU-utilization reading.
- Do not modify I2S DMA buffers, WebSocket behavior, CPU affinity, or Open WebUI server.

## Validate
1. Compile the combined S3/C5 workflow on this feature branch.
2. Run `system status` idle and during a call; check audio stack-free, internal heap/PSRAM headroom, and reset reasons.
3. Search an unrelated conversation topic with a large SD archive while a call is active; check mic drops, speaker drops, and first response latency against the saved checkpoint.
4. Confirm English/French/Japanese recall and reboot-persistent facts.
5. Roll back to the saved checkpoint without erase-all-flash if any regressions occur.

Note: This is a targeted cooperative scheduling update, not proof of improved dual-core CPU utilization. Per-core percentages would require carefully calibrated idle/runtime measurements and are not fabricated.
