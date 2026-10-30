#!/usr/bin/env python3
"""CPU-only semantic index for a read-only export of Kitty's microSD.

The S3 microSD remains authoritative. This SQLite database is a disposable
derived cache, never a second writable memory authority. No remote downloads
except the embedding model's initial local cache download.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_MODEL_CACHE = {}
_MODEL_LOCK = threading.RLock()

def get_model(name=DEFAULT_MODEL):
    # Warm one CPU model for HTTP requests rather than loading per search.
    with _MODEL_LOCK:
        if name not in _MODEL_CACHE:
            from sentence_transformers import SentenceTransformer
            _MODEL_CACHE[name] = SentenceTransformer(name, device="cpu")
        return _MODEL_CACHE[name]

def load_rows(sd):
    root = Path(sd) / "kitty"
    for filename in ("facts.tsv", "dated_plans.tsv", "summaries.tsv", "conversations.tsv"):
        path = root / filename
        if not path.is_file():
            continue
        with path.open(encoding="utf-8", errors="replace") as handle:
            for i, line in enumerate(handle):
                parts = line.rstrip("\r\n").split("\t")
                if filename == "facts.tsv" and len(parts) >= 2:
                    key, value = parts[0], parts[1]
                elif filename == "dated_plans.tsv" and len(parts) >= 3:
                    key, value = parts[1], parts[2]
                elif filename == "summaries.tsv" and len(parts) >= 2:
                    key, value = "summary:" + parts[0], parts[1]
                elif filename == "conversations.tsv" and len(parts) >= 3:
                    key, value = "conversation:" + parts[0], parts[1] + " " + parts[2]
                else:
                    continue
                if key and value:
                    yield f"{filename}:{i}:{key}", f"{key}: {value}"

def _connect(path):
    db = sqlite3.connect(str(path), timeout=10)
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("""CREATE TABLE IF NOT EXISTS semantic_v6 (
      id TEXT NOT NULL, text TEXT NOT NULL, digest TEXT NOT NULL,
      vector BLOB NOT NULL, model TEXT NOT NULL, generation INTEGER NOT NULL,
      PRIMARY KEY(id,generation)
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS semantic_v6_generation ON semantic_v6(generation)")
    db.execute("""CREATE TABLE IF NOT EXISTS semantic_speakers (
       id TEXT NOT NULL, generation INTEGER NOT NULL,
       speaker_id TEXT NOT NULL, speaker_role TEXT NOT NULL,
       provenance TEXT NOT NULL, PRIMARY KEY(id,generation)
    )""")
    return db

def build(sd, out, model_name=DEFAULT_MODEL, batch_size=32):
    """Incrementally refresh derived index. Writes commit only after each batch.

    On interruption, next build repairs any partial generation; searches can
    continue to use the last complete generation.
    """
    import numpy as np
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    model = get_model(model_name)
    with _connect(out) as db:
        db.execute("CREATE TABLE IF NOT EXISTS semantic_meta (key TEXT PRIMARY KEY, value TEXT)")
        active_row = db.execute("SELECT value FROM semantic_meta WHERE key='active'").fetchone()
        active = int(active_row[0]) if active_row else 0
        next_gen = active + 1
        # Interrupted build rows are discarded, not offered to live searches.
        db.execute("DELETE FROM semantic_v6 WHERE generation NOT IN (?,?)", (active, next_gen))
        db.execute("DELETE FROM semantic_v6 WHERE generation=?", (next_gen,))
        db.execute("DELETE FROM semantic_speakers WHERE generation=?", (next_gen,))
        db.commit()
        from kitty_semantic_attribution_v6 import iter_archive_with_speakers
        speakers = {r["id"]:r for r in iter_archive_with_speakers(sd)}
        current = {row[0]: row[1:] for row in db.execute(
            "SELECT id,digest,vector,model FROM semantic_v6 WHERE generation=?", (active,))}
        count, reused, changed = 0, 0, 0
        batch = []
        def flush():
            nonlocal changed
            if not batch:
                return
            texts = [x[2] for x in batch]
            with _MODEL_LOCK:
                vectors = model.encode(texts, normalize_embeddings=True, batch_size=16)
            db.executemany("INSERT OR REPLACE INTO semantic_v6 VALUES (?,?,?,?,?,?)",
                [(id, text, digest, np.asarray(vec, dtype="<f4").tobytes(), model_name, next_gen)
                 for (id, digest, text), vec in zip(batch, vectors)])
            changed += len(batch)
            batch.clear()
            db.commit()
        for id, value in load_rows(sd):
            count += 1
            source=speakers.get(id)
            if source:
                db.execute("INSERT OR REPLACE INTO semantic_speakers VALUES (?,?,?,?,?)",
                           (id,next_gen,source["speaker_id"],source["speaker_role"],source["provenance"]))
            digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
            old = current.get(id)
            if old and old[0] == digest and old[2] == model_name:
                db.execute("INSERT OR REPLACE INTO semantic_v6 VALUES (?,?,?,?,?,?)",
                           (id, value, digest, old[1], model_name, next_gen))
                reused += 1
            else:
                batch.append((id, digest, value))
                if len(batch) >= batch_size:
                    flush()
        flush()
        db.execute("INSERT OR REPLACE INTO semantic_meta VALUES ('active', ?)", (str(next_gen),))
        db.commit()
        db.execute("DELETE FROM semantic_v6 WHERE generation!=?", (next_gen,))
        db.execute("DELETE FROM semantic_speakers WHERE generation!=?", (next_gen,))
        db.commit()
    return {"indexed":count, "embedded":changed, "reused":reused, "model":model_name}

def search(db_path, query, k=5, model_name=DEFAULT_MODEL, speaker_id=None):
    """Return bounded semantic results. Never modify source memories."""
    import numpy as np
    if not query or not query.strip() or len(query)>1000:
        return []
    if not os.path.isfile(db_path):
        raise FileNotFoundError(db_path)
    model = get_model(model_name)
    with _MODEL_LOCK:
        q = np.asarray(model.encode([query], normalize_embeddings=True)[0], dtype=np.float32)
    results = []
    with _connect(db_path) as db:
        active_row = db.execute("SELECT value FROM semantic_meta WHERE key='active'").fetchone() if _has_meta(db) else None
        if not active_row:
            return []
        gen=int(active_row[0])
        speaker_rows={r[0]:{"speaker_id":r[1],"speaker_role":r[2],"provenance":r[3]}
            for r in db.execute("SELECT id,speaker_id,speaker_role,provenance FROM semantic_speakers WHERE generation=?", (gen,))}
        for id, text, raw, model_used in db.execute(
            "SELECT id,text,vector,model FROM semantic_v6 WHERE generation=?", (gen,)):
            if model_used != model_name:
                continue
            attribution=speaker_rows.get(id,{"speaker_id":"unknown","speaker_role":"unknown","provenance":"unverified"})
            if speaker_id is not None and attribution["speaker_id"] != speaker_id:
                continue
            vec = np.frombuffer(raw, dtype="<f4")
            if vec.shape != q.shape:
                continue
            results.append((float(np.dot(q, vec)), id, text))
    results.sort(reverse=True)
    return [{"score": round(score,4), "id":id, "text":text,
             **speaker_rows.get(id,{"speaker_id":"unknown","speaker_role":"unknown","provenance":"unverified"})}
            for score,id,text in results[:max(1,min(int(k),10))]]

def _has_meta(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='semantic_meta'").fetchone() is not None

def main():
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest="command",required=True)
    a=sub.add_parser("build"); a.add_argument("--sd-copy",required=True); a.add_argument("--db",required=True)
    b=sub.add_parser("search"); b.add_argument("--db",required=True); b.add_argument("--query",required=True)
    b.add_argument("--limit",type=int,default=5)
    args=p.parse_args()
    if args.command=="build":
        print(json.dumps(build(args.sd_copy,args.db)))
    else:
        print(json.dumps({"results":search(args.db,args.query,args.limit)},ensure_ascii=False))
if __name__=="__main__":
    main()
