#!/usr/bin/env python3
"""Read S3 conversation attribution without modifying legacy conversations.tsv.

Sidecar rows (v1): timestamp<TAB>archive_byte_offset<TAB>speaker_id<TAB>
speaker_role<TAB>provenance. The S3 currently emits unknown/unknown/unverified.
Legacy turns have no sidecar and are *unknown*, never automatically owner.
"""
from pathlib import Path

UNKNOWN = {"speaker_id": "unknown", "speaker_role": "unknown",
           "provenance": "unverified"}

def read_sidecar(sd_root):
    root=Path(sd_root)/"kitty"
    mapping={}
    source=root/"turn_sources.tsv"
    if not source.is_file():
        return mapping
    with source.open("r",encoding="utf-8",errors="replace") as stream:
        for line in stream:
            cols=line.rstrip("\r\n").split("\t")
            if len(cols)!=5:
                continue
            stamp, offset, speaker_id, role, provenance=cols
            if not stamp.isdecimal() or not offset.isdecimal():
                continue
            if not speaker_id or len(speaker_id)>128:
                continue
            if role not in ("unknown","guest","owner","remote_ai","kitty"):
                continue
            if provenance not in ("unverified","explicit_introduction",
                                  "explicit_correction","session_verified"):
                continue
            # Never treat an unauthenticated, SD-editable sidecar as proof of
            # owner verification. Verified owner attribution requires trusted
            # session provenance handled in a future authenticated protocol.
            if role=="owner":
                continue
            mapping[(int(stamp),int(offset))] = {
                "speaker_id":speaker_id,
                "speaker_role":role,
                "provenance":provenance
            }
    return mapping

def iter_archive_with_speakers(sd_root):
    root=Path(sd_root)/"kitty"
    archive=root/"conversations.tsv"
    if not archive.is_file():
        return
    annotations=read_sidecar(sd_root)
    with archive.open("rb") as stream:
        line_number=0
        while True:
            # Record the byte offset before readline; buffered iterator's
            # tell() is not supported after implicit iteration on many Pythons.
            offset=stream.tell()
            raw=stream.readline()
            if not raw:
                break
            # Raw-byte offsets match FAT SD_MMC::File.position().
            current_line=line_number
            line_number+=1
            parts=raw.rstrip(b"\r\n").decode("utf-8",errors="replace").split("\t")
            if len(parts)<3:
                continue
            stamp, question, answer=parts[0],parts[1],parts[2]
            identity=annotations.get((int(stamp),offset),UNKNOWN) if stamp.isdecimal() else UNKNOWN
            yield {
                "id":f"conversations.tsv:{current_line}:conversation:{stamp}",
                "offset":offset, "timestamp":stamp,
                "text":f"conversation:{stamp}: {question} {answer}",
                **identity
            }
