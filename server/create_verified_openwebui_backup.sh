#!/usr/bin/env bash
# Safely back up the EXISTING Open WebUI volume without deploying a new image.
# Live pre-copy, brief consistent stopped delta sync, then restart original.
# Compress/verify OFFLINE snapshot while original Open WebUI is online.
set -euo pipefail
umask 077
BASE=/home/ryushi/docker-compose.yaml
PROJECT=ryushi
SERVICE=open-webui
DATA=/var/lib/docker/volumes/open-webui/_data
IMAGE=ghcr.io/open-webui/open-webui:main

if [[ $# -ne 1 || "$1" != "--backup" ]]; then
 echo "Usage: bash server/create_verified_openwebui_backup.sh --backup" >&2
 exit 2
fi
for program in rsync tar gzip sha256sum python3 df du mktemp curl; do
 command -v "$program" >/dev/null || {
  echo "Missing $program. No server changes made." >&2
  exit 1
 }
done
[[ -f "$BASE" ]] || { echo "Missing original Compose file" >&2; exit 1; }
sudo docker info >/dev/null
[[ "$(sudo docker inspect "$SERVICE" --format '{{.State.Status}}')" == "running" ]] || {
 echo "Original Open WebUI not running. Refusing backup." >&2; exit 1;
}
[[ "$(sudo docker inspect "$SERVICE" --format '{{.Config.Image}}')" == "$IMAGE" ]] || {
 echo "Original image tag differs. Refusing backup." >&2; exit 1;
}
[[ "$(sudo docker inspect "$SERVICE" --format '{{range .Mounts}}{{if eq .Destination "/app/backend/data"}}{{.Name}}{{end}}{{end}}')" == "open-webui" ]] || {
 echo "Original volume differs. Refusing backup." >&2; exit 1;
}
[[ "$(sudo docker volume inspect open-webui --format '{{.Mountpoint}}')" == "$DATA" ]] || {
 echo "Volume path differs. Refusing backup." >&2; exit 1;
}
curl -fsS --max-time 10 http://127.0.0.1:8080/health >/dev/null || {
 echo "Original Open WebUI must be healthy before backup." >&2; exit 1;
}
SIZE_KIB="$(sudo du -sk "$DATA" | awk '{print $1}')"
FREE_KIB="$(df -Pk /home/ryushi | awk 'NR==2{print $4}')"
if ((FREE_KIB < (SIZE_KIB * 2) + 1048576)); then
 echo "Insufficient disk for independent snapshot and archive. Nothing changed." >&2
 exit 1
fi

BACKUP="$(mktemp -d /home/ryushi/openwebui-verified-XXXXXXXX)"
chmod 700 "$BACKUP"
SNAPSHOT="$BACKUP/snapshot"
sudo install -d -m 700 "$SNAPSHOT"
sudo install -m 600 "$BASE" "$BACKUP/docker-compose.yaml"
if [[ -f /home/ryushi/.env ]]; then
 sudo install -m 600 /home/ryushi/.env "$BACKUP/.env"
fi
cat > "$BACKUP/rollback.yaml" <<'YAML'
services:
  open-webui:
    image: cutedisplay/openwebui-existing:backup
YAML
chmod 600 "$BACKUP/rollback.yaml"

STOPPED=0
COMPLETE=0
recover() {
 local result=$?
 trap - EXIT
 if (( STOPPED )); then
  echo "Recovery: restarting ORIGINAL Open WebUI after backup failure/interruption." >&2
  sudo docker start open-webui >&2 || true
 fi
 if (( ! COMPLETE )); then
  echo "Backup was NOT verified; never restore from: $BACKUP" >&2
 fi
 exit "$result"
}
trap recover EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

echo "Phase 1/3: precopy while original Open WebUI stays ONLINE..."
# Not a valid backup until stopped final sync: SQLite changes during precopy.
sudo rsync -aH --numeric-ids --delete "$DATA/" "$SNAPSHOT/"
echo "Precopy complete. This is not yet a consistent backup."

[[ "$(sudo docker inspect "$SERVICE" --format '{{.State.Status}}')" == "running" ]] || {
 echo "Original service changed during precopy." >&2; exit 1;
}
echo "Phase 2/3: briefly stop ONLY Open WebUI for consistent final sync..."
STOPPED=1
sudo docker compose -p "$PROJECT" --project-directory /home/ryushi -f "$BASE" \
 stop "$SERVICE"
# Compare actual contents, including SQLite DB/WAL, not only mtime.
sudo rsync -aHc --numeric-ids --delete "$DATA/" "$SNAPSHOT/"
echo "Consistent point-in-time snapshot obtained."
sudo docker start "$SERVICE" >/dev/null
STOPPED=0
HEALTH=0
for ((n=1;n<=60;n++)); do
 if curl -fsS --max-time 3 http://127.0.0.1:8080/health >/dev/null 2>&1; then
  HEALTH=1; break
 fi
 sleep 3
done
if (( ! HEALTH )); then
 echo "Original Open WebUI failed /health after restart." >&2
 exit 1
fi
echo "PASS: original Open WebUI online, packaging the offline snapshot."

echo "Phase 3/3: compress snapshot while Open WebUI stays ONLINE..."
# Do not write unverified backup to the final file name.
sudo tar -czf "$BACKUP/openwebui-data.tar.gz.partial" -C "$SNAPSHOT" .
sudo gzip -t "$BACKUP/openwebui-data.tar.gz.partial"
sudo tar -tzf "$BACKUP/openwebui-data.tar.gz.partial" >/dev/null
sudo mv "$BACKUP/openwebui-data.tar.gz.partial" "$BACKUP/openwebui-data.tar.gz"
sudo chmod 600 "$BACKUP/openwebui-data.tar.gz"
(cd "$BACKUP" && sudo sha256sum openwebui-data.tar.gz) > "$BACKUP/SHA256SUMS"
chmod 600 "$BACKUP/SHA256SUMS"
(cd "$BACKUP" && sha256sum -c SHA256SUMS >/dev/null)
printf '%s\n' "verified: gzip, tar, SHA256" > "$BACKUP/BACKUP_VERIFIED"
chmod 600 "$BACKUP/BACKUP_VERIFIED"

COMPLETE=1
trap - EXIT HUP INT TERM
echo "BACKUP VERIFIED: $BACKUP/openwebui-data.tar.gz"
echo "Backup directory: $BACKUP"
echo "Original Open WebUI remains in service; NO patched image deployed."
