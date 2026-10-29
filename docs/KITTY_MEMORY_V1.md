# Kitty Memory v1 — latency-first backend (stage 1)

This stage implements the **storage engine only**, not automatic AI memory extraction,
realtime retrieval, or S3 microSD syncing. Do not describe the full memory feature
as working until it is integrated and hardware-tested.

## Scope / safety
- Python standard library + SQLite FTS5 on ai-server (no Mac inference load).
- Localhost-only HTTP API by default (port 8766). Never forward this port publicly.
- Explicit 202-accepted write queue; requests never wait for the disk commit.
- Bounded recall: 6 results maximum, 500-character query.
- Upsert on exact topic; soft delete by ID.
- Append-only transcript archive on explicit /turn calls.
- No microphone/I2S, C5 framebuffer, websocket or current voice path changed.
- No automatic mining of personal data or storage of conversation content yet.

## Install (ai-server)

```bash
cd ~/CuteDisplay-realtime-server
git fetch origin feature/realtime-kitty-fullscreen-expressions
git checkout feature/realtime-kitty-fullscreen-expressions
python3 -m unittest server.test_kitty_memory_service -v

mkdir -p ~/.config/cutedisplay
umask 077
test -s ~/.config/cutedisplay/memory-token || python3 -c 'import secrets,pathlib; p=pathlib.Path.home()/".config/cutedisplay/memory-token";p.write_text(secrets.token_urlsafe(32))'
export KITTY_MEMORY_TOKEN="$(cat ~/.config/cutedisplay/memory-token)"
python3 server/kitty_memory_service.py --host 127.0.0.1 --port 8766
```

This foreground run is for testing. For persistence, configure an ordinary
systemd user unit and protect the secret file (0600).

## Example local API

```bash
export KITTY_MEMORY_TOKEN="$(cat ~/.config/cutedisplay/memory-token)"
curl -fsS http://127.0.0.1:8766/health
curl -fsS -X POST http://127.0.0.1:8766/remember \
  -H "Authorization: Bearer $KITTY_MEMORY_TOKEN" -H "Content-Type: application/json" \
  -d '{"topic":"trip plan","detail":"Kyoto in December"}'
curl -fsS -X POST http://127.0.0.1:8766/recall \
  -H "Authorization: Bearer $KITTY_MEMORY_TOKEN" -H "Content-Type: application/json" \
  -d '{"query":"Kyoto travel"}'
```

## Future integration gates
1. Explicitly opt in to persistent retention (previous transient retention is 24 h).
2. Implement nonblocking turn capture and independent memory sync.
3. Integrate bounded retrieval into the actual Open WebUI chat request, measure p50/p95
   time-to-first-token before/after, and skip retrieval on timeout.
4. Extract memories with the model ONLY while it is idle; never consume the Mac
   inference device concurrently with active speech generation.
5. Add portable SD snapshot export with power-loss safe writes and backups.
6. Test malformed inputs, crash recovery, retention/deletion, and permissions.

The card is not used by this stage.
