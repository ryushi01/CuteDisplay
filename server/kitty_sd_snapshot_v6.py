#!/usr/bin/env python3
"""V6 append-only SD-export receiver with authenticated, resumable sessions.

Receives file *bytes* as sequential chunks; writes only a staging snapshot.
A SHA-256-verified manifest finalizes the copy atomically. Never touches S3.
Authorization (bearer token) and TLS/mTLS transport are caller responsibilities.
"""
import hashlib
import os
from pathlib import Path

FILES = {"facts.tsv", "factsmeta.tsv", "dated_plans.tsv", "summaries.tsv",
         "conversations.tsv", "turn_sources.tsv", "voice_profiles_v6.json", "speaker_claims_v6.tsv"}
MAX_CHUNK = 8192
MAX_FILE = 256 * 1024 * 1024

class SnapshotReceiver:
    def __init__(self, root):
        self.root=Path(root).resolve()
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        if self.root.is_symlink():
            raise ValueError('snapshot root cannot be a symlink')
    @staticmethod
    def valid_id(snapshot):
        return isinstance(snapshot,str) and 8<=len(snapshot)<=64 and all(c.isascii() and (c.isalnum() or c in "_-") for c in snapshot)
    def _file(self, snapshot, name):
        if not self.valid_id(snapshot) or name not in FILES:
            raise ValueError("invalid snapshot or filename")
        path=self.root/("staging-"+snapshot)/"kitty"
        path.mkdir(mode=0o700,parents=True,exist_ok=True)
        if path.is_symlink():
            raise ValueError("symlinked snapshot path")
        return path/name
    def chunk(self,snapshot,name,offset,data):
        if not isinstance(data,bytes) or len(data)>MAX_CHUNK or not isinstance(offset,int) or offset<0 or offset+len(data)>MAX_FILE:
            raise ValueError("invalid chunk")
        path=self._file(snapshot,name)
        flags=os.O_CREAT|os.O_RDWR|getattr(os,"O_NOFOLLOW",0)
        fd=os.open(path,flags,0o600)
        try:
            with os.fdopen(fd,"r+b",closefd=False) as f:
                f.seek(0,2)
                current=f.tell()
                if offset<current:
                    if offset+len(data)>current:
                        raise ValueError("partial chunk replay")
                    f.seek(offset)
                    if f.read(len(data))!=data:
                        raise ValueError("replayed chunk differs")
                    return current
                if offset!=current:
                    raise ValueError("gap in upload")
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
                return current+len(data)
        finally:
            os.close(fd)
    def finalize(self,snapshot,manifest):
        if not self.valid_id(snapshot) or not isinstance(manifest,dict) or not manifest or set(manifest)-FILES:
            raise ValueError("invalid manifest")
        base=self.root/("staging-"+snapshot)
        for name,desc in manifest.items():
            if not isinstance(desc,dict) or set(desc)!={"size","sha256"}:
                raise ValueError("invalid descriptor")
            size,digest=desc["size"],desc["sha256"]
            if not isinstance(size,int) or not 0<=size<=MAX_FILE or not isinstance(digest,str) or len(digest)!=64:
                raise ValueError("invalid checksum")
            path=self._file(snapshot,name)
            if not path.is_file() or path.stat().st_size!=size:
                raise ValueError("incomplete snapshot")
            h=hashlib.sha256()
            with path.open("rb") as f:
                for block in iter(lambda:f.read(65536),b""):
                    h.update(block)
            if h.hexdigest()!=digest:
                raise ValueError("checksum mismatch")
        # Require the full canonical file manifest to safely propagate deletions.
        actual={p.name for p in (base/"kitty").iterdir() if p.is_file()}
        if actual != set(manifest):
            raise ValueError("undeclared or missing files")
        complete=self.root/("snapshot-"+snapshot)
        if complete.exists():
            # A lost HTTP acknowledgement must not create another snapshot or
            # turn a successfully finalized upload into an error. Verify that
            # *all* manifest bytes agree before accepting this as a retry.
            for name, desc in manifest.items():
                existing = complete / "kitty" / name
                if not existing.is_file() or existing.is_symlink() or existing.stat().st_size != desc["size"]:
                    raise ValueError("snapshot id reused with different content")
                h = hashlib.sha256()
                with existing.open("rb") as f:
                    for block in iter(lambda: f.read(65536), b""):
                        h.update(block)
                if h.hexdigest() != desc["sha256"]:
                    raise ValueError("snapshot id reused with different content")
            if {p.name for p in (complete / "kitty").iterdir() if p.is_file()} != set(manifest):
                raise ValueError("snapshot manifest differs")
            # The staging copy is not removed here: cleanup is a separate,
            # conservative operation and cannot race an in-flight uploader.
            return str(complete)
        os.rename(base,complete)
        return str(complete)
