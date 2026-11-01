#!/usr/bin/env python3
"""Kitty V6 authenticated LAN OTA client (disabled by default on S3).

Never switches boot partition. --execute requires an explicit operator opt-in.
S3 firmware must separately enable OTA transport and verify rollback capability.
LAN protocol has HMAC integrity but NO encryption; use trusted local LAN only.
"""
import argparse
import getpass
import hashlib
import hmac
import ipaddress
import json
import socket
from pathlib import Path

from kitty_ota_frames_v6 import chunk_frame, decode_key, start_frame

def read_line(f, limit=256):
    line=f.readline(limit+1)
    if not line or len(line)>limit or not line.endswith(b"\n"):
        raise ValueError("missing or invalid S3 response")
    return line.rstrip(b"\r\n").decode("ascii")

def connect_and_upload(host, key, image, port=8848):
    address=ipaddress.ip_address(host)
    if not address.is_private:
        raise ValueError("S3 target must be private LAN IP")
    digest=hashlib.sha256(image).hexdigest()
    with socket.create_connection((host,port),timeout=10) as sock:
        sock.settimeout(20)
        with sock.makefile("rwb",buffering=0) as file:
            greeting=read_line(file)
            if not greeting.startswith("CHALLENGE ") or len(greeting)!=42:
                raise ValueError("invalid challenge")
            challenge=bytes.fromhex(greeting[10:])
            mac=hmac.new(key,greeting[10:].encode("ascii"),hashlib.sha256).hexdigest()
            file.write(("AUTH "+mac+"\n").encode("ascii"))
            if read_line(file)!="OK":
                raise ValueError("S3 authorization rejected")
            file.write(b"OTA_STATUS\n")
            status=[read_line(file) for _ in range(4)]
            if "OTA:TRANSFER_ENABLED:1" not in status or "OTA:ROLLBACK_SUPPORTED:1" not in status:
                raise ValueError("S3 receiver or rollback support disabled")
            file.write((start_frame(len(image),digest)+"\n").encode())
            ready=read_line(file)
            if not ready.startswith("OTA:READY:") or len(ready)!=42:
                raise ValueError("OTA BEGIN refused: "+ready)
            nonce=bytes.fromhex(ready[10:])
            try:
                for offset in range(0,len(image),48):
                    line=chunk_frame(key,nonce,offset,image[offset:offset+48])
                    file.write((line+"\n").encode("ascii"))
                    result=read_line(file)
                    if result!=f"OTA:ACK:{min(offset+48,len(image))}":
                        raise ValueError("OTA DATA failed: "+result)
                file.write(b"OTA_FINISH\n")
                end=read_line(file)
                if end!="OTA:VERIFIED_NO_BOOT_SWITCH":
                    raise ValueError("OTA FINISH failed: "+end)
            except Exception:
                try:file.write(b"OTA_ABORT\n")
                except OSError:pass
                raise
    return {"verified":True,"bytes":len(image),"sha256":digest,
            "boot_switched":False,"reboot_triggered":False}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--host",required=True)
    p.add_argument("--image",type=Path,required=True)
    p.add_argument("--execute",action="store_true",help="Explicitly send firmware to inactive slot; never boot it")
    args=p.parse_args()
    image=args.image.read_bytes()
    if len(image)<1024 or image[0]!=0xe9:
        raise SystemExit("Not an ESP32 application image")
    result={"size":len(image),"sha256":hashlib.sha256(image).hexdigest(),
            "mode":"execute-inactive-slot-only" if args.execute else "dry-run"}
    print(json.dumps(result,indent=2))
    if not args.execute:
        print("Dry run only. No network connection or flash writes.")
        return
    key=decode_key(getpass.getpass("S3 LAN secret (64 hex; hidden): ").strip())
    print(json.dumps(connect_and_upload(args.host,key,image),indent=2))

if __name__=="__main__":
    main()
