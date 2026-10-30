#pragma once
// Kitty V6 ESP32-S3 inactive-slot OTA writer.
// The transport MUST supply authenticated, verified bytes; this class does not
// expose a network endpoint or start an update on its own.
#include <Arduino.h>
#include <esp_ota_ops.h>
#include <esp_partition.h>
#include <mbedtls/sha256.h>
#include <cstring>
#include "KittyOTASafety.h"

namespace KittyOTAWriter {
enum class State : uint8_t { Idle, Receiving, Ready, Failed };
class Session {
 esp_ota_handle_t handle=0;
 const esp_partition_t *target=nullptr;
 uint32_t expectedSize=0;
 uint32_t received=0;
 uint8_t expectedDigest[32]={0};
 mbedtls_sha256_context digest;
 bool digestReady=false;
 State state=State::Idle;
 void stopDigest(){
  if(digestReady){mbedtls_sha256_free(&digest);digestReady=false;}
 }
 void fail(){
  if(handle){esp_ota_abort(handle);handle=0;}
  stopDigest();state=State::Failed;
 }
public:
 Session()=default;
 Session(const Session&)=delete;
 Session& operator=(const Session&)=delete;
 ~Session(){abort();}
 State status()const{return state;}
 uint32_t bytesReceived()const{return received;}
 bool begin(uint32_t imageBytes,const uint8_t sha256[32],bool systemIdle){
  if(state==State::Receiving || !systemIdle || !sha256 ||
     !KittyOTASafety::fitsInactiveSlot(imageBytes))return false;
  abort();
  target=esp_ota_get_next_update_partition(nullptr);
  if(!target || imageBytes>target->size)return false;
  if(esp_ota_begin(target,imageBytes,&handle)!=ESP_OK){handle=0;return false;}
  expectedSize=imageBytes;received=0;
  memcpy(expectedDigest,sha256,sizeof(expectedDigest));
  mbedtls_sha256_init(&digest);digestReady=true;
  if(mbedtls_sha256_starts(&digest,0)!=0){fail();return false;}
  state=State::Receiving;
  return true;
 }
 bool append(const uint8_t *bytes,size_t count){
  if(state!=State::Receiving || !bytes || !count ||
     count>4096 || count>expectedSize-received)return false;
  if(esp_ota_write(handle,bytes,count)!=ESP_OK){fail();return false;}
  if(mbedtls_sha256_update(&digest,bytes,count)!=0){fail();return false;}
  received+=(uint32_t)count;
  return true;
 }
 bool complete(bool stillIdle){
  if(state!=State::Receiving || !stillIdle || received!=expectedSize)return false;
  uint8_t actual[32];
  if(mbedtls_sha256_finish(&digest,actual)!=0){fail();return false;}
  stopDigest();
  if(memcmp(actual,expectedDigest,sizeof(actual))!=0){fail();return false;}
  if(esp_ota_end(handle)!=ESP_OK){handle=0;state=State::Failed;return false;}
  handle=0;state=State::Ready;
  // Deliberately does NOT set boot partition or reboot.
  return true;
 }
 bool armBoot(bool explicitAuthorization){
  if(state!=State::Ready || !explicitAuthorization || !target)return false;
  if(esp_ota_set_boot_partition(target)!=ESP_OK){state=State::Failed;return false;}
  state=State::Idle;
  return true;
 }
 void abort(){
  if(handle)esp_ota_abort(handle);
  handle=0;stopDigest();state=State::Idle;target=nullptr;
  expectedSize=received=0;
  memset(expectedDigest,0,sizeof(expectedDigest));
 }
};
} // namespace KittyOTAWriter
