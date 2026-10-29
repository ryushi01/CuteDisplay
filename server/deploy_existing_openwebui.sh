#!/usr/bin/env bash
# Replace only the existing Open WebUI Compose image, with a consistent data backup.
# Run from ~/CuteDisplay-realtime-server on ai-server.
set -euo pipefail
umask 077
BASE=/home/ryushi/docker-compose.yaml
PROJECT=ryushi
SERVICE=open-webui
ORIGINAL=cutedisplay/openwebui-existing:backup
CANDIDATE=cutedisplay/openwebui:realtime-apikey-candidate
MODE="$1"
BACKUP_REQUEST="${2:-}"
if [[ "$MODE" != "--check" && "$MODE" != "--deploy" ]]; then
  echo "Usage: bash server/deploy_existing_openwebui.sh --check | --deploy /home/ryushi/openwebui-verified-NNNN" >&2
  exit 2
fi
if [[ ! -f "$BASE" ]]; then echo "Missing original Compose file" >&2; exit 1; fi
sudo docker info >/dev/null
sudo docker compose version >/dev/null
sudo docker image inspect "$ORIGINAL" >/dev/null
sudo docker image inspect "$CANDIDATE" >/dev/null
# Do not print resolved Compose config: it can contain passwords.
# Map logical Compose volume aliases to the effective Docker volume name.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
sudo docker compose -p "$PROJECT" --project-directory /home/ryushi -f "$BASE" config --format json |
  python3 "$SCRIPT_DIR/check_openwebui_compose_config.py" \
    --expected-image ghcr.io/open-webui/open-webui:main
IMAGE="$(sudo docker inspect "$SERVICE" --format '{{.Config.Image}}')"
STATE="$(sudo docker inspect "$SERVICE" --format '{{.State.Status}}')"
VOLUME="$(sudo docker inspect "$SERVICE" --format '{{range .Mounts}}{{if eq .Destination "/app/backend/data"}}{{.Name}}{{end}}{{end}}')"
if [[ "$IMAGE" != "ghcr.io/open-webui/open-webui:main" || "$STATE" != "running" || "$VOLUME" != "open-webui" ]]; then
  echo "Existing container does not match expected running service. Nothing changed." >&2
  exit 1
fi
if [[ "$MODE" == "--check" ]]; then
  # Exercise the EXACT candidate image/volume check that deployment runs,
  # rather than passing preflight and failing when deployment starts.
  CHECK_OVERRIDE="$(mktemp "$HOME/cutedisplay-compose-check-XXXXXXXX.yaml")"
  trap 'rm -f "$CHECK_OVERRIDE"' EXIT
  cat > "$CHECK_OVERRIDE" <<'OVERRIDE'
services:
  open-webui:
    image: cutedisplay/openwebui:realtime-apikey-candidate
OVERRIDE
  sudo docker compose -p "$PROJECT" --project-directory /home/ryushi -f "$BASE" -f "$CHECK_OVERRIDE" config --format json |
    python3 "$SCRIPT_DIR/check_openwebui_compose_config.py" \
      --expected-image "$CANDIDATE"
  echo "PASS: original and candidate Compose configurations preserve real Docker volume and port 8080."
  echo "No Docker service was changed."
  exit 0
fi

DATA="$(sudo docker volume inspect open-webui --format '{{.Mountpoint}}')"
if [[ "$DATA" != "/var/lib/docker/volumes/open-webui/_data" ]]; then
  echo "Volume mountpoint differs; refusing deployment." >&2
  exit 1
fi
# A newly verified backup is mandatory. Do not stop the server to produce
# another gzip file: the earlier 593 MB backup was truncated when interrupted.
BACKUP="$BACKUP_REQUEST"
if [[ ! "$BACKUP" == /home/ryushi/openwebui-verified-* ||
      ! -f "$BACKUP/BACKUP_VERIFIED" ||
      ! -f "$BACKUP/openwebui-data.tar.gz" ||
      ! -f "$BACKUP/SHA256SUMS" ||
      ! -f "$BACKUP/candidate.yaml" ]]; then
 echo "Need a fully VERIFIED backup. Run create_verified_openwebui_backup.sh --backup first." >&2
 exit 1
fi
# A backup must be recently captured to minimize loss if rollback is needed.
AGE_SEC=$(( $(date +%s) - $(stat -c %Y "$BACKUP/BACKUP_VERIFIED") ))
if (( AGE_SEC < 0 || AGE_SEC > 21600 )); then
 echo "Backup is older than 6 hours. Create a new verified backup before deployment." >&2
 exit 1
fi
echo "Verifying the independent archived snapshot BEFORE any service stop..."
(cd "$BACKUP" && sudo sha256sum -c SHA256SUMS >/dev/null)
sudo gzip -t "$BACKUP/openwebui-data.tar.gz"
sudo tar -tzf "$BACKUP/openwebui-data.tar.gz" >/dev/null
echo "PASS: validated protected Open WebUI data archive, SHA256 and gzip trailer."
# Real Docker mount must remain open-webui even if Compose logical alias differs.
sudo docker compose -p "$PROJECT" --project-directory /home/ryushi -f "$BASE" -f "$BACKUP/candidate.yaml" config --format json |
  python3 "$SCRIPT_DIR/check_openwebui_compose_config.py" \
    --expected-image "$CANDIDATE"
STAGE=0
DONE=0
cleanup() {
  result=$?
  trap - EXIT
  if [[ "$DONE" == 0 && "$STAGE" == 1 ]]; then
    echo "Recovering stopped original Open WebUI container..." >&2
    sudo docker start open-webui || true
  elif [[ "$DONE" == 0 && "$STAGE" == 2 ]]; then
    echo "Replacing failed candidate with ORIGINAL backed-up image..." >&2
    sudo docker compose -p "$PROJECT" --project-directory /home/ryushi -f "$BASE" -f "$BACKUP/rollback.yaml" up -d --no-deps --force-recreate "$SERVICE" || true
  fi
  if [[ "$DONE" == 0 ]]; then echo "Deployment failed. Backup: $BACKUP" >&2; fi
  exit "$result"
}
trap cleanup EXIT

echo "Deploying with a PREVERIFIED existing backup. No new snapshot required."
STAGE=1
sudo docker compose -p "$PROJECT" --project-directory /home/ryushi -f "$BASE" stop "$SERVICE"
STAGE=2
sudo docker compose -p "$PROJECT" --project-directory /home/ryushi -f "$BASE" -f "$BACKUP/candidate.yaml" up -d --no-deps --force-recreate "$SERVICE"
EXPECTED="$(sudo docker image inspect "$CANDIDATE" --format '{{.Id}}')"
ACTIVE="$(sudo docker inspect "$SERVICE" --format '{{.Image}}')"
if [[ "$EXPECTED" != "$ACTIVE" ]]; then
  echo "Wrong running image: rolling back" >&2
  exit 1
fi
HEALTH=0
for ((n=0;n<60;n++)); do
  if curl --silent --fail --max-time 3 http://127.0.0.1:8080/health >/dev/null 2>&1; then
    HEALTH=1
    break
  fi
  sleep 3
done
if [[ "$HEALTH" != 1 ]]; then
  echo "New image did not pass HTTP health check; rolling back" >&2
  exit 1
fi
DONE=1
trap - EXIT
echo "PASS: candidate image active and original /health responding."
echo "Verified backup directory: $BACKUP"
echo "Browser login, MFA and API-key tests still required before flashing devices."
echo "Rollback command: sudo docker compose -p ryushi -f /home/ryushi/docker-compose.yaml -f '$BACKUP/rollback.yaml' up -d --no-deps --force-recreate open-webui"
