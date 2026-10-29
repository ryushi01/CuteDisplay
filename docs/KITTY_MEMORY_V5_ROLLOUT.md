# Kitty Memory V5 — coordinated rollout (2026-10-29)

## State and rollback
Experimental branch: `feature/kitty-memory-v5-fullstack`. Prior firmware checkpoint: `checkpoint/2026-10-29-sd-brain-v4`. Validated `main` remains unchanged.

## Architecture
1. ESP32-S3/C5 continue using the V4 firmware: microSD is canonical for `/kitty/facts.tsv`, `factsmeta.tsv`, `dated_plans.tsv`, `summaries.tsv`, `conversations.tsv` and `memory.idx`. The low-priority Core 0 SD worker owns I/O.
2. The Ubuntu server may run optional **CPU-only multilingual embeddings** through `server/kitty_sd_semantic_index.py`. It reads a *read-only offline copy* of `kitty/` on SD and builds a local SQLite embedding index. This indexes facts, dated plans, summaries and the conversation archive from a copied SD directory. Large exports can consume significant CPU, RAM and storage on the first embedding pass. Embeddings are a disposable derived cache; the SD files remain source of truth.
3. `server/kitty_calendar.py` can parse many Japanese, English and French natural-language date phrases with explicit IANA timezone. It returns `outcome=unconfirmed` even for past activities.
4. `server/kitty_memory_service.py` has authenticated optional `POST /semantic` and `POST /calendar` routes, in addition to its existing API. Semantic search requires `KITTY_SEMANTIC_DB`. These endpoints are **not yet invoked by S3 firmware**, and are not installed on the running host.
5. `server/patch_openwebui_memory_refresh.py` is the previously developed opt-in, version-guarded realtime memory refresh extension. It is included in the optional Open WebUI image Dockerfile and paired S3 firmware (from V4); no changes were made to your running container.
6. `server/KITTY_PERSONA_V5.md` is the shared, reviewable persona specification. The shipped V4 firmware includes its short persona instructions; the realtime Open WebUI patch includes onee-san instructions. The full V5 prompt is not automatically injected into your live server until you edit the model prompt / rebuild the pinned gateway image.

## Ubuntu installation preparation (manual, **not** deployed)
Use a Python virtual environment on Ubuntu:
```bash
python3 -m venv ~/kitty-memory-venv
~/kitty-memory-venv/bin/pip install 'sentence-transformers>=3,<6' 'dateparser>=1.2,<2'
```
Copy **only** the `kitty/` directory from S3 microSD into a private directory accessible on Ubuntu, preferably using a secure one-time SD export, without deleting the source.
```bash
~/kitty-memory-venv/bin/python server/kitty_sd_semantic_index.py build \
  --sd-copy /path/to/read-only-sd-export --db /path/to/private/kitty-semantic.sqlite3
~/kitty-memory-venv/bin/python server/kitty_sd_semantic_index.py search \
  --db /path/to/private/kitty-semantic.sqlite3 --query '昨日の予定は？'
~/kitty-memory-venv/bin/python server/kitty_calendar.py --text 'next Friday at 3 PM' --timezone Asia/Tokyo
```
The model weights are downloaded the first time `SentenceTransformer` loads; verify CPU/RAM/disk headroom first. No GPU or Mac is mandatory. The first cold-start can be slow; do **not** run this inside the realtime I2S/WebSocket task.

Use your existing verified server backup process for the Open WebUI image and state before applying the gateway patch. **Do not** restart or replace Open WebUI without verifying the pinned image and rollback. This GitHub commit does not execute any server changes.

## Important remaining engineering work before an end-to-end release
- Implement authenticated incremental/streaming SD-to-server export (rather than manually copying data), replay/checksum recovery, and a reliable reconciliation loop without making the cloud server canonical.
- Integrate the server semantic + calendar endpoint into the realtime/Open WebUI retrieval path with tight timeouts, cancellation and fallback to local memory. Merely defining the endpoints does not make Kitty use them.
- Make large SD archive embedding ingestion incremental with checkpoints and add scalable approximate-nearest-neighbor indexing (current SQLite vector search computes all cosines); evaluate multilingual retrieval accuracy and model size.
- Improve arbitrary language/calendar ambiguities, recurring plans, corrections and events with multiple timezones. Dateparser is broad but not a complete semantic calendar or proof-of-completion engine.
- Test exact gateway image compatibility with real Open WebUI session.update, memory refresh, audio barge-in, permissions and older clients.
- Validate full CI and S3 hardware before production merge; do not claim zero latency until measured.

## Security
Do not expose the optional memory service to the public internet. It binds loopback by default and requires `KITTY_MEMORY_TOKEN`; use a reverse proxy or authenticated VPN when remote calls are eventually implemented. Treat exported SD memory and derived embeddings as private data. Avoid committing actual memories, tokens, credentials, audio or medical/relationship information to GitHub.
