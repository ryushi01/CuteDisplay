# Kitty V6 — asynchronous owner SD receipt bridge (2026-11-07)

## Baseline and status

Continue merged PR #22, baseline `d037e9f`. **Source only**: the working Ubuntu Open WebUI realtime voice route, approved shared recall, Mac AI/TTS, S3 memory, C5 firmware and iPhone setup are unchanged.

## Internal gateway design

The new `server/kitty_owner_receipt_async_bridge_v6.py` is an opt-in `AsyncOwnerReceiptBridge` for one independently authenticated S3 socket, one gateway-created call ID and one `VoiceOwnerIssuer`. It composes earlier voice issuer, archive ACK correlation and early-sign/late-verify receipt components, without adding HTTP endpoints or touching voice forwarding.

- `begin_call()` yields an optional capability message only after issuer policy, owner consent and S3 socket validation; the real gateway must choose whether to send it. The capability never unlocks private recall.
- `on_provider_completed(item_id)` MUST be called only from the authenticated upstream provider receive loop. It schedules bounded background voice scoring, retrieving trusted S3 microphone audio and transcript through the issuer. A separate gateway-internal lookup supplies the exact final provider transcript and is matched cryptographically. Do not pass client, S3 claim, or model-generated transcripts.
- `on_authenticated_s3_ack(channel,event)` MUST be called only from the authenticated S3 device receive loop with the actual connection object. A bounded ACK buffer handles arrival before or after CPU voice scoring. Duplicate ACKs/items, invalid fields, mismatched sockets and unknown provider items are denied.
- A qualifying fresh, audio-bound owner turn and authenticated ACK mint only an opaque signed receipt. The supplied `send_to_s3` callback uses the existing S3 websocket and is limited to 0.8 seconds, with no retries after ambiguous delivery. No raw audio, owner memory, key or transcript is persisted on Ubuntu.
- Later, an immutable original S3 SD snapshot must match the exact archived row offset, SHA-256, transcript digest and HMAC. Only the verified derived index may label it owner. A signed ACK alone never authorizes disclosure.

## Cancellation and nonblocking behavior

The issuer now checks an interruption generation before using results from background CPU scoring. Guest turns, cancellation, overlap, playback, unknown speaker, revocation or disconnect must call `interrupted()` or `close()` at the trusted gateway call site. Old high-confidence scores cannot repopulate trust. The voice queue holds at most four items; early ACKs at most eight; CPU timeout is four seconds. When these bounds fail, only the optional private owner receipt capability fails; normal audio does not depend on it.

## Tests and deployment barrier

`server/test_kitty_owner_receipt_async_bridge_v6.py` exercises both event orders, original SD verification, wrong socket, candidate/guest identity denial, transcript mismatch, cancellation during inference, a late score after interruption, consent revocation, one-use ACKs, CPU timeout and slow sending. Included in focused GitHub CI.

**Not deployed:** No production gateway callback, real microphone capture binding, model calibration, SD writer confirmation, firmware flash or owner-private recall enablement. Before rollout, validate the actual private bind-mounted Open WebUI provider and S3 device receive scopes using the read-only preflight, test the optional tenth SD snapshot receiver, verify owner-versus-guest/replay/voice-clone scores, and prepare a rollback-tested disabled-by-default gateway hook. S3 microSD remains the sole durable owner memory authority.
