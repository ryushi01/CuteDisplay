#!/usr/bin/env python3
"""Kitty Memory v1 storage API. Standard library only; bind localhost by default."""
import argparse, base64, binascii, json, os, queue, re, sqlite3, threading, time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_BODY = 16384
DB = os.environ.get("KITTY_MEMORY_DB", os.path.expanduser("~/.local/share/cutedisplay/memory.sqlite3"))
TOKEN = os.environ.get("KITTY_MEMORY_TOKEN", "")
WRITE_Q = queue.Queue(maxsize=256)
LOCK = threading.Lock()
OWNER_PROOF = None
# Optional, isolated CPU index refresh. Snapshot upload acknowledgement never
# waits for embedding; a single worker coalesces bursts of completed snapshots.
SEMANTIC_REFRESH_Q = queue.Queue(maxsize=1)

def semantic_refresh_worker():
    while True:
        snapshot = SEMANTIC_REFRESH_Q.get()
        try:
            root = os.environ.get("KITTY_SD_SNAPSHOT_ROOT", "")
            db = os.environ.get("KITTY_SEMANTIC_DB", "")
            if root and db:
                from kitty_refresh_finalized_v6 import refresh
                result = refresh(root, db, dry_run=False)
                print("Kitty semantic index refreshed:", result.get("indexed", 0), flush=True)
        except Exception as exc:
            # Preserve the previous complete index generation on failure.
            print("Kitty semantic refresh failed:", type(exc).__name__, flush=True)
        finally:
            SEMANTIC_REFRESH_Q.task_done()

def queue_semantic_refresh(snapshot):
    if os.environ.get("KITTY_SEMANTIC_AUTO_REFRESH", "") != "1":
        return
    try:
        SEMANTIC_REFRESH_Q.put_nowait(snapshot)
    except queue.Full:
        # A later refresh reads the newest finalized snapshot.
        pass

def legacy_memory_enabled():
    # Explicit migration-only opt-in; never enabled for normal SD memory use.
    return os.environ.get("KITTY_LEGACY_MEMORY_DB_ENABLED") == "1"

def connect():
    db = sqlite3.connect(DB, timeout=3)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=3000")
    return db

