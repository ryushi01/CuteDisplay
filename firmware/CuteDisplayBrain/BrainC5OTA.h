#pragma once
// S3 sends a separately compiled ESP32-C5 application to the C5 over
// the proven GPIO47/21 ↔ GPIO1/6 UART. Never uses the C5 ROM downloader.
#include <Arduino.h>
#include "CuteLink.h"
#include "C5FirmwareImage.h"
namespace BrainC5OTA {
enum Stage :uint8_t { IDLE, QUERY, READY, BEGIN, DATA, END, WAIT_BOOT, DONE, FAILED };
static Stage stage=IDLE;
static uint16_t seq=40000,pending=0;
static uint32_t targetSize=0,position=0,lastSent=0,waitSince=0,lastReport=0;
static uint8_t retry=0,payloadBytes=0;
static String sentPayload;
static char sentKind[16]={0};
static bool triedUpdate=false,permitUpdate=false;
static uint32_t currentVersion=0;
static uint32_t slotCapacity=0;
inline bool updating(){
 return stage==BEGIN||stage==DATA||stage==END||stage==WAIT_BOOT;
}
inline bool imageAvailable(){
 return C5Image::version>0 && C5Image::length>1024 &&
        C5Image::length<=0x640000 &&
        C5Image::sha256[0]!=0 && C5Image::bytes[0]==0xE9;
}
inline void fail(const char *reason){
 Serial.printf("[S3 OTA] Stopped: %s (no automatic retry in this boot)\n",reason);
 stage=FAILED;pending=0;
}
inline bool send(Stream &uart,const char *type,const String &value){
 if(++seq==0)++seq;
 pending=seq;
 if(!CuteLink::send(uart,pending,type,value)){fail("FRAME");return false;}
 strncpy(sentKind,type,sizeof(sentKind)-1);sentKind[sizeof(sentKind)-1]=0;
 sentPayload=value;lastSent=millis();retry=0;
 return true;
}
inline void query(Stream &uart){
 stage=QUERY;
 send(uart,"OTA_QUERY","");
}
inline void onConnected(Stream &uart){
 if(stage==WAIT_BOOT){
  // C5 has rebooted; request the installed version.
  send(uart,"OTA_QUERY","");return;
 }
 if(stage==IDLE)query(uart);
}
inline void start(Stream &uart){
 if(!imageAvailable()){stage=DONE;return;}
 if(targetSize!=C5Image::length){fail("BAD_PACKAGE");return;}
 String manifest=String(C5Image::version)+","+String(targetSize)+","+
                 String(C5Image::sha256);
 if(manifest.length()>CuteLink::PAYLOAD){fail("MANIFEST");return;}
 triedUpdate=true;
 stage=BEGIN;position=0;
 Serial.printf("[S3 OTA] Upgrading C5 from v%lu to v%lu (%lu bytes)\n",
        (unsigned long)currentVersion,(unsigned long)C5Image::version,
        (unsigned long)targetSize);
 send(uart,"OTA_BEGIN",manifest);
}
inline void block(Stream &uart){
 if(position>=targetSize){
  stage=END;send(uart,"OTA_END","");return;
 }
 size_t count=min((size_t)40,(size_t)(targetSize-position));
 char off[9];snprintf(off,sizeof(off),"%08lX",(unsigned long)position);
 const char *hex="0123456789ABCDEF";
 String payload=String(off)+",";
 payload.reserve(89);
 for(size_t i=0;i<count;++i){
  uint8_t byte=C5Image::bytes[position+i];
  payload+=hex[byte>>4];payload+=hex[byte&15];
 }
 payloadBytes=count;
 stage=DATA;send(uart,"OTA_DATA",payload);
}
inline bool decimal(const String &s){
 if(s.isEmpty()||s.length()>10)return false;
 for(size_t i=0;i<s.length();++i)if(s[i]<'0'||s[i]>'9')return false;
 return true;
}
inline void onFrame(Stream &uart,const CuteLink::Frame &f){
 if(f.type!="OTA_INFO"&&f.type!="OTA_ACK"&&f.type!="OTA_NACK")
  return;
 if(!pending||f.seq!=pending)return;
 if(f.type=="OTA_INFO"&&(stage==QUERY||stage==WAIT_BOOT)){
  pending=0;
  int comma=f.payload.indexOf(',');
  if(comma<1||!decimal(f.payload.substring(0,comma))||
    !decimal(f.payload.substring(comma+1))){fail("INFO_FORMAT");return;}
  currentVersion=strtoul(f.payload.substring(0,comma).c_str(),nullptr,10);
  slotCapacity=strtoul(f.payload.substring(comma+1).c_str(),nullptr,10);
  Serial.printf("[S3 OTA] C5 reports v%lu, OTA slot=%lu bytes\n",
      (unsigned long)currentVersion,(unsigned long)slotCapacity);
  if(stage==WAIT_BOOT){
   if(currentVersion==C5Image::version){
    stage=DONE;Serial.println("[S3 OTA] SUCCESS: new display firmware confirmed after reboot");
   }else fail("POST_BOOT_VERSION");
   return;
  }
  if(!imageAvailable()){
   stage=DONE;Serial.println("[S3 OTA] No bundled C5 image; no update required");
   return;
  }
  if(C5Image::version<=currentVersion){
   stage=DONE;Serial.println("[S3 OTA] C5 already current");
   return;
  }
  if(triedUpdate){fail("ALREADY_TRIED");return;}
  if(C5Image::length>slotCapacity||slotCapacity==0){
   fail("PARTITION_TOO_SMALL");return;
  }
  targetSize=C5Image::length;
  stage=READY;
  Serial.println("[S3 OTA] Update queued; waiting for idle command relay");
  return;
 }
 if(f.type=="OTA_NACK"){pending=0;fail(f.payload.c_str());return;}
 if(f.type!="OTA_ACK")return;
 if(stage==BEGIN&&f.payload=="BEGIN"){
  pending=0;block(uart);return;
 }
 if(stage==DATA&&f.payload=="DATA"){
  pending=0;position+=payloadBytes;
  int percent=targetSize?(int)((uint64_t(position)*100)/targetSize):0;
  if(percent>=((int)lastReport+5)||position==targetSize){
   lastReport=(uint32_t)percent;
   Serial.printf("[S3 OTA] Transfer %d%% (%lu/%lu)\n",percent,
       (unsigned long)position,(unsigned long)targetSize);
  }
  block(uart);return;
 }
 if(stage==END&&f.payload=="REBOOT"){
  pending=0;stage=WAIT_BOOT;waitSince=millis();lastSent=millis();
  Serial.println("[S3 OTA] Image verified by C5; waiting for display reboot");
  return;
 }
 fail("UNEXPECTED_ACK");
}
inline void tick(Stream &uart,bool linked){
 const uint32_t now=millis();
 if(stage==READY){
  if(linked&&permitUpdate)start(uart);
  return;
 }
 if(stage==IDLE&&linked){query(uart);return;}
 if(stage==WAIT_BOOT){
  if((uint32_t)(now-waitSince)>45000UL){fail("REBOOT_TIMEOUT");return;}
  if(pending && (uint32_t)(now-lastSent)>5000UL){
   // C5 may reboot while processing QUERY. Wait, then query again.
   pending=0;
  }
  if(!pending&&(uint32_t)(now-lastSent)>3000UL)send(uart,"OTA_QUERY","");
  return;
 }
 if(!pending)return;
 if((uint32_t)(now-lastSent)<4500UL)return;
 if(retry++>=3){
  if(stage==QUERY){stage=IDLE;pending=0;
   // Old C5 firmware has no receiver; stop probing repeatedly.
   stage=DONE;Serial.println("[S3 OTA] C5 OTA receiver not detected");
  }else fail("TRANSFER_TIMEOUT");
  return;
 }
 if(!linked){fail("UART_LOST");return;}
 CuteLink::send(uart,pending,sentKind,sentPayload);
 lastSent=now;
}
}
