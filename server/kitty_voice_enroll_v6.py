#!/usr/bin/env python3
"""Consent-based offline voice enrollment into an SD-canonical profile file.

Use three or more recordings made with Kitty's microphone, mono PCM16 16kHz,
2-8 s each. Only vectors persist; WAVs remain wherever the operator placed
them and should be deleted securely according to their retention policy.
"""
import argparse,json,os
from pathlib import Path
from kitty_voice_id_v6 import pcm16_from_wav,embedding
from kitty_voice_profiles_sd_v6 import validate_profiles

def enroll(profile_file,speaker_id,wavs,consent):
    if consent is not True:
        raise PermissionError("explicit consent required")
    if not isinstance(speaker_id,str) or not speaker_id.startswith("person:") or not 8<=len(speaker_id)<=64 or any(c in speaker_id for c in "\t\r\n"):
        raise ValueError("invalid stable speaker id")
    if not 3<=len(wavs)<=12:
        raise ValueError("need 3 to 12 recordings")
    vectors=[]
    for file in wavs:
        raw=Path(file).read_bytes()
        vectors.append(embedding(pcm16_from_wav(raw)).astype(float).tolist())
    path=Path(profile_file)
    data={"version":1,"speakers":{}}
    if path.exists():
        data=json.loads(path.read_text(encoding="utf-8"))
        validate_profiles(data)
    data["speakers"][speaker_id]={"consent":True,"vectors":vectors}
    validate_profiles(data)
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+".next")
    with tmp.open("w",encoding="utf-8") as f:
        os.fchmod(f.fileno(),0o600)
        json.dump(data,f,ensure_ascii=False,separators=(",",":"))
        f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)
    return len(vectors)

def delete(profile_file,speaker_id):
    path=Path(profile_file)
    data=json.loads(path.read_text(encoding="utf-8"))
    validate_profiles(data)
    if speaker_id not in data["speakers"]:
        return False
    del data["speakers"][speaker_id]
    tmp=path.with_name(path.name+".next")
    with tmp.open("w",encoding="utf-8") as f:
        os.fchmod(f.fileno(),0o600)
        json.dump(data,f,ensure_ascii=False,separators=(",",":"))
        f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)
    return True

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--profile",required=True)
    actions=ap.add_mutually_exclusive_group(required=True)
    actions.add_argument("--enroll",metavar="SPEAKER_ID")
    actions.add_argument("--delete",metavar="SPEAKER_ID")
    ap.add_argument("--consent",action="store_true")
    ap.add_argument("wavs",nargs="*")
    a=ap.parse_args()
    if a.enroll:
        print(json.dumps({"enrolled":a.enroll,"samples":enroll(a.profile,a.enroll,a.wavs,a.consent)}))
    else:
        if a.wavs:ap.error("delete takes no WAV files")
        print(json.dumps({"deleted":delete(a.profile,a.delete)}))
if __name__=="__main__":main()
