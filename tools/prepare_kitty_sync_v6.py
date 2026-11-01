#!/usr/bin/env python3
"""Prepare local-only S3 sync configuration; never print or commit the token.

Provide a private bearer token file (same value as KITTY_SYNC_DEVICE_TOKEN)
and public Ragnarok trust anchor. Use the generated header ONLY in trusted local builds.
"""
import argparse
import json
import os
from pathlib import Path

def prepare(cert, token, output, url):
    if url != "https://ragnarok-project.com/kitty-v6/sync":
        raise ValueError("S3 sync must use ragnarok-project.com HTTPS port 443")
    certificate=Path(cert).read_text(encoding="ascii")
    secret=Path(token).read_text(encoding="ascii").strip()
    if "-----BEGIN CERTIFICATE-----" not in certificate or "-----END CERTIFICATE-----" not in certificate:
        raise ValueError("invalid TLS certificate")
    if len(secret)<32 or any(c.isspace() for c in secret):
        raise ValueError("invalid device bearer token")
    output=Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing to overwrite existing private header")
    output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    data=("#pragma once\n"
          "#define KITTY_SYNC_V6_URL "+json.dumps(url)+"\n"
          "#define KITTY_SYNC_V6_DEVICE_TOKEN "+json.dumps(secret)+"\n"
          "#define KITTY_SYNC_V6_CA_PEM "+json.dumps(certificate)+"\n")
    fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as file:file.write(data)
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    return output

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--cert",required=True)
    parser.add_argument("--token-file",required=True)
    parser.add_argument("--output",required=True)
    parser.add_argument("--url",default="https://ragnarok-project.com/kitty-v6/sync")
    args=parser.parse_args()
    result=prepare(args.cert,args.token_file,args.output,args.url)
    print("Private S3 sync header created:",result)
    print("Do not upload this file, or the resulting credential-bearing firmware, to public CI.")

if __name__=="__main__":main()
