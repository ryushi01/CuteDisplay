#pragma once
// Kitty V6 OTA receiver session. Explicitly disabled in shipped builds.
// The authenticated, same-subnet LAN socket supplies commands; this class
// never listens on a public interface or changes boot target.
#include <Arduino.h>
#include <mbedtls/sha256.h>
#include "KittyOTAWriter.h"
#include "KittyOTAFrames.h"

#ifndef KITTY_V6_ENABLE_OTA_TRANSPORT
#define KITTY_V6_ENABLE_OTA_TRANSPORT 0
#endif

namespace KittyOTASession {
class Receiver {
 KittyOTAWriter::Session writer;
 uint8_t key[32]={0};
 uint8_t nonce[16]={0};
 uint32_t expected=0;
 uint32_t offset=0;
 uint32_t lastActivity=0;
 bool transferring=false;
 void reset(){
  writer.abort();transferring=false;expected=offset=0;
  memset(key,0,sizeof(key));memset(nonce,0,sizeof(nonce));
 }
public:
 Receiver()=default;
 Receiver(const Receiver&)=delete;
 Receiver& operator=(const Receiver&)=delete;
 ~Receiver(){reset();}
 bool active()const{return transferring;}
 uint32_t progress()const{return offset;}
 void cancel(){reset();}
 void tick(){
  if(transferring && (uint32_t)(millis()-lastActivity)>15000UL)reset();
 }
 bool begin(uint32_t size,const uint8_t sha[32],const uint8_t secret[32],
            const uint8_t challenge[16],bool idle){
#if KITTY_V6_ENABLE_OTA_TRANSPORT
  if(transferring||!idle||!secret||!challenge||!sha)return false;
  reset();
  if(!writer.begin(size,sha,idle))return false;
  memcpy(key,secret,32);memcpy(nonce,challenge,16);
  expected=size;offset=0;lastActivity=millis();transferring=true;
  return true;
#else
  (void)size;(void)sha;(void)secret;(void)challenge;(void)idle;
  return false;
#endif
 }
 bool append(const String &line,bool idle){
#if KITTY_V6_ENABLE_OTA_TRANSPORT
  if(!transferring || !idle){reset();return false;}
  uint8_t bytes[KittyOTAFrames::CHUNK_BYTES]={0};
  size_t n=0;
  if(!KittyOTAFrames::verifyFrame(line,key,nonce,offset,bytes,n)||
     n>expected-offset || !writer.append(bytes,n)){reset();return false;}
  offset+=(uint32_t)n;lastActivity=millis();return true;
#else
  (void)line;(void)idle;return false;
#endif
 }
 bool finish(bool idle){
#if KITTY_V6_ENABLE_OTA_TRANSPORT
  if(!transferring || !idle || offset!=expected){reset();return false;}
  bool ok=writer.complete(idle);
  transferring=false;memset(key,0,sizeof(key));memset(nonce,0,sizeof(nonce));
  return ok; // Verified, but does not authorize boot or reboot.
#else
  (void)idle;return false;
#endif
 }
 // No exposed commit/reboot action: receiver cannot switch boot partitions.
};
}
