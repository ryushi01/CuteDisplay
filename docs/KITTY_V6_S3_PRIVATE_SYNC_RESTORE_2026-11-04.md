# Kitty V6 — S3 private snapshot sync recovery (2026-11-04)

## Live observations (operator confirmed)

- Open WebUI `running healthy`; `kitty-memory-v6.service` and `kitty-sync-gateway-v6.service` active.
- Ubuntu latest finalized S3-derived snapshot is ~66 hours old. It includes nonempty conversation archive and explicitly approved shared notes, but the exported facts/plans/summaries are empty; the derived semantic index has 259 rows, all with attribution metadata (not necessarily verified owner identities).
- Physical S3 USB: `[MEMSYNC] configured=0 running=0 completed=0 failures=0 sd_ready=1 wifi=1`, and no bytes/HTTP activity. This is a **disabled sender**, not an HTTP failure.
- Physical S3 USB: `[MEMORY V6] sd=1 active_call=0 job_ack_offset=4146 awaiting=0 summary_queue=0 results_queue=0 backpressure=0 ai_running=0 ai_pending=0 ai_http_paused=0 ai_enabled=1`. Earlier accepted hardware result showed `accepted=1` and ACK 2878; the ack cursor has advanced and there is currently no backlog. This is not proof that owner-private summaries are available.
- Current S3 source routes unverified AI summaries into `unverified_summaries_v6.tsv`, intentionally excluded from the nine-file snapshot export. Never reclassify these as owner-verified history.

## Confirmed cause and limit

`firmware/CuteDisplayBrain/KittyMemorySyncV6.h` uses `KittySyncPrivateConfig.h` if present at **compile time**; otherwise `KITTY_SYNC_V6_URL`, `KITTY_SYNC_V6_DEVICE_TOKEN` and `KITTY_SYNC_V6_CA_PEM` default to empty strings. The `configured()` guard requires the exact `https://ragnarok-project.com/kitty-v6/sync` endpoint, an at-least-32-character device token and a PEM CA certificate. The worker is created only when this guard passes during S3 startup. Therefore a running image with `configured=0` cannot be fixed by restarting Ubuntu or modifying environment variables there. The current binary either lacks the private header or contains values the guard rejects. No evidence of data loss, broken microSD or failed Ubuntu service.

## Code-only preparation committed to GitHub main

- `tools/build_s3_only_v6.sh` accepts `KITTY_SYNC_PRIVATE_HEADER` **only for trusted local builds**, validates the three expected literal macros without printing their values, refuses the private input under GitHub Actions/CI, prevents writing credential-bearing outputs inside the Git checkout, and creates a private application binary and Arduino IDE sketch in a new local output directory. Files and directories have restricted permissions.
- The builder removes any inherited header copied from an unreviewed source checkout. It requires an **empty C5 image placeholder**, so an S3-only upload cannot automatically update the running C5 v38. The public CI build intentionally contains no private sync credentials.
- `server/test_kitty_private_s3_only_build_v6.py` runs the actual packaging shell with a fake compiler, testing private output, credentials excluded from logs, no C5 payload, CI refusal, invalid/missing config refusal, and safe public builds. It is part of the existing firmware CI.
- `.gitignore` excludes local `KittySyncPrivateConfig.h` files and generated firmware directories; **do not rely on .gitignore alone** to protect generated binaries outside the checkout.
- The existing `tools/prepare_kitty_sync_v6.py` can generate a private header from a **local** device bearer-token file and a public CA certificate file. Never paste these secret contents into ChatGPT or GitHub.

## Trusted Mac build procedure — prepare only, do not flash yet

Use a current trusted local checkout of CuteDisplay on the Mac with Arduino-ESP32 3.3.12, Arduino CLI, required libraries, and the correct **private** `KittySyncPrivateConfig.h` created or recovered from the original setup. Do not download a public CI firmware and expect it to contain credentials.

```bash
cd /path/to/trusted/CuteDisplay
git fetch origin main
# Ensure the working tree is on the intended reviewed version before compiling.
# Example, after reviewing local changes: git pull --ff-only origin main
KITTY_SYNC_PRIVATE_HEADER="$HOME/path/to/private/KittySyncPrivateConfig.h" \
  bash tools/build_s3_only_v6.sh
```

The private output is created under `$HOME/.local/share/kitty-v6/private-builds/` by default and contains `S3-Brain-application.bin`, `SHA256SUMS.txt`, `README.txt`, and a complete private `CuteDisplayBrain` Arduino IDE sketch. The directory is **sensitive**: it embeds a device bearer credential in the binary and private header. Do not publish, attach, or upload it to GitHub; do not compile it on public CI.

The build does **not** upload or flash either device. When deciding to flash later, use the generated **S3-only Arduino sketch**, the verified current partition settings, preserved NVS and microSD, and verify a rollback path for the previous working image. **Do not flash an application-only .bin at offset `0x0`**, and do not use the combined S3+C5 v39 build for a sync-only repair. After a deliberate S3-only flash, check `memory sync status`: expect `configured=1 running=1`, then allow a finalized snapshot. Verify Ubuntu snapshot recency and indexed generation without reading private contents. Record any failure stage and HTTP status; never share tokens/certs.

## Separate release gates

Re-enabling snapshot sync does not enable private owner recall. Independently trusted per-turn speaker attestation, protected owner grants, and correct context injection must still be integrated before Kitty can safely recall owner-private previous-day conversations. Preserve C5 v38, the working gateway observer and SD authority throughout.
