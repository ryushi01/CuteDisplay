# CuteDisplay: native Realtime on the SAME Open WebUI server

**Status:** The C5 v22 short-tap Call Mode toggle and S3 direct WSS status client compile; audio I2S full conversation is not yet enabled. The Open WebUI server patch is prepared, not deployed. Never paste a human password, 2FA code, API key, or Docker secrets into chats or Git.

## Auth: no password/2FA on S3

Open WebUI's current `/api/v1/audio/realtime` WSS route accepts user-session JWTs only. This opt-in server source patch adds Open WebUI's existing `sk-` API-key auth *to that same WebSocket endpoint* while preserving its `chat.call`, model-access, API-key permission and endpoint-allowlist checks. Keys are revalidated every minute. The S3 uses its existing HTTPS Open WebUI URL, `cutedisplay-ai` model and revocable API key, provisioned once by the iPhone via encrypted BLE; credentials survive reboot in S3 Preferences. No extra gateway host, URL, port, microphone server, or session login.

## Step 1 — build a replacement image WITHOUT changing the running server

**WHERE: Ubuntu VM with your existing Docker Open WebUI container**

```bash
set -e
if [ -d "$HOME/CuteDisplay-realtime-server/.git" ]; then
  git -C "$HOME/CuteDisplay-realtime-server" switch feature/realtime-call-c5v21
  git -C "$HOME/CuteDisplay-realtime-server" pull --ff-only
else
  git clone --branch feature/realtime-call-c5v21 --single-branch \
    https://github.com/ryushi01/CuteDisplay.git "$HOME/CuteDisplay-realtime-server"
fi
cd "$HOME/CuteDisplay-realtime-server"

# The ryushi account may not be in the Docker socket-access group.
# Use sudo for Docker rather than modifying root-equivalent group memberships.
# Fail fast on ANY error. The server container remains running.
bash <<'BUILD_CANDIDATE'
set -euo pipefail
sudo docker info >/dev/null
RUNNING_IMAGE_ID="$(sudo docker inspect open-webui --format '{{.Image}}')"
RUNNING_USER="$(sudo docker inspect open-webui --format '{{.Config.User}}')"
[ -n "$RUNNING_USER" ] || RUNNING_USER='0:0'
sudo docker image tag "$RUNNING_IMAGE_ID" cutedisplay/openwebui-existing:backup

# This builds a NEW image only. No service restart, DB change or deployment.
sudo docker build -f server/Dockerfile.openwebui-realtime-apikey \
  --build-arg BASE_IMAGE=cutedisplay/openwebui-existing:backup \
  --build-arg ORIGINAL_USER="$RUNNING_USER" \
  -t cutedisplay/openwebui:realtime-apikey-candidate .

sudo docker image inspect cutedisplay/openwebui:realtime-apikey-candidate \
  --format 'PATCH_IMAGE_BUILT_AND_VERIFIED: {{.Id}}'
BUILD_CANDIDATE
```

A command that merely prints `BUILD COMPLETE` does **not** prove Docker succeeded. Only the final `PATCH_IMAGE_BUILT_AND_VERIFIED` line from the guarded block means the image was created. The source patch runs a strict source-version check; Docker build **fails** if the installed Open WebUI Python module has changed incompatibly. At this point the running container is **not** touched, users' chats and settings remain available, and the original image has a local backup tag.

## Step 1.5 — existing Compose safety checks and deployment

The original Ubuntu `ryushi` account needs `sudo` to access Docker. A previous `--deploy` attempt failed during the **pre-stop** snapshot setup: `sudo install` created `docker-compose.yaml` owned by root and unprivileged `chmod` then failed. This caused **no service restart, no volume backup and no container replacement**. That ownership mistake is fixed; a CI regression test now reproduces it before release. The deployment script also explicitly sets the Compose project working directory to `/home/ryushi` so existing `.env` interpolation remains consistent.

```bash
cd "$HOME/CuteDisplay-realtime-server"
git switch feature/realtime-call-c5v21
git pull --ff-only
sudo docker inspect open-webui --format 'Open WebUI currently: {{.State.Status}}'
bash server/deploy_existing_openwebui.sh --check
# This step briefly stops ONLY Open WebUI for a consistent data backup.
bash server/deploy_existing_openwebui.sh --deploy
```

Only proceed with deployment if `--check` passes. The script preserves the original image and volume and attempts automatic rollback if the candidate fails its health test. A successful deployment prints `PASS: candidate image active and original /health responding.` and a private backup/rollback directory.

### Compose volume-name correction (second safe pre-stop failure)

A second attempt failed an assertion **before the script stops Open WebUI**. In the original Compose config, the logical volume alias resolves to the real Docker volume `open-webui`; the secondary candidate validation had incorrectly compared the alias to the physical name. `server/check_openwebui_compose_config.py` now validates the effective volume name, port 8080 and image for **both original and override Compose**. Regression tests cover a logical name differing from the actual physical volume name, and `--check` now also verifies the candidate override, before any deployment is attempted. This failure did not modify the running server; the incomplete backup folders from preflight failures contain no database snapshots and should not be used for restoration.

