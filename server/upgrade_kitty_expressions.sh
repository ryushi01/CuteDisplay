#!/usr/bin/env bash
# One-command, guarded extension of the existing Open WebUI container.
# Run as normal ryushi user on ai-server: bash server/upgrade_kitty_expressions.sh
# Never invoked by CI. Leaves browser login/MFA, data, hostname and port intact.
set -euo pipefail
umask 077
BASE=/home/ryushi/docker-compose.yaml
PROJECT=ryushi
SERVICE=open-webui
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHECK="$ROOT/server/check_openwebui_compose_config.py"
for tool in docker rsync tar gzip sha256sum curl python3 mktemp; do
 command -v "$tool" >/dev/null || { echo "Missing $tool" >&2; exit 1; }
done
[[ -f "$BASE" && -f "$CHECK" ]] || { echo "Original Compose config missing" >&2; exit 1; }
sudo -v
sudo docker info >/dev/null
sudo docker compose version >/dev/null
STATUS="$(sudo docker inspect "$SERVICE" --format '{{.State.Status}}')"
IMAGE_ID="$(sudo docker inspect "$SERVICE" --format '{{.Image}}')"
IMAGE_USER="$(sudo docker inspect "$SERVICE" --format '{{.Config.User}}')"
VOLUME="$(sudo docker inspect "$SERVICE" --format '{{range .Mounts}}{{if eq .Destination "/app/backend/data"}}{{.Name}}{{end}}{{end}}')"
[[ "$STATUS" == running && -n "$IMAGE_ID" && "$VOLUME" == open-webui ]] || {
 echo "Unexpected Open WebUI container state or volume; refusing changes" >&2; exit 1;
}
DATA="$(sudo docker volume inspect open-webui --format '{{.Mountpoint}}')"
[[ "$DATA" == /var/lib/docker/volumes/open-webui/_data ]] || {
 echo "Unexpected data volume location; refusing changes" >&2; exit 1;
}
curl -fsS --max-time 8 http://127.0.0.1:8080/health >/dev/null
[[ -n "$IMAGE_USER" ]] || IMAGE_USER=0:0
STAMP="$(date -u +%Y%m%d%H%M%S)"
BEFORE="cutedisplay/openwebui:before-kitty-expressions-$STAMP"
CANDIDATE="cutedisplay/openwebui:kitty-expressions-$STAMP"
OUT="$(mktemp -d /home/ryushi/kitty-expressions-XXXXXXXX)"
chmod 700 "$OUT"
cat > "$OUT/rollback.yaml" <<YAML
services:
  open-webui:
    image: $BEFORE
YAML
cat > "$OUT/candidate.yaml" <<YAML
services:
  open-webui:
    image: $CANDIDATE
YAML
chmod 600 "$OUT/rollback.yaml" "$OUT/candidate.yaml"
for FILE in rollback.yaml candidate.yaml; do
 if [[ "$FILE" == rollback.yaml ]]; then IMAGE="$BEFORE"; else IMAGE="$CANDIDATE"; fi
 sudo docker compose -p "$PROJECT" --project-directory /home/ryushi \
  -f "$BASE" -f "$OUT/$FILE" config --format json |
  python3 "$CHECK" --expected-image "$IMAGE" >/dev/null
done
sudo docker image tag "$IMAGE_ID" "$BEFORE"
echo "[1/4] Building extension from the precise currently running image..."
sudo docker build --quiet -f "$ROOT/server/Dockerfile.openwebui-realtime-apikey" \
 --build-arg "BASE_IMAGE=$BEFORE" --build-arg "ORIGINAL_USER=$IMAGE_USER" \
 -t "$CANDIDATE" "$ROOT" >/dev/null
sudo docker image inspect "$CANDIDATE" >/dev/null
echo "[2/4] Creating independent, verified Open WebUI data backup..."
SIZE_KIB="$(sudo du -sk "$DATA" | awk '{print $1}')"
FREE_KIB="$(df -Pk /home/ryushi | awk 'NR==2{print $4}')"
if (( FREE_KIB < SIZE_KIB*2 + 1048576 )); then
 echo "Insufficient space for verified backup; no deployment" >&2; exit 1
