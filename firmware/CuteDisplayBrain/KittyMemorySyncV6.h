#pragma once
// V6 private, opt-in SD snapshot sender. No SD calls outside KittyMemory::task.
// Network runs on a separate low-priority task and is suspended during calls.
// TLS certificate verification is mandatory; no setInsecure(), no OTA.
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <mbedtls/sha256.h>
#include <mbedtls/base64.h>
#include "KittyMemory.h"

#ifndef KITTY_SYNC_V6_URL
#define KITTY_SYNC_V6_URL ""
#endif
#ifndef KITTY_SYNC_V6_DEVICE_TOKEN
#define KITTY_SYNC_V6_DEVICE_TOKEN ""
#endif
#ifndef KITTY_SYNC_V6_CA_PEM
#define KITTY_SYNC_V6_CA_PEM ""
#endif

namespace KittyMemorySyncV6 {
static TaskHandle_t worker=nullptr;
static bool (*idleCheck)()=nullptr;
static volatile uint32_t completed=0,failures=0;
static volatile uint32_t bytesSent=0;
inline bool configured(){
 return String(KITTY_SYNC_V6_URL).startsWith("https://") &&
        strlen(KITTY_SYNC_V6_DEVICE_TOKEN)>=32 &&
        strstr(KITTY_SYNC_V6_CA_PEM,"BEGIN CERTIFICATE")!=nullptr;
}
inline bool allowed(){
 return configured() && WiFi.status()==WL_CONNECTED &&
        KittyMemory::ready() && (!idleCheck || idleCheck());
}
inline String encode(const uint8_t* data,size_t n){
 size_t capacity=4*((n+2)/3)+4;
 char buffer[1040]={0};
 if(capacity>sizeof(buffer))return "";
 size_t written=0;
 if(mbedtls_base64_encode((unsigned char*)buffer,sizeof(buffer)-1,
      &written,data,n)!=0)return "";
 return String(buffer);
}
inline String digestHex(const unsigned char* bytes){
 static const char hex[]="0123456789abcdef";
 char result[65];for(int i=0;i<32;i++){result[i*2]=hex[bytes[i]>>4];result[i*2+1]=hex[bytes[i]&15];}
 result[64]=0;return String(result);
}
inline int send(const char* route,const String &json,String &response){
 if(!allowed())return -1;
 WiFiClientSecure client;client.setCACert(KITTY_SYNC_V6_CA_PEM);
 client.setTimeout(3);
 HTTPClient http;http.setConnectTimeout(2500);http.setTimeout(3500);
 String url=String(KITTY_SYNC_V6_URL)+route;
 if(!http.begin(client,url))return -1;
 http.addHeader("Authorization",String("Bearer ")+KITTY_SYNC_V6_DEVICE_TOKEN);
 http.addHeader("Content-Type","application/json");
 int status=http.POST((uint8_t*)json.c_str(),json.length());
 if(status==200)response=http.getString();
 http.end();return status;
}
inline bool ackOffset(const String &response,uint32_t wanted){
 int pos=response.indexOf("\"next_offset\"");
 if(pos<0)return false;
 pos=response.indexOf(':',pos);if(pos<0)return false;
 return (uint32_t)response.substring(pos+1).toInt()==wanted;
}
inline bool exportAndSend(const String &snapshot){
 // Reject snapshots assembled across a concurrent conversation/fact change.
 // Never block SD writes to force consistency.
 const uint32_t savedBefore=KittyMemory::saved;
 const uint32_t factsBefore=KittyMemory::factRevision;
 const uint32_t summariesBefore=KittyMemory::summaryRevision;
 String manifest="{";
 for(uint8_t i=0;i<KittyMemory::EXPORT_COUNT;i++){
  if(!allowed())return false;
  mbedtls_sha256_context sha;mbedtls_sha256_init(&sha);
  if(mbedtls_sha256_starts(&sha,0)!=0){mbedtls_sha256_free(&sha);return false;}
  uint32_t offset=0,total=0;bool ok=true;
  while(ok){
   if(!allowed() || !KittyMemory::requestExport(i,offset)){ok=false;break;}
   KittyMemory::ExportBlock block={};
   if(!KittyMemory::takeExport(block,1200) || !block.ok ||
      block.file!=i || block.offset!=offset || block.total>256UL*1024UL*1024UL){
     ok=false;break;
   }
   if(offset==0)total=block.total;
   if(block.total!=total || offset+block.length>total){ok=false;break;}
   if(block.length || (total==0 && offset==0)){
    String payload=encode(block.data,block.length);
    if(block.length && payload.isEmpty()){ok=false;break;}
    String req=String("{\"snapshot\":\"")+snapshot+
      "\",\"name\":\""+KittyMemory::EXPORT_NAMES[i]+
      "\",\"offset\":"+String(offset)+",\"data\":\""+payload+"\"}";
    String reply;
    uint32_t next=offset+block.length;
    if(send("/snapshot/chunk",req,reply)!=200 || !ackOffset(reply,next)){ok=false;break;}
    if(mbedtls_sha256_update(&sha,block.data,block.length)!=0){ok=false;break;}
    offset=next;
    bytesSent+=block.length;
   }
   if(offset==total)break;
   if(block.length==0){ok=false;break;}
   vTaskDelay(pdMS_TO_TICKS(12));
  }
  if(!ok){mbedtls_sha256_free(&sha);return false;}
  unsigned char hash[32]={0};
  if(mbedtls_sha256_finish(&sha,hash)!=0){mbedtls_sha256_free(&sha);return false;}
  mbedtls_sha256_free(&sha);
  if(i)manifest+=",";
  manifest+=String("\"")+KittyMemory::EXPORT_NAMES[i]+"\":{\"size\":"+
    String(total)+",\"sha256\":\""+digestHex(hash)+"\"}";
 }
 manifest+="}";
 if(savedBefore!=KittyMemory::saved || factsBefore!=KittyMemory::factRevision ||
    summariesBefore!=KittyMemory::summaryRevision)return false;
 String reply;
 String body=String("{\"snapshot\":\"")+snapshot+"\",\"manifest\":"+manifest+"}";
 const int status=send("/snapshot/finalize",body,reply);
 return status==200 && (reply.indexOf("\"finalized\": true")>=0 ||
                         reply.indexOf("\"finalized\":true")>=0);
}
inline void task(void*){
 vTaskDelay(pdMS_TO_TICKS(45000));
 while(true){
  if(allowed()){
   // Unique session per attempt. Replayed chunks can resume within the same
   // attempt, but no stale data is imported when SD contents have changed.
   String snapshot=String("s3_")+String((unsigned long)time(nullptr))+
      "_"+String((unsigned long)esp_random(),HEX);
   if(exportAndSend(snapshot)){completed++;Serial.println("[MEMSYNC] snapshot finalized");}
   else{failures++;Serial.println("[MEMSYNC] upload deferred/failed (SD remains authoritative)");}
  }
  vTaskDelay(pdMS_TO_TICKS(600000));
 }
}
inline void init(bool (*isIdle)()){
 idleCheck=isIdle;
 if(!configured()){Serial.println("[MEMSYNC] disabled: HTTPS endpoint/token/CA not configured");return;}
 if(!worker){
  BaseType_t ok=xTaskCreatePinnedToCore(task,"kitty_sync",8192,nullptr,1,&worker,1);
  if(ok!=pdPASS)Serial.println("[MEMSYNC] network worker allocation failed");
 }
}
} // namespace KittyMemorySyncV6