After pulling the latest development branch, run `bash server/deploy_existing_openwebui.sh --check` and verify **both original and candidate** configuration passes before executing `--deploy`. The `--deploy` command will stop Open WebUI briefly to back up its persistent volume.

## Verified backup before deployment (revised after truncated archive)

On 2026-10-28, the original long offline `tar -czf` process ended before writing a gzip trailer. Its output `/home/ryushi/openwebui-rollback-aq21l830/openwebui-data.tar.gz` is **CORRUPT**, confirmed by `gzip: unexpected end of file`, and must never be used for restoration. The original Open WebUI container recovered, passed Docker health, and served HTTP `200` at `/health`. The corrupted archive cannot itself damage the original Docker volume.

**The old combined `--deploy` backup process is retired.** Use the new standalone script instead. It first pre-copies data while Open WebUI remains online, briefly stops ONLY Open WebUI for a consistent rsync delta (including SQLite/WAL), restarts the original app, then creates and validates the gzip archive while Open WebUI is ONLINE. It writes only `.partial` files until full gzip, tar and SHA256 checks pass; it creates `BACKUP_VERIFIED` only at the end.

```bash
cd "$HOME/CuteDisplay-realtime-server"
git switch feature/realtime-call-c5v21
git pull --ff-only

# Do not continue if the original service is not healthy.
sudo docker inspect open-webui --format 'Status: {{.State.Status}}, Image: {{.Config.Image}}'
curl -fsS --max-time 10 http://127.0.0.1:8080/health

# Backup only: creates no replacement image, changes no Compose config.
# Requires rsync. Keep the SSH session open, or use an existing tmux session.
command -v rsync
bash server/create_verified_openwebui_backup.sh --backup
```

The only valid success marker is `BACKUP VERIFIED: /home/ryushi/openwebui-verified-.../openwebui-data.tar.gz`. If SSH disconnects during compression, the original app has already restarted; an abandoned `.partial` archive is NOT a valid backup.

**Do not deploy until the independent backup succeeds.** The corrected deployment command now requires the just-verified backup directory and refuses a missing, corrupt, or older-than-six-hours archive:

```bash
# EXAMPLE ONLY — replace with the exact fresh directory printed above:
bash server/deploy_existing_openwebui.sh --check
bash server/deploy_existing_openwebui.sh --deploy /home/ryushi/openwebui-verified-XXXXXXXX
```

Never supply the older `openwebui-rollback-aq21l830` directory. The deployment rechecks the checksum, gzip trailer and archived manifest BEFORE stopping the original app.

## Step 2 — controlled deployment, not automatic

Before switching Compose/container to the new image:
- Record the exact existing Docker Compose file, environment, port mappings, attached database and volumes. Back up the Open WebUI DB and persistent volume. Do not run both containers against one SQLite DB simultaneously.
- Change **only the Open WebUI container image** to `cutedisplay/openwebui:realtime-apikey-candidate`; preserve every other setting. Stop the existing container and start the replacement through its existing Compose project to keep the **same** URL and network.
- Verify browser login, existing 2FA, original chat, PTT REST APIs, and normal `/health`. Test a valid low-privilege user API key against the realtime WSS, a revoked/wrong key (must fail), `chat.call` permission (must be enforced), and API-key endpoint allowlists.
- If any issue appears, change the Compose image back to `cutedisplay/openwebui-existing:backup` and recreate the container using the original volumes and config. Do **not** delete/initialize the database.
- To test on Mac after the safe deploy, use `python tools/probe_openwebui_realtime_key.py --url "$OPENWEBUI_URL" --model cutedisplay-ai` in the existing `.venv-realtime`; it prompts for the API key without echoing it and tests only the same HTTPS/WSS Open WebUI host.

## Physical button and firmware

The experimental **C5 v22** left BOOT button:
- Short tap (release before 320 ms): `CALL_TOGGLE` → S3 opens or closes the native Open WebUI WSS.
- Hold at least 320 ms while Call Mode is OFF: original manual Push-to-Talk; release stops the recording.
- Hold during Call Mode: ignored (not a second PTT).
- The S3 reports `CALL_CONNECTING`, `CALL_READY`, `CALL_ERROR` and `CALL_OFF` to C5 via UART, with state resynchronization after C5 reboot and every 15 seconds.

**Important:** `CALL_READY` currently means authenticated realtime WebSocket, **NOT** live microphone/speaker. Keep your hardware-tested C5 v21 branch intact and do not flash the v22 experiment until the server-side API-key WSS is tested. The next guarded firmware milestone is 24kHz I2S streaming with safe shared GPIO41/42 clocks, plus selected-model delegation and speaker playback.