fi
SNAP="$OUT/snapshot"
sudo install -d -m 700 "$SNAP"
sudo install -m 600 "$BASE" "$OUT/original-compose.yaml"
if [[ -f /home/ryushi/.env ]]; then
 sudo install -m 600 /home/ryushi/.env "$OUT/original-env"
fi
STOPPED=0
DEPLOYED=0
SUCCESS=0
recover(){
 local rc=$?
 trap - EXIT
 if (( STOPPED )); then
  echo "Recovery: restart original service" >&2
  sudo docker start "$SERVICE" >/dev/null || true
 elif (( DEPLOYED && ! SUCCESS )); then
  echo "Recovery: restore exact previous running image" >&2
  sudo docker compose -p "$PROJECT" --project-directory /home/ryushi \
   -f "$BASE" -f "$OUT/rollback.yaml" up -d --no-deps --force-recreate "$SERVICE" || true
 fi
 echo "Rollback image and verified backups: $OUT" >&2
 exit "$rc"
}
trap recover EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
sudo rsync -aH --numeric-ids --delete "$DATA/" "$SNAP/"
STOPPED=1
sudo docker stop "$SERVICE" >/dev/null
sudo rsync -aHc --numeric-ids --delete "$DATA/" "$SNAP/"
sudo docker start "$SERVICE" >/dev/null
STOPPED=0
HEALTH=0
for ((n=0;n<60;n++)); do
 if curl -fsS --max-time 3 http://127.0.0.1:8080/health >/dev/null 2>&1; then
  HEALTH=1;break
 fi
 sleep 3
done
(( HEALTH == 1 )) || { echo "Original service health did not return" >&2; exit 1; }
sudo tar -czf "$OUT/data.tar.gz.partial" -C "$SNAP" .
sudo gzip -t "$OUT/data.tar.gz.partial"
sudo tar -tzf "$OUT/data.tar.gz.partial" >/dev/null
sudo mv "$OUT/data.tar.gz.partial" "$OUT/data.tar.gz"
(cd "$OUT" && sudo sha256sum data.tar.gz) > "$OUT/SHA256SUMS"
(cd "$OUT" && sudo sha256sum -c SHA256SUMS >/dev/null)
printf 'verified: stopped-state snapshot, tar, gzip, sha256\n' > "$OUT/BACKUP_VERIFIED"
echo "[3/4] Switching only Open WebUI to expression-enabled image..."
DEPLOYED=1
sudo docker compose -p "$PROJECT" --project-directory /home/ryushi \
 -f "$BASE" -f "$OUT/candidate.yaml" up -d --no-deps --force-recreate "$SERVICE"
EXPECTED="$(sudo docker image inspect "$CANDIDATE" --format '{{.Id}}')"
ACTIVE="$(sudo docker inspect "$SERVICE" --format '{{.Image}}')"
[[ "$EXPECTED" == "$ACTIVE" ]] || { echo "Unexpected deployed image" >&2; exit 1; }
HEALTH=0
for ((n=0;n<60;n++)); do
 if curl -fsS --max-time 3 http://127.0.0.1:8080/health >/dev/null 2>&1; then
  HEALTH=1;break
 fi
 sleep 3
done
(( HEALTH == 1 )) || { echo "New service health failed" >&2; exit 1; }
SUCCESS=1
trap - EXIT HUP INT TERM
echo "[4/4] PASS: existing Open WebUI healthy; data backed up with SHA256"
echo "Backup and rollback: $OUT"
echo "Undo if necessary: sudo docker compose -p ryushi --project-directory /home/ryushi -f $BASE -f $OUT/rollback.yaml up -d --no-deps --force-recreate open-webui"
echo "Expression tool enabled only for authenticated S3 clients opting in."
