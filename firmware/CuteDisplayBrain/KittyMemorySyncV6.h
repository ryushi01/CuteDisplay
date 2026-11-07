#pragma once
// V6 private, opt-in SD snapshot sender. No SD calls outside KittyMemory::task.
// Network runs on a separate low-priority task; uploads are paced during calls.
// TLS certificate verification is mandatory; no setInsecure(), no OTA.
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <mbedtls/sha256.h>
#include <mbedtls/base64.h>
#include "KittyMemory.h"
// Local-only config: never commit or attach to public build artifacts.
#if __has_include("KittySyncPrivateConfig.h")
#include "KittySyncPrivateConfig.h"
#endif

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
static bool (*callActive)()=nullptr;
static bool (*speechActive)()=nullptr;
inline void setSpeechActive(bool (*check)()){speechActive=check;}
inline void setCallActive(bool (*check)()){callActive=check;}
static volatile uint32_t completed=0,failures=0;
static volatile uint32_t bytesSent=0;
static volatile int lastHttpStatus=0;
static volatile uint8_t lastFileIndex=0;
static volatile uint8_t failureStage=0; // 1=export, 2=chunk, 3=finalize, 4=concurrent-change
static volatile uint32_t changedDuringExport=0,abortedBeforeUpload=0;
static volatile uint32_t inCallPosts=0,speechOverlapPosts=0,slowestPostMs=0;
inline bool archiveChanged(uint32_t saved,uint32_t facts,uint32_t summaries,
                           uint32_t shared,uint32_t receipts){
 return saved!=KittyMemory::saved || facts!=KittyMemory::factRevision ||
        summaries!=KittyMemory::summaryRevision ||
        shared!=KittyMemory::sharedRevision ||
        receipts!=KittyMemory::ownerReceiptRevision;
}
inline bool configured(){
 return String(KITTY_SYNC_V6_URL)=="https://ragnarok-project.com/kitty-v6/sync" &&
        strlen(KITTY_SYNC_V6_DEVICE_TOKEN)>=32 &&
        strstr(KITTY_SYNC_V6_CA_PEM,"BEGIN CERTIFICATE")!=nullptr;
}
inline bool allowed(){
 return configured() && WiFi.status()==WL_CONNECTED &&
        KittyMemory::ready() && (!idleCheck || idleCheck());
}
inline bool pauseForSpeech(){
 // Pause *between* chunks, never from an audio thread. Avoid prolonged
 // network contention while Kitty is generating/playback speech.
 while(speechActive && speechActive()){
  if(!allowed())return false;
  vTaskDelay(pdMS_TO_TICKS(100));
 }
 return allowed();
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
 HTTPClient http;http.setConnectTimeout(2500);http.setTimeout(12000); // 8s gateway upstream + HTTPS margin
 String url=String(KITTY_SYNC_V6_URL)+route;
 if(!http.begin(client,url))return -1;
 http.addHeader("Authorization",String("Bearer ")+KITTY_SYNC_V6_DEVICE_TOKEN);
 http.addHeader("Content-Type","application/json");
 // Diagnostics are counters only; never log URLs, payloads or credentials.
 const bool wasCall=callActive && callActive();
 const bool wasSpeech=speechActive && speechActive();
 const uint32_t began=millis();
 int status=http.POST((uint8_t*)json.c_str(),json.length());
 const uint32_t elapsed=millis()-began;
 if(wasCall)inCallPosts++;
 if(wasSpeech || (speechActive && speechActive()))speechOverlapPosts++;
 if(elapsed>slowestPostMs)slowestPostMs=elapsed;
 lastHttpStatus=status;
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
 // Freeze all file lengths on the SD worker, so later append-only
 // conversation writes do not invalidate the snapshot's byte boundary.
 const uint32_t factsBefore=KittyMemory::factRevision;
 const uint32_t summariesBefore=KittyMemory::summaryRevision;
 const uint32_t sharedBefore=KittyMemory::sharedRevision;
 const uint32_t receiptsBefore=KittyMemory::ownerReceiptRevision;
 failureStage=0;lastHttpStatus=0;
 if(!KittyMemory::requestExport(KittyMemory::EXPORT_COUNT,0)){
  failureStage=1;return false;
 }
 KittyMemory::ExportBlock boundary={};
 if(!KittyMemory::takeExport(boundary,2000) || !boundary.ok ||
    boundary.file!=KittyMemory::EXPORT_COUNT){
  failureStage=1;return false;
 }
 uint32_t frozen[KittyMemory::EXPORT_COUNT]={};
 for(uint8_t n=0;n<KittyMemory::EXPORT_COUNT;n++)frozen[n]=boundary.boundaries[n];
 String manifest="{";
 for(uint8_t i=0;i<KittyMemory::EXPORT_COUNT;i++){
  lastFileIndex=i;
  if((factsBefore!=KittyMemory::factRevision || summariesBefore!=KittyMemory::summaryRevision || sharedBefore!=KittyMemory::sharedRevision ||
      receiptsBefore!=KittyMemory::ownerReceiptRevision)){
   changedDuringExport++;failureStage=4;return false;
  }
  if(!allowed()){failureStage=1;return false;}
  mbedtls_sha256_context sha;mbedtls_sha256_init(&sha);
  if(mbedtls_sha256_starts(&sha,0)!=0){mbedtls_sha256_free(&sha);return false;}
  uint32_t offset=0,total=0;bool ok=true;
  while(ok){
   // Abort before the next SD read/HTTPS chunk when the live archive grows.
   // A partial staging upload is never finalized as a mixed-revision snapshot.
   if((factsBefore!=KittyMemory::factRevision || summariesBefore!=KittyMemory::summaryRevision || sharedBefore!=KittyMemory::sharedRevision ||
      receiptsBefore!=KittyMemory::ownerReceiptRevision)){
    failureStage=4;changedDuringExport++;ok=false;break;
   }
   if(!pauseForSpeech() || !KittyMemory::requestExport(i,offset,frozen[i])){ok=false;break;}
   KittyMemory::ExportBlock block={};
   if(!KittyMemory::takeExport(block,1200) || !block.ok ||
      block.file!=i || block.offset!=offset || block.total>256UL*1024UL*1024UL){
     ok=false;break;
   }
   if(offset==0)total=frozen[i];
   if(block.total!=total || offset+block.length>total){ok=false;break;}
   if(block.length || (total==0 && offset==0)){
    String payload=encode(block.data,block.length);
    if(block.length && payload.isEmpty()){ok=false;break;}
    String req=String("{\"snapshot\":\"")+snapshot+
      "\",\"name\":\""+KittyMemory::EXPORT_NAMES[i]+
      "\",\"offset\":"+String(offset)+",\"data\":\""+payload+"\"}";
    String reply;
    uint32_t next=offset+block.length;
    if(!pauseForSpeech() || send("/snapshot/chunk",req,reply)!=200 || !ackOffset(reply,next)){failureStage=2;ok=false;break;}
    if(mbedtls_sha256_update(&sha,block.data,block.length)!=0){ok=false;break;}
    offset=next;
    bytesSent+=block.length;
   }
   if(offset==total)break;
   if(block.length==0){ok=false;break;}
   // Yield between chunks; use gentler pacing when sharing Wi-Fi with voice.
   vTaskDelay(pdMS_TO_TICKS(callActive && callActive()?750:12));
  }
  if(!ok){if(failureStage!=4)failureStage=lastHttpStatus==200?1:2;mbedtls_sha256_free(&sha);return false;}
  unsigned char hash[32]={0};
  if(mbedtls_sha256_finish(&sha,hash)!=0){mbedtls_sha256_free(&sha);return false;}
  mbedtls_sha256_free(&sha);
  if(i)manifest+=",";
  manifest+=String("\"")+KittyMemory::EXPORT_NAMES[i]+"\":{\"size\":"+
    String(total)+",\"sha256\":\""+digestHex(hash)+"\"}";
 }
 manifest+="}";
 if((factsBefore!=KittyMemory::factRevision || summariesBefore!=KittyMemory::summaryRevision || sharedBefore!=KittyMemory::sharedRevision ||
      receiptsBefore!=KittyMemory::ownerReceiptRevision)){
  changedDuringExport++;failureStage=4;return false;
 }
 String reply;
 String body=String("{\"snapshot\":\"")+snapshot+"\",\"manifest\":"+manifest+"}";
 failureStage=3;
 const int status=send("/snapshot/finalize",body,reply);
 return status==200 && (reply.indexOf("\"finalized\": true")>=0 ||
                         reply.indexOf("\"finalized\":true")>=0);
}
// Short eligibility debounce, not a restriction on ongoing calls.
// Polling is lightweight; actual SD reads remain on the memory worker.
static constexpr uint32_t IDLE_QUIET_MS=500UL;
// Do not start large exports during bursts of archived conversation writes.
static constexpr uint32_t ARCHIVE_QUIET_MS=3000UL;
static constexpr uint32_t FAILURE_RETRY_MS=15000UL;
static constexpr uint32_t PERIODIC_REFRESH_MS=60000UL;
inline void task(void*){
 uint32_t idleSince=0,lastSuccess=0,lastFailure=0;
 uint32_t lastArchiveChange=millis();
 uint32_t seenSaved=KittyMemory::saved,seenFacts=KittyMemory::factRevision;
 uint32_t seenSummaries=KittyMemory::summaryRevision,seenShared=KittyMemory::sharedRevision;
 uint32_t seenReceipts=KittyMemory::ownerReceiptRevision;
 uint32_t syncedSaved=UINT32_MAX,syncedFacts=UINT32_MAX,syncedSummaries=UINT32_MAX,syncedShared=UINT32_MAX;
 uint32_t syncedReceipts=UINT32_MAX;
 while(true){
  uint32_t now=millis();
  if(archiveChanged(seenSaved,seenFacts,seenSummaries,seenShared,seenReceipts)){
   lastArchiveChange=now;
   seenSaved=KittyMemory::saved;seenFacts=KittyMemory::factRevision;
   seenSummaries=KittyMemory::summaryRevision;seenShared=KittyMemory::sharedRevision;
   seenReceipts=KittyMemory::ownerReceiptRevision;
  }
  if(!allowed()){
   idleSince=0;
   vTaskDelay(pdMS_TO_TICKS(500));
   continue;
  }
  if(idleSince==0)idleSince=now;
  bool quiet=(uint32_t)(now-idleSince)>=IDLE_QUIET_MS &&
              (uint32_t)(now-lastArchiveChange)>=ARCHIVE_QUIET_MS;
  bool changed=syncedSaved!=KittyMemory::saved ||
               syncedFacts!=KittyMemory::factRevision ||
               syncedSummaries!=KittyMemory::summaryRevision ||
               syncedShared!=KittyMemory::sharedRevision ||
               syncedReceipts!=KittyMemory::ownerReceiptRevision;
  bool periodic=lastSuccess && (uint32_t)(now-lastSuccess)>=PERIODIC_REFRESH_MS;
  bool mayRetry=!lastFailure || (uint32_t)(now-lastFailure)>=FAILURE_RETRY_MS;
  if(quiet && mayRetry && (changed || periodic)){
   const uint32_t startSaved=KittyMemory::saved;
   const uint32_t startFacts=KittyMemory::factRevision;
   const uint32_t startSummaries=KittyMemory::summaryRevision;
   const uint32_t startShared=KittyMemory::sharedRevision;
   const uint32_t startReceipts=KittyMemory::ownerReceiptRevision;
   String snapshot=String("s3_")+String((unsigned long)time(nullptr))+
      "_"+String((unsigned long)esp_random(),HEX);
   if(archiveChanged(startSaved,startFacts,startSummaries,startShared,startReceipts)){
    abortedBeforeUpload++;lastArchiveChange=millis();
    idleSince=0;vTaskDelay(pdMS_TO_TICKS(500));continue;
   }
   if(exportAndSend(snapshot)){
    completed++;
    syncedSaved=startSaved;syncedFacts=startFacts;syncedSummaries=startSummaries;syncedShared=startShared;
    syncedReceipts=startReceipts;
    lastSuccess=millis();lastFailure=0;
    Serial.printf("[MEMSYNC] snapshot finalized call_posts=%lu speech_overlap=%lu max_post_ms=%lu changed=%lu\n",
      (unsigned long)inCallPosts,(unsigned long)speechOverlapPosts,
      (unsigned long)slowestPostMs,(unsigned long)changedDuringExport);
   }else{
    // An in-flight SD write can invalidate a snapshot; retry soon.
    failures++;lastFailure=millis();
    if(failureStage==4)lastArchiveChange=lastFailure;
    Serial.printf("[MEMSYNC] upload deferred/failed stage=%u file=%u http=%d changed=%lu call_posts=%lu speech_overlap=%lu max_post_ms=%lu (SD authoritative)\n",
      (unsigned)failureStage,(unsigned)lastFileIndex,(int)lastHttpStatus,
      (unsigned long)changedDuringExport,(unsigned long)inCallPosts,
      (unsigned long)speechOverlapPosts,(unsigned long)slowestPostMs);
   }
   idleSince=0;
  }
  vTaskDelay(pdMS_TO_TICKS(500));
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
