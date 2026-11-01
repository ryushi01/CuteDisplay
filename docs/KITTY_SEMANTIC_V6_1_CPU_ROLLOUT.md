# Kitty Semantic Memory V6.1 — CPU-first staged rollout

Status: **code committed; NOT deployed to Ubuntu or ESP32-S3**. Production `main` continues to run the previously accepted configuration. V6 is an optional, independently testable derived index, not yet part of Kitty's realtime answer path.

## What is implemented
- CPU-only multilingual semantic vectors from a **read-only export** of the S3 microSD `kitty/` directory.
- Reuses one embedding model in RAM across repeated HTTP requests in the same Python process.
- Incremental index rebuild: unchanged records reuse their prior vector; changed/new rows are embedded; deleted rows are removed when a complete generation is published.
- Generation-based publication prevents a failed/incomplete rebuild from becoming the active result set. Partial builds can leave extra temporary data until the next successful rebuild.
- Float32 binary vector storage in SQLite rather than large JSON arrays. Persistent index is disposable/rebuildable; SD is canonical.
- Existing optional `POST /semantic` memory-service route can call the new search function when `KITTY_SEMANTIC_DB` is configured.
- Existing calendar/date path stays untouched, since its current behavior was user-validated.

## Important limits
1. **No automatic SD-to-Ubuntu sync exists yet.** A verified read-only SD export is required for indexing. Do not copy private SD memories into GitHub.
2. **No S3/voice gateway integration yet.** Kitty's realtime conversation currently uses the existing local SD context. Merely installing the index will not automatically improve recall.
3. No GPU required. The default model is `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, not `multilingual-e5-small`; switching models requires rebuilding the index.
4. The first Python/SentenceTransformers installation and model download may use **more storage than the model file alone**, particularly with PyTorch dependencies. Inspect disk headroom.
5. This embedding database contains personal conversation text in addition to vectors; protect it like private microSD data. It is **not** an anonymous cache.
6. SQLite is on the Ubuntu VM's local filesystem backed by iSCSI block storage. Keep backups/snapshots appropriate to the VM; do not assume mounted network shares behave identically.
7. This is an initial flat scan of vectors per search. Benchmark its latency with the real archive before connecting realtime calls; large archives may need ANN indexing and memory limits.

## Before installation on Ubuntu
Run read-only system checks:
```bash
free -h
nproc
df -h /
lsblk -o NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS
```
Keep Open WebUI and its currently running Docker containers unchanged. Verify free RAM/disk and existing container headroom first.

## Independent optional test environment
From a trusted checkout of this feature branch on Ubuntu (not from the running Open WebUI Docker image):
```bash
python3 -m venv ~/kitty-semantic-v6-venv
~/kitty-semantic-v6-venv/bin/python -m pip install -U pip
~/kitty-semantic-v6-venv/bin/pip install 'sentence-transformers>=3,<6'
~/kitty-semantic-v6-venv/bin/python -m unittest server/test_kitty_semantic_v6.py
```
Tests use a fake model, but NumPy is required; no GPU or model download for the tests. The **first real build** downloads a multilingual encoder into the default HuggingFace cache. For safety, set a private model cache directory with appropriate permissions and disk space if needed.

After copying a **read-only export** of `/kitty` from the S3 SD card to a private location, e.g. `/srv/kitty-sd-export/kitty`:
```bash
~/kitty-semantic-v6-venv/bin/python server/kitty_sd_semantic_index.py build \
  --sd-copy /srv/kitty-sd-export --db /var/lib/kitty-semantic/index.sqlite3
~/kitty-semantic-v6-venv/bin/python server/kitty_sd_semantic_index.py search \
  --db /var/lib/kitty-semantic/index.sqlite3 --query "What did I say about work?" --limit 5
```
The destination directory must be user-writable, not world-readable. Repeat `build` after a *new, complete* SD export; the output reports indexed/embedded/reused counts. Do not index a concurrently changing incomplete export.

## Integration plan (not yet complete)
1. Add a bounded, authenticated, incremental synchronization protocol from S3 SD worker to Ubuntu, including stable record IDs, deletions/corrections, checksums, commit markers, retry and backpressure. Keep audio callbacks free of SD I/O.
2. Benchmark CPU encoder warm-start, per-query 50/95th percentile latency, peak RSS, iSCSI write activity, corpus size and Japanese/English/French cross-lingual retrieval accuracy.
3. Introduce asynchronous/bounded retrieval in Open WebUI realtime route with a strict timeout and local SD fallback. Never block or reset microphone/speaker processing while waiting on embeddings.
4. Confirm no additional persistent personal-memory authority on Ubuntu, and retention/deletion propagation before production deployment.
5. Stage deployments with exact Docker image rollback and device firmware checkpoint. Only then merge and promote to `main`.

## Performance principle
Embedding inference primarily uses **CPU and RAM** while creating and querying vectors, but it **does use disk** for model files, SQLite, Python packages and any exported SD copy. Incremental rebuilds reduce repeated vector computation and writes; they do not eliminate I/O.