def init():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS memories (
          id INTEGER PRIMARY KEY, topic TEXT NOT NULL, detail TEXT NOT NULL,
          source TEXT NOT NULL DEFAULT 'user', updated_at TEXT NOT NULL,
          deleted INTEGER NOT NULL DEFAULT 0
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(topic,detail,content='memories',content_rowid='id');
        CREATE TRIGGER IF NOT EXISTS mem_insert AFTER INSERT ON memories BEGIN
          INSERT INTO memories_fts(rowid,topic,detail) VALUES(new.id,new.topic,new.detail);
        END;
        CREATE TRIGGER IF NOT EXISTS mem_delete AFTER DELETE ON memories BEGIN
          INSERT INTO memories_fts(memories_fts,rowid,topic,detail) VALUES('delete',old.id,old.topic,old.detail);
        END;
        CREATE TRIGGER IF NOT EXISTS mem_update AFTER UPDATE ON memories BEGIN
          INSERT INTO memories_fts(memories_fts,rowid,topic,detail) VALUES('delete',old.id,old.topic,old.detail);
          INSERT INTO memories_fts(rowid,topic,detail) VALUES(new.id,new.topic,new.detail);
        END;
        CREATE TABLE IF NOT EXISTS conversation_archive (
          id INTEGER PRIMARY KEY, ts TEXT NOT NULL, speaker TEXT NOT NULL, text TEXT NOT NULL
        );
        """)

def store(kind, payload):
    now = datetime.now(timezone.utc).isoformat()
    with connect() as db:
        if kind == "turn":
            text = str(payload.get("text",""))[:4096]
            speaker = str(payload.get("speaker",""))[:24]
            if text and speaker in ("user","assistant"):
                db.execute("INSERT INTO conversation_archive(ts,speaker,text) VALUES(?,?,?)",(now,speaker,text))
        elif kind == "remember":
            topic = str(payload.get("topic","")).strip()[:120]
            detail = str(payload.get("detail","")).strip()[:1000]
            if topic and detail:
                # Same topic updates the previous fact; prevents accumulating contradictions.
                old = db.execute("SELECT id FROM memories WHERE topic=? AND deleted=0 ORDER BY id DESC LIMIT 1",(topic,)).fetchone()
                if old:
                    db.execute("UPDATE memories SET detail=?,updated_at=?,source=? WHERE id=?",
                               (detail,now,"user",old[0]))
                else:
                    db.execute("INSERT INTO memories(topic,detail,source,updated_at) VALUES(?,?,?,?)",
                               (topic,detail,"user",now))
        elif kind == "forget":
            mid = payload.get("id")
            if isinstance(mid,int) and mid>0:
                db.execute("UPDATE memories SET deleted=1,updated_at=? WHERE id=?",(now,mid))

def writer():
    while True:
        kind, data = WRITE_Q.get()
        try:
            store(kind,data)
        except Exception as exc:
            print("memory write failed:",repr(exc),flush=True)
        finally:
            WRITE_Q.task_done()

def recall(query, limit=4):
    terms = re.findall(r"[\w]+",query,flags=re.UNICODE)[:12]
    if not terms:return []
    expr = " OR ".join('"'+t.replace('"','')+'"' for t in terms if t)
    if not expr:return []
    with connect() as db:
        rows = db.execute("""SELECT m.id,m.topic,m.detail,m.updated_at FROM memories_fts f
             JOIN memories m ON m.id=f.rowid WHERE memories_fts MATCH ? AND m.deleted=0
             ORDER BY bm25(memories_fts) LIMIT ?""",(expr,min(6,max(1,int(limit))))).fetchall()
    return [dict(zip(("id","topic","detail","updated_at"),row)) for row in rows]

class Handler(BaseHTTPRequestHandler):
    def _reply(self,status,obj):
        blob=json.dumps(obj,ensure_ascii=False).encode()
        self.send_response(status);self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length",str(len(blob)))
        self.end_headers();self.wfile.write(blob)
    def do_GET(self):
        if self.path=="/health":return self._reply(200,{"ok":True,"pending":WRITE_Q.qsize()})
        self._reply(404,{"error":"not_found"})
    def do_POST(self):
        if not TOKEN or self.headers.get("Authorization")!="Bearer "+TOKEN:
            return self._reply(401,{"error":"unauthorized"})
        try:
            length=int(self.headers.get("Content-Length","0"))
            limit = 420000 if self.path == "/speaker/identify" else MAX_BODY
            if length<2 or length>limit:return self._reply(413,{"error":"invalid_length"})
            data=json.loads(self.rfile.read(length))
            if not isinstance(data,dict):raise ValueError("Expected object")
            if self.path=="/speaker/identify":
                # Authenticated, bounded HTTP transport; never run on S3 audio.
                # No samples saved and no owner authorization granted.
                if os.environ.get("KITTY_SPEAKER_CPU_ENABLED") != "1":
                    return self._reply(503,{"error":"speaker_id_disabled"})
                try:
                    from kitty_speaker_cpu_v6 import identify
                    result=identify(data.get("audio_wav_b64"))
                    return self._reply(200,result)
                except (ValueError,binascii.Error):
                    return self._reply(400,{"error":"invalid_speaker_sample"})
                except (RuntimeError,ImportError,OSError):
                    return self._reply(503,{"error":"speaker_backend_unavailable"})
            if self.path in ("/owner/challenge","/owner/verify"):
                if OWNER_PROOF is None:
                    return self._reply(503,{"error":"owner_proof_disabled"})
                sid=data.get("session_id")
                if not isinstance(sid,str) or not 8<=len(sid)<=100:
                    return self._reply(400,{"error":"invalid_session"})
                if self.path=="/owner/challenge":
                    return self._reply(200,OWNER_PROOF.challenge(sid))
                result=OWNER_PROOF.verify(sid,data.get("challenge"),data.get("signature"))
                if not result:
                    return self._reply(403,{"error":"invalid_owner_proof"})
                return self._reply(200,{"grant":result,"expires_in":120})
            if self.path in ("/snapshot/chunk","/snapshot/finalize"):
                # Optional endpoint; only enabled when an isolated staging
                # directory is configured. Auth checked before this branch.
                base=os.environ.get("KITTY_SD_SNAPSHOT_ROOT","")
                if not base:
                    return self._reply(503,{"error":"snapshot_sync_disabled"})
                from kitty_sd_snapshot_v6 import SnapshotReceiver
                receiver=SnapshotReceiver(base)
                snapshot=data.get("snapshot")
                if self.path=="/snapshot/chunk":
                    encoded=data.get("data","")
                    if not isinstance(encoded,str) or len(encoded)>11000:
                        return self._reply(413,{"error":"chunk_too_large"})
                    try:
                        payload=base64.b64decode(encoded,validate=True)
                        offset=receiver.chunk(snapshot,data.get("name"),
                                              data.get("offset"),payload)
                    except (ValueError,binascii.Error,OSError) as exc:
                        return self._reply(400,{"error":"invalid_snapshot_chunk"})
                    return self._reply(200,{"next_offset":offset})
                try:
                    path=receiver.finalize(snapshot,data.get("manifest"))
                except (ValueError,OSError):
                    return self._reply(400,{"error":"invalid_snapshot_manifest"})
                # Indexing runs out-of-band; never delay the S3 uploader.
                queue_semantic_refresh(snapshot)
                return self._reply(200,{"finalized":True,"snapshot":snapshot})
            if self.path=="/calendar":
                # Parsing is CPU-only and bounded by the HTTP body. The clock
                # and timezone are explicit inputs; completion is never inferred.
                from kitty_calendar import interpret
                from datetime import datetime
                from zoneinfo import ZoneInfo
                zone=str(data.get("timezone","Asia/Tokyo"))[:64]
                now=datetime.now(ZoneInfo(zone))
                return self._reply(200,interpret(str(data.get("text",""))[:300],now,zone))
            if self.path=="/semantic/context":
                index=os.environ.get("KITTY_SEMANTIC_DB","")
                if not index or not os.path.isfile(index):
                    return self._reply(503,{"error":"semantic_index_unavailable"})
                sid=data.get("speaker_id")
                if not isinstance(sid,str) or not sid.strip() or sid=="unknown" or len(sid)>128:
                    return self._reply(400,{"error":"speaker_identity_required"})
                from kitty_memory_context_v6 import recall_context
                return self._reply(200,{"context":recall_context(
                    index,str(data.get("query",""))[:300],sid)})
            if self.path=="/semantic":
                # Optional local index, refreshed from a read-only SD export.
                # Disabled when the DB/model aren't configured.
                index=os.environ.get("KITTY_SEMANTIC_DB","")
                if not index or not os.path.isfile(index):
                    return self._reply(503,{"error":"semantic_index_unavailable"})
                from kitty_sd_semantic_index import search
                speaker_id = data.get("speaker_id")
                if (not isinstance(speaker_id,str) or not speaker_id.strip()
                    or speaker_id=="unknown" or len(speaker_id)>128):
                    return self._reply(400,{"error":"invalid_speaker_id"})
                return self._reply(200,{"results":search(
                    index,str(data.get("query",""))[:300],
                    speaker_id=speaker_id)})
            if self.path=="/recall":
                if not legacy_memory_enabled():
                    return self._reply(410,{"error":"legacy_ubuntu_memory_disabled"})
                return self._reply(200,{"memories":recall(str(data.get("query",""))[:500])})
            if self.path in ("/turn","/remember","/forget"):
                if not legacy_memory_enabled():
                    return self._reply(410,{"error":"legacy_ubuntu_memory_disabled"})
                try: WRITE_Q.put_nowait((self.path[1:],data))
                except queue.Full:return self._reply(503,{"error":"queue_full"})
                return self._reply(202,{"queued":True})
            return self._reply(404,{"error":"not_found"})
        except (ValueError,TypeError,json.JSONDecodeError,sqlite3.Error) as exc:
            return self._reply(400,{"error":str(exc)[:120]})
    def log_message(self,*args):pass

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--host",default="127.0.0.1")
    ap.add_argument("--port",type=int,default=8766)
    args=ap.parse_args()
    if not TOKEN:raise SystemExit("Set KITTY_MEMORY_TOKEN first")
    key_path=os.environ.get("KITTY_OWNER_PUBLIC_KEY_PEM","")
    signing_secret=os.environ.get("KITTY_OWNER_GRANT_SECRET_HEX","")
    if key_path and signing_secret:
        from kitty_owner_proof_v6 import OwnerProof
        try:
            secret=bytes.fromhex(signing_secret)
            with open(key_path,"rb") as fh: enrolled_key=fh.read()
            global OWNER_PROOF
            OWNER_PROOF=OwnerProof(secret,enrolled_key)
        except (ValueError,OSError) as exc:
            raise SystemExit("Invalid owner verification configuration") from exc
    if legacy_memory_enabled():
        init()
        threading.Thread(target=writer,daemon=True).start()
    if os.environ.get("KITTY_SEMANTIC_AUTO_REFRESH", "") == "1":
        if not os.environ.get("KITTY_SD_SNAPSHOT_ROOT") or not os.environ.get("KITTY_SEMANTIC_DB"):
            raise SystemExit("Auto refresh requires KITTY_SD_SNAPSHOT_ROOT and KITTY_SEMANTIC_DB")
        threading.Thread(target=semantic_refresh_worker,daemon=True).start()
    print("Kitty Memory storage ready",args.host,args.port,flush=True)
    ThreadingHTTPServer((args.host,args.port),Handler).serve_forever()
if __name__=="__main__":main()
