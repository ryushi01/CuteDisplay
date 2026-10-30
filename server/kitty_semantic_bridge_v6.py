#!/usr/bin/env python3
"""Bounded, optional semantic lookup for the Open WebUI gateway.

Never executes embeddings in an event-loop thread. Caller retains and uses
the already-available S3 local context on timeout, failure, or empty results.
"""
import asyncio
import json
import os
from urllib import request

MAX_CONTEXT_BYTES=600
DEFAULT_TIMEOUT_SEC=0.18

def _lookup(url, token, query, speaker_id, timeout):
    payload={"query":query[:300]}
    if speaker_id:
        payload["speaker_id"]=speaker_id
    req=request.Request(
        url.rstrip("/")+"/semantic",
        data=json.dumps(payload,ensure_ascii=False).encode("utf-8"),
        headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"},
        method="POST")
    with request.urlopen(req, timeout=timeout) as response:
        if response.status!=200:
            return []
        body=response.read(32769)
        if len(body)>32768:
            return []
        obj=json.loads(body)
        return obj.get("results",[]) if isinstance(obj,dict) else []

async def bounded_semantic_context(query, local_context, *,
                                   speaker_id=None, url=None, token=None,
                                   timeout=DEFAULT_TIMEOUT_SEC):
    """Return (context,source). Always fall back to S3 local context.

    Semantic results may be claims by someone else; include provenance so the
    assistant never silently considers them verified owner profile facts.
    """
    fallback=local_context or ""
    url=url or os.environ.get("KITTY_SEMANTIC_URL","")
    token=token or os.environ.get("KITTY_MEMORY_TOKEN","")
    if not url or not token or not query or not query.strip():
        return fallback,"local"
    timeout=max(0.025,min(float(timeout),0.5))
    try:
        results=await asyncio.wait_for(
            asyncio.to_thread(_lookup,url,token,query,speaker_id,timeout),
            timeout=timeout)
    except (Exception,asyncio.CancelledError):
        return fallback,"local"
    if not isinstance(results,list):
        return fallback,"local"
    fragments=[]
    budget=MAX_CONTEXT_BYTES
    for item in results[:4]:
        if not isinstance(item,dict) or not isinstance(item.get("text"),str):
            continue
        attribution=str(item.get("speaker_id","unknown"))[:128]
        provenance=str(item.get("provenance","unverified"))[:32]
        text=item["text"].replace("\r"," ").replace("\n"," ").strip()
        line=f"[source={attribution}; provenance={provenance}] {text}"
        raw=line.encode("utf-8")
        if len(raw)>budget:
            continue
        fragments.append(line)
        budget-=len(raw)+1
    if not fragments:
        return fallback,"local"
    # Preserve existing S3 memory as the primary context. Trim semantic slice
    # rather than dropping S3 facts to fit an LLM prompt.
    return fallback+"\nRelevant unverified historical excerpts:\n"+"\n".join(fragments),"hybrid"
