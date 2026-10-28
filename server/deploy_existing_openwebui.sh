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
if [[ "$MODE" != "--check" && "$MODE" != "--deploy" ]]; then
  echo "Usage: bash server/deploy_existing_openwebui.sh --check|--deploy" >&2
  exit 2
fi
if [[ ! -f "$BASE" ]]; then echo "Missing original Compose file" >&2; exit 1; fi
sudo docker info >/dev/null
sudo docker compose version >/dev/null
sudo docker image inspect "$ORIGINAL" >/dev/null
sudo docker image inspect "$CANDIDATE" >/dev/null
# Do not print resolved Compose config: it may contain passwords.
sudo docker compose -p "$PROJECT" --project-directory /home/ryushi -f "$BASE" config --format json | python3 -c '
import json,sys
cfg=json.load(sys.stdin)
s=cfg["services"]["open-webui"]
assert s.get("image")=="ghcr.io/open-webui/open-webui:main", "Original Compose image differs"
vols=[v for v in s.get("volumes",[]) if v.get("target")=="/app/backend/data"]
assert len(vols)==1 and vols[0].get("type")=="volume", "Unexpected data mount"
source=vols[0]["source"]
assert cfg.get("volumes",{}).get(source,{}).get("name",source)=="open-webui", "Unexpected volume name"
assert any(str(v.get("published"))=="8080" and int(v.get("target",0))==8080 for v in s.get("ports",[])), "Unexpected port"
print("PASS: same project, same WebUI port 8080, same open-webui persistent volume")
'
IMAGE="$(sudo docker inspect "$SERVICE" --format '{{.Config.Image}}')"
STATE="$(sudo docker inspect "$SERVICE" --format '{{.State.Status}}')"
VOLUME="$(sudo docker inspect "$SERVICE" --format '{{range .Mounts}}{{if eq .Destination "/app/backend/data"}}{{.Name}}{{end}}{{end}}')"
if [[ "$IMAGE" != "ghcr.io/open-webui/open-webui:main" || "$STATE" != "running" || "$VOLUME" != "open-webui" ]]; then
  echo "Existing container does not match expected running service. Nothing changed." >&2
  exit 1
fi
if [[ "$MODE" == "--check" ]]; then
  echo "PASS: both images available. No Docker service was changed."
  exit 0
fi

DATA="$(sudo docker volume inspect open-webui --format '{{.Mountpoint}}')"
if [[ "$DATA" != "/var/lib/docker/volumes/open-webui/_data" ]]; then
  echo "Volume mountpoint differs; refusing deployment." >&2
  exit 1
fi
BACKUP="$(mktemp -d "$HOME/openwebui-rollback-XXXXXXXX")"
chmod 700 "$BACKUP"
sudo install -m 600 "$BASE" "$BACKUP/docker-compose.yaml"
if [[ -f /home/ryushi/.env ]]; then
  sudo install -m 600 /home/ryushi/.env "$BACKUP/.env"
fi
cat > "$BACKUP/candidate.yaml" <<'OVERRIDE'
services:
  open-webui:
    image: cutedisplay/openwebui:realtime-apikey-candidate
OVERRIDE
cat > "$BACKUP/rollback.yaml" <<'OVERRIDE'
services:
  open-webui:
    image: cutedisplay/openwebui-existing:backup
OVERRIDE
# docker-compose.yaml was copied with sudo install and is root-owned mode 600.
# Only chmod override files written by the unprivileged ryushi account.
chmod 600 "$BACKUP/candidate.yaml" "$BACKUP/rollback.yaml"
# Verify replacement keeps exactly the same persistent data mapping.
sudo docker compose -p "$PROJECT" --project-directory /home/ryushi -f "$BASE" -f "$BACKUP/candidate.yaml" config --format json | python3 -c '
import json,sys
svc=json.load(sys.stdin)["services"]["open-webui"]
assert svc["image"]=="cutedisplay/openwebui:realtime-apikey-candidate"
assert any(v.get("source")=="open-webui" and v.get("target")=="/app/backend/data" for v in svc["volumes"])
'
AVAILABLE="$(df -Pk "$BACKUP" | awk 'NR==2{print $4}')"
SIZE="$(sudo du -sk "$DATA" | awk '{print $1}')"
if (( AVAILABLE < SIZE + 102400 )); then
  echo "Insufficient disk space to back up database safely; original service untouched." >&2
  exit 1
fi

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

echo "Stopping ONLY open-webui for a consistent database backup..."
# Arrange automatic restart even if the stop command itself returns an error.
STAGE=1
sudo docker compose -p "$PROJECT" --project-directory /home/ryushi -f "$BASE" stop "$SERVICE"
sudo tar -czf "$BACKUP/openwebui-data.tar.gz" -C "$DATA" .
sudo chmod 600 "$BACKUP/openwebui-data.tar.gz"
sudo tar -tzf "$BACKUP/openwebui-data.tar.gz" >/dev/null
echo "PASS: data archived while Open WebUI was stopped."
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
echo "Private backup directory: $BACKUP"
echo "Browser login, MFA and API-key tests still required before flashing devices."
echo "Rollback command: sudo docker compose -p ryushi -f /home/ryushi/docker-compose.yaml -f '$BACKUP/rollback.yaml' up -d --no-deps --force-recreate open-webui"
