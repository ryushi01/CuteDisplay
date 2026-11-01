"""Offline end-to-end OTA protocol simulator, never connects to hardware."""
import hashlib
import hmac
from kitty_ota_frames_v6 import chunk_frame, start_frame

def simulate(image, key, nonce, slot_bytes):
    if len(key)!=32 or len(nonce)!=16 or len(image)>slot_bytes:
        raise ValueError("invalid transfer parameters or image too large")
    if not image or image[0]!=0xe9: raise ValueError("ESP app header missing")
    sha=hashlib.sha256(image).hexdigest()
    start_frame(len(image),sha)
    stored=bytearray()
    for pos in range(0,len(image),48):
        line=chunk_frame(key,nonce,pos,image[pos:pos+48])
        parts=line.split(" ")
        if len(parts)!=4 or int(parts[1],16)!=len(stored):
            raise ValueError("out of order frame")
        payload=bytes.fromhex(parts[2])
        signature=hmac.new(key,nonce+len(stored).to_bytes(4,"big")+payload,hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(parts[3],signature):raise ValueError("invalid frame signature")
        stored.extend(payload)
    if len(stored)!=len(image) or hashlib.sha256(stored).hexdigest()!=sha:
        raise ValueError("image digest mismatch")
    return {"frames":(len(image)+47)//48,"image_bytes":len(image),
            "sha256":sha,"simulated_valid":True,"hardware_flash_performed":False,
            "deploy_authorized":False}
