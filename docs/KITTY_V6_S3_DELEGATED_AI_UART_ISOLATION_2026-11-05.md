# Kitty V6 — S3 delegated AI UART isolation candidate (2026-11-05)

## Operator-confirmed v41 evidence

During a working realtime Call Mode conversation, the S3 returned delegated chat HTTP=200 with transport=0, yet intermittently printed `[AI] UART ACK timeout` and `[AI] Stream ended with an error`. The S3 UART diagnostic was `ack_ok=50 ignored_ack=0 retransmits=32 timeouts=8 pending=0`. One successful request had `Generated UART bytes=324 acked=129`; a failed request had `Generated UART bytes=638 acked=77`. C5 continued sending `ACK AI`, with LCD/BLE/Wi-Fi all reporting 1. The v40 `NACK CALL_ACTIVE` signature did **not** recur.

The same call had `mic_drops=0`, `speaker_dropped_ms=0` and recorded audio task stack free ~6164 bytes. S3 internal heap reached ~49–52 KB during concurrent TLS, with boot-lifetime min ~33 KB and largest internal block ~31 KB. Speaker underruns are counted when `remoteReply` is true but the local speaker ring has no next frame; this includes remote waits, so the accumulated count alone does not prove audible glitches.

## Memory conclusion

After the call, idle automatic summarization returned `HTTP=200 accepted=1 summary_stage=6`; SD printed `summary persisted ack_offset=4929`, up from 4792. `ai_http_paused=0`, `ai_enabled=1`, and no backpressure. It works automatically **after calls** and preserves unverified summaries separately; it is not verified owner memory or actual live in-call rolling summary. Do not bypass the owner boundary.

## Narrow S3-only fix candidate

In `firmware/CuteDisplayBrain/BrainAI.h`, the delegated realtime call already receives model SSE deltas into `liveTextQueue` (C5 full-screen `CALL_TEXT`) and `currentAnswer` (tool result). However it also emitted redundant background `AI_BEGIN` / `AI_DATA` / `AI_END` frames to the hidden legacy C5 bubble. A lost ACK could therefore fail a perfectly valid HTTP=200 delegated reply. New source gates **only those legacy packets** to non-delegated standalone chat. It preserves call caption stream, tool answer, S3 audio, C5 v41 animation/buttons/BLE, SD/voice-private data, and all standalone AI UART packets.

This is a **source candidate**, not a deployed fix. It cannot correct all possible UART/wiring errors and has not yet passed a physical firmware test. Keep v41 `main` and `stable/2026-11-05-s3-c5-v41-hardware-confirmed` as recoverable baselines. Use the existing private `tools/build_s3_only_v6.sh` to compile one S3-only candidate off GitHub (never publish `KittySyncPrivateConfig.h` or generated binaries). Test static regression before compile. Do not update the C5 firmware or erase NVS or microSD.

## Remaining checks

Once the S3-only candidate is flashed deliberately, make one normal call including a delegated tool request; compare `[SYS UART AI]` counters before/after the call. No new `AI_BEGIN`/`AI_DATA` packets should be generated for delegated calls, while full-screen captions and spoken answer remain available and ordinary standalone chat remains unchanged. Keep testing private owner attestation and long-call continuity separately; neither is completed by this patch.
