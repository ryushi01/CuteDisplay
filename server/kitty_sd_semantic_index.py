#!/usr/bin/env python3
"""Optional multilingual semantic search over SD-exported Kitty memory.

Runs on Ubuntu/Mac, not ESP32 audio tasks. Data is sourced from a read-only
copy of Kitty's SD TSV files; the microSD remains canonical. No automatic
migration, deletion, upload, or network model calls are performed.
"""
import argparse, json, math, os, pathlib, sqlite3
from datetime import datetime

def load_rows(sd):
    sd=pathlib.Path(sd)
    for filename in ("facts.tsv","dated_plans.tsv","summaries.tsv","conversations.tsv"):
        path=sd/"kitty"/filename
        if not path.is_file():continue
        with path.open(encoding="utf-8",errors="replace") as f:
            for i,line in enumerate(f):
                parts=line.rstrip("\n").split("\t")
                if filename=="facts.tsv" and len(parts)>=2:
                    key,text=parts[0],parts[1]
                elif filename=="dated_plans.tsv" and len(parts)>=3:
                    key,text=parts[1],parts[2]
                elif filename=="summaries.tsv" and len(parts)>=2:
                    key,text="summary:"+parts[0],parts[1]
                elif filename=="conversations.tsv" and len(parts)>=3:
                    key,text="conversation:"+parts[0],parts[1]+" "+parts[2]
                else:continue
                if key and text:
                    yield f"{filename}:{i}:{key}",f"{key}: {text}"

def build(sd,out,model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"):
    from sentence_transformers import SentenceTransformer
    model=SentenceTransformer(model_name,device="cpu")
    rows=list(load_rows(sd))
    db=sqlite3.connect(out)
    db.execute("CREATE TABLE IF NOT EXISTS vectors (id TEXT PRIMARY KEY,text TEXT NOT NULL,embedding TEXT NOT NULL)")
    db.execute("DELETE FROM vectors")
    for start in range(0,len(rows),64):
        chunk=rows[start:start+64]
        embeds=model.encode([x[1] for x in chunk],normalize_embeddings=True,batch_size=16)
        db.executemany("INSERT INTO vectors VALUES (?,?,?)",[
            (item[0],item[1],json.dumps(vec.tolist(),separators=(",",":"))) for item,vec in zip(chunk,embeds)])
    db.commit();db.close()
    return len(rows)

def search(db_path,query,k=5,model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"):
    from sentence_transformers import SentenceTransformer
    import numpy as np
    model=SentenceTransformer(model_name,device="cpu")
    query_vec=model.encode([query],normalize_embeddings=True)[0]
    db=sqlite3.connect(db_path)
    scores=[]
    for id,text,raw in db.execute("SELECT id,text,embedding FROM vectors"):
        vec=np.array(json.loads(raw),dtype="float32")
        score=float(np.dot(query_vec,vec))
        scores.append((score,id,text))
    db.close()
    return [{"score":round(score,4),"id":id,"text":text} for score,id,text in sorted(scores,reverse=True)[:max(1,min(k,10))]]

def main():
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest="command",required=True)
    a=sub.add_parser("build");a.add_argument("--sd-copy",required=True);a.add_argument("--db",required=True)
    b=sub.add_parser("search");b.add_argument("--db",required=True);b.add_argument("--query",required=True);b.add_argument("--limit",type=int,default=5)
    x=ap.parse_args()
    if x.command=="build":print(json.dumps({"indexed":build(x.sd_copy,x.db)}))
    else:print(json.dumps({"results":search(x.db,x.query,x.limit)},ensure_ascii=False))
if __name__=="__main__":main()
