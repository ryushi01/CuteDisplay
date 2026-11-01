# Kitty centralized releases — V6 rollout contract

Status: design approved; update controller is NOT deployed. Do not treat this
document as authorization to change live machines.

## One control point

Ubuntu ai-server is the release controller and status dashboard. GitHub is
the source repository, not the source of runtime secrets. A release consists
of an immutable, versioned manifest (including minimum compatible versions,
exact artifact SHA-256, signature, rollback reference and per-component
health checks), with independently deployable components:
- ESP32-S3: OTA image with A/B slot and boot-confirmation health checks
- LILYGO C5: tested C5 image forwarded through existing S3/C5 update path
- Ubuntu: service versions in a staged deployment, restarted individually
- Mac: independently installed, authenticated agent for TTS/Ollama integration
  (model downloads remain separate and opt-in)

## Safety invariants

1. Manual approval by default; no auto-flash and no auto-install of models.
2. S3/C5 compatibility checked before either image is activated; order is
   controlled by manifest and actual bootloader/updater capabilities.
3. Read-only inventory, preflight, backup, staging, signature validation,
   deployment, and post-deploy health checks are separate observable states.
4. Stop on failed health checks. Do not automatically claim rollback success;
   verify it, and document components without atomic rollback support.
5. MicroSD memory and voice profiles are canonical, never formatted, migrated
   destructively, or overwritten by firmware updates. Encrypted backups of
   device data must be verified before an update involving storage changes.
6. Device tokens, signing keys, macOS credentials and TLS private keys never
   enter GitHub or an update bundle. Provision them separately.
7. CPU speech and real-time conversation must not block on updates. Defer
   transfer/reboots when in an active call or when power/network is unstable.
8. Each component reports its installed, staged, and healthy release ID.
9. Restartable sync and partial update recovery are mandatory.
10. Do not bind a device-facing update endpoint until authentication and
    verified HTTPS (including certificate rotation) are implemented/tested.

## Current baseline (2026-10-30)

Ubuntu user services kitty-memory-v6, kitty-voice-v6 and
kitty-sync-gateway-v6 active, enabled and bound to localhost. Arduino CLI
1.5.1 and esp32 core 3.3.7 installed for compilation. No ESP32/S3-to-Ubuntu
snapshot sender, voice-profile return path, Mac update agent or centralized
updater is deployed yet. Existing C5 OTA mechanism requires compatibility
verification before releasing combined images.

## Proposed implementation sequence

1. Capture baseline compile with explicit Arduino dependencies, pin versions.
2. Implement/test SD snapshot sender with verified HTTPS, no realtime I/O.
3. Implement secure speaker enrollment and profile return to S3 microSD.
4. Introduce signed release manifest and preflight/status-only CLI on Ubuntu.
5. Implement S3/C5 staged OTA, health confirmation and verified rollback.
6. Add opt-in Mac agent with narrow permissions and verified service health.
7. Add a local authenticated UI that invokes tested update transactions.
8. Test interrupted transfers, failed boots, offline Mac, token rotation,
   storage integrity, and downgrade/rollback paths before rollout.


## Locked ESP32-S3 N16R8 Arduino build profile (validated baseline)

- Arduino CLI 1.5.1; ESP32 Arduino platform esp32:esp32 3.3.7.
- Board FQBN esp32:esp32:esp32s3.
- FlashSize=16M, PSRAM=opi, PartitionScheme=app3M_fat9M_16MB.
- USB CDC on boot: CDCOnBoot=cdc.
- Arduino task core: LoopCore=1.
- Event task core: EventsCore=0.
- CPUFreq=240.
- Pin the entire FQBN in the release build script, not interactive IDE settings.
- The partition has TWO OTA app slots, each 0x300000 bytes, app0 at
  0x10000 and app1 at 0x310000. This was confirmed from the installed
  Espressif 3.3.7 partition CSV on ai-server on 2026-10-30.
- Baseline binary 1,781,120 bytes; 56 percent of available app slot,
  compiled before adding device sync. Preserve microSD as canonical memory.
- Verify actual USB CDC and CPU menu IDs in the installed board definition;
  if the FQBN flags differ, correct the build profile instead of quietly
  omitting flags. OTA image is app .bin, NEVER the 16 MB merged factory image.
