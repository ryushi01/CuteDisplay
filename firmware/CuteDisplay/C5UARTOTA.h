#pragma once
// ESP32-C5 application OTA over the EXISTING C5 GPIO1 RX / GPIO6 TX UART.
// Requires Arduino-ESP32 3.3.12+ and a two-slot OTA partition layout.
// The bootloader is NOT modified. On error the running image remains.
#include <Arduino.h>
#include <Update.h>
#include <esp_ota_ops.h>
#include <esp_partition.h>
#include "CuteLink.h"
#include "C5FirmwareVersion.h"

void c5OTARedraw(); // implemented by lcd.ino

namespace C5UARTOTA {
enum Phase : uint8_t { IDLE, RECEIVING, INSTALLING, ERROR };
static Phase phase=IDLE;
static uint32_t imageBytes=0,received=0,startedAt=0,lastDataAt=0,targetVersion=0,errorAt=0;
static uint32_t previousOffset=UINT32_MAX;
static uint16_t previousLength=0;
static uint8_t lastPercent=255;
static String expectedHash,errorMessage;

inline bool active(){return phase==RECEIVING||phase==INSTALLING;}
inline int percent(){return imageBytes?int((uint64_t(received)*100)/imageBytes):0;}
inline const String &error(){return errorMessage;}
inline void respond(Stream &serial,uint16_t seq,bool ok,const char *what){
 CuteLink::send(serial,seq,ok?"OTA_ACK":"OTA_NACK",what);
}
inline int unhex(char x){
 if(x>='0'&&x<='9')return x-'0';
 if(x>='a'&&x<='f')return x-'a'+10;
 if(x>='A'&&x<='F')return x-'A'+10;
 return -1;
}
inline void fail(const char *message){
 if(active())Update.abort();
 phase=ERROR;errorMessage=message;errorAt=millis();
 imageBytes=0;received=0;previousOffset=UINT32_MAX;
 Serial.printf("[C5 OTA] Failed: %s (old app retained)\n",message);
 c5OTARedraw();
}
inline void clear(){
 if(active())Update.abort();
 phase=IDLE;errorMessage="";imageBytes=0;received=0;
 targetVersion=0;previousOffset=UINT32_MAX;previousLength=0;
 c5OTARedraw();
}
inline void onFrame(Stream &uart,const CuteLink::Frame &f){
 if(f.type=="OTA_QUERY"){
  const esp_partition_t *slot=esp_ota_get_next_update_partition(nullptr);
  String info=String(C5_FIRMWARE_VERSION)+","+String(slot?slot->size:0)+",160";
  CuteLink::send(uart,f.seq,"OTA_INFO",info);
  return;
 }
 if(f.type=="OTA_ABORT"){clear();respond(uart,f.seq,true,"ABORT");return;}
 if(f.type=="OTA_BEGIN"){
  int a=f.payload.indexOf(','),b=f.payload.lastIndexOf(',');
  if(a<1||b<=a+1){respond(uart,f.seq,false,"FORMAT");return;}
  String vs=f.payload.substring(0,a),bs=f.payload.substring(a+1,b);
  String sha=f.payload.substring(b+1);
  if(vs.length()>10||bs.length()>10||sha.length()!=64){
   respond(uart,f.seq,false,"FORMAT");return;
  }
  for(size_t i=0;i<vs.length();++i)if(vs[i]<'0'||vs[i]>'9'){
   respond(uart,f.seq,false,"VERSION");return;
  }
  for(size_t i=0;i<bs.length();++i)if(bs[i]<'0'||bs[i]>'9'){
   respond(uart,f.seq,false,"SIZE");return;
  }
  for(size_t i=0;i<sha.length();++i)if(unhex(sha[i])<0){
   respond(uart,f.seq,false,"HASH");return;
  }
  uint32_t newVersion=strtoul(vs.c_str(),nullptr,10);
  uint32_t nbytes=strtoul(bs.c_str(),nullptr,10);
  if(phase==RECEIVING && newVersion==targetVersion && nbytes==imageBytes &&
     sha.equalsIgnoreCase(expectedHash)){
   // Safe if the original BEGIN acknowledgment was lost.
   respond(uart,f.seq,true,"BEGIN");return;
  }
  if(active()){respond(uart,f.seq,false,"BUSY");return;}
  const esp_partition_t *slot=esp_ota_get_next_update_partition(nullptr);
  if(newVersion<=C5_FIRMWARE_VERSION){respond(uart,f.seq,false,"OLD");return;}
  if(!slot||nbytes<1024||nbytes>slot->size){
   respond(uart,f.seq,false,"NO_SLOT");return;
  }
  if(!Update.begin(nbytes,U_FLASH)){
   respond(uart,f.seq,false,"BEGIN");return;
  }
  if(!Update.setSHA256(sha.c_str())){
   Update.abort();respond(uart,f.seq,false,"SHA_SETUP");return;
  }
  phase=RECEIVING;imageBytes=nbytes;received=0;startedAt=millis();lastDataAt=startedAt;
  targetVersion=newVersion;expectedHash=sha;previousOffset=UINT32_MAX;
  previousLength=0;lastPercent=255;errorMessage="";
  Serial.printf("[C5 OTA] Receiving target v%lu, %lu bytes\n",
      (unsigned long)targetVersion,(unsigned long)imageBytes);
  c5OTARedraw();
  respond(uart,f.seq,true,"BEGIN");return;
 }
 if(f.type=="OTA_DATA"){
  if(phase!=RECEIVING){respond(uart,f.seq,false,"NOT_STARTED");return;}
  if(f.payload.length()<11||f.payload.length()>329||f.payload[8]!=','||
     ((f.payload.length()-9)%2)!=0){
   respond(uart,f.seq,false,"FORMAT");return;
  }
  uint32_t offset=0;
  for(int j=0;j<8;++j){
   int d=unhex(f.payload[j]);
   if(d<0){respond(uart,f.seq,false,"OFFSET");return;}
   offset=(offset<<4)|(uint32_t)d;
  }
  size_t n=(f.payload.length()-9)/2;
  if(n<1||n>160){respond(uart,f.seq,false,"SIZE");return;}
  if(offset==previousOffset && n==previousLength && offset+n==received){
   respond(uart,f.seq,true,"DATA");return;
  }
  if(offset!=received||received+n>imageBytes){
   respond(uart,f.seq,false,"OFFSET");return;
  }
  uint8_t buffer[160];
  for(size_t j=0;j<n;++j){
   int hi=unhex(f.payload[9+j*2]),lo=unhex(f.payload[10+j*2]);
   if(hi<0||lo<0){respond(uart,f.seq,false,"HEX");return;}
   buffer[j]=(uint8_t)((hi<<4)|lo);
  }
  if(Update.write(buffer,n)!=n){
   fail("FLASH_WRITE");respond(uart,f.seq,false,"WRITE");return;
  }
  received+=n;lastDataAt=millis();previousOffset=offset;previousLength=n;
  uint8_t progress=uint8_t(percent());
  if(lastPercent==255||progress>=lastPercent+2||progress==100){
   lastPercent=progress;c5OTARedraw();
  }
  respond(uart,f.seq,true,"DATA");return;
 }
 if(f.type=="OTA_END"){
  if(phase!=RECEIVING){respond(uart,f.seq,false,"NOT_STARTED");return;}
  if(received!=imageBytes){
   respond(uart,f.seq,false,"INCOMPLETE");return;
  }
  phase=INSTALLING;
  c5OTARedraw();
  if(!Update.end(false)){
   Serial.printf("[C5 OTA] Verification failed: %s\n",Update.errorString());
   fail("VERIFY");respond(uart,f.seq,false,"VERIFY");return;
  }
  Serial.printf("[C5 OTA] Complete; rebooting target v%lu\n",
      (unsigned long)targetVersion);
  respond(uart,f.seq,true,"REBOOT");
  uart.flush();delay(400);
  ESP.restart();
 }
}
inline void tick(){
 // Recover automatically if the S3 lost OTA_BEGIN ACK or stopped
 // sending DATA. A stalled inactive OTA slot must not trap the display.
 if(phase==RECEIVING && (uint32_t)(millis()-lastDataAt)>45000UL)
  fail(received==0?"START_STALLED":"TRANSFER_STALLED");
 if(phase==ERROR && (uint32_t)(millis()-errorAt)>10000UL)clear();
}
} // namespace C5UARTOTA
