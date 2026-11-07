# Kitty V6 — authenticated gateway event provenance gate (2026-11-07)

## Scope

Built on main `92a80e7` (PR #23). Source only. Working public/shared recall, realtime voice, Mac AI/TTS, Open WebUI bind-mounted realtime.py, S3/C5, iPhone and SD archives are not modified or deployed. Owner-private recall stays disabled.

## Separate trusted event sources

`server/kitty_owner_gateway_event_gate_v6.py` provides `ProviderTranscriptEvidence` (bounded RAM-only store) and `OwnerGatewayEventGate` (per-call trusted event router). The future gateway must instantiate **distinct** authenticated provider and S3 WebSocket handle objects and pass only the real, server-held connection objects to these components. Neither a source string nor a socket identifier in JSON can substitute for those objects.

- `from_provider(channel,event)` only accepts `conversation.item.input_audio_transcription.completed` from the actual provider socket. It records a final item transcript once, using the same <=255-byte clean UTF-8 limit as the S3 archive and routes item ID to the async voice/ACK bridge. Repeated/malformed provider items invalidate pending evidence.
- `from_s3(channel,event)` only accepts `kitty.memory.owner_archive.ack` as a positive event from the exact original S3 socket. Device speaker claims, client owner grants, stated names and probable scores are always inert. Device cancellation events invalidate the current evidence.
- An ACK may arrive before or after CPU voice proof completion (but only after the provider item has been observed). Neither event alone proves owner status. A trusted S3 microphone capture and separate pinned owner model must still provide an exact audio-bound turn ticket; only the signed S3 receipt is delivered back via the authenticated device socket.
- After a signed receipt is appended to microSD, the derived Ubuntu index must verify a later finalized SD snapshot against the exact offset, transcript digest, row SHA-256 and receipt HMAC. The RAM store itself neither persists owner facts nor grants private semantic recall.
- On errors, interrupts and disconnect, pending transcripts are erased; item tombstones remain until the call ends so replayed provider item IDs cannot regain trust.

## Read-only deployed gateway preflight

`server/kitty_owner_gateway_preflight_v6.py` reads only the known private `realtime.py` path and emits closed-category AST shape statuses. It does not reveal source, paths, hashes, transcript text or secrets and makes no modification. It is self-contained, so it can run inside the existing Open WebUI container without importing GitHub helpers.

Run from the existing Ubuntu clone after fetching main:

```bash
cd "$HOME/kitty-v6/private/kitty-sync-deployment/live-sync-build"
git fetch origin main
git show origin/main:server/kitty_owner_gateway_preflight_v6.py | sudo docker exec -i open-webui python3 -
```

`provider_decode_scope=candidate`, `s3_device_receive_scope=candidate` and `common_route_scope=candidate` are **structural clues only**, not authorization or rollout permission. `authenticated_s3_device`, `provider_to_s3_item_binding`, `trusted_s3_microphone_capture`, `owner_model_calibrated` and `receipt_sd_write_confirmed` intentionally remain `not_verified`. `deployment_ready=no` and `live_owner_private_recall=no` are unconditional. If any shape is ambiguous, leave everything disabled and inspect the gateway privately without pasting secrets.

## Remaining work

1. Run the read-only preflight on the actual Ubuntu Docker bind mount and compare its closed-vocabulary statuses to the documented source topology.
2. Confirm that the S3 device WebSocket is authenticated independently of browser/phone messages and that provider turn IDs and original microphone capture truly correlate. The gateway must supply a **trusted** `capture_lookup`, pinned owner profile and genuine CPU scorer; these are not implemented by the event gate.
3. Validate owner/guest/overlap/replay/voice-clone impostor scores on real microphone audio; no one-call approval is requested, but voice-only biometric authorization carries residual spoof risk.
4. Prepare an exact AST-guarded, **disabled-by-default**, rollback-tested gateway patch. Check deployed snapshot receiver understands the optional tenth `owner_turn_receipts_v6.tsv`, then verify actual S3 ACK latency and SD receipt writing before any consolidated firmware flash.

Source tests: `server/test_kitty_owner_gateway_event_gate_v6.py`, `server/test_kitty_owner_gateway_preflight_v6.py`. Both are included in the focused privacy CI. The original normal voice relay and public-memory path are intentionally independent of these modules.
