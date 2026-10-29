#pragma once
// Kitty SD-only long-term archive v1. Nothing is persisted to a server.
// All filesystem I/O is restricted to a low-priority task on CPU0.
// Realtime audio, WebSocket callbacks and the main loop never touch SD_MMC.
#include <Arduino.h>
#include <FS.h>
#include <SD_MMC.h>
#include <time.h>

namespace KittyMemory {
static constexpr size_t SLOT_BYTES=768;
struct Entry { char question[256]; char answer[512]; };
static QueueHandle_t writes=nullptr;
static TaskHandle_t worker=nullptr;
static bool mounted=false;
static volatile uint32_t saved=0, failed=0;
static String recent[8];
static uint8_t recentCount=0,recentNext=0;
static SemaphoreHandle_t cacheMutex=nullptr;

// ASCII-safe UTF-8 truncation. Writes are bounded and never persist API keys.
inline String clipUTF8(const String &s,size_t maxBytes){
 if(s.length()<=maxBytes)return s;
 size_t end=maxBytes;
 while(end>0 && ((uint8_t)s[end]&0xC0)==0x80)--end;
 return s.substring(0,end);
}
inline String sanitize(String s,size_t maxBytes){
 s.replace("\r"," ");s.replace("\n"," ");s.replace("\t"," ");
 return clipUTF8(s,maxBytes);
}
inline void addCache(const String &question,const String &answer){
 String line=sanitize(question,110)+" => "+sanitize(answer,160);
 if(!cacheMutex || xSemaphoreTake(cacheMutex,pdMS_TO_TICKS(3))!=pdTRUE)return;
 recent[recentNext]=line;
 recentNext=(recentNext+1)%8;
 if(recentCount<8)recentCount++;
 xSemaphoreGive(cacheMutex);
}
inline String recall(const String &question){
 // RAM-only recall: no SD access on the model request path.
 // A tiny bounded context prevents long prompts and latency spikes.
 String q=question;q.toLowerCase();
 String result;
 // Search fragments longer than 3 characters for a conservative match.
 if(!cacheMutex || xSemaphoreTake(cacheMutex,pdMS_TO_TICKS(3))!=pdTRUE)return "";
 for(int i=0;i<recentCount && result.length()<540;i++){
  int index=(recentNext+8-1-i)%8;
  String candidate=recent[index];
  String lower=candidate;lower.toLowerCase();
  bool match=false;
  int start=0;
  for(int p=0;p<=q.length();p++){
   if(p==q.length() || q[p]==' ' || q[p]==',' || q[p]=='?' || q[p]=='.'){
    if(p-start>=4 && lower.indexOf(q.substring(start,p))>=0){match=true;break;}
    start=p+1;
   }
  }
  if(match)result+=candidate+"\n";
 }
 xSemaphoreGive(cacheMutex);
 return clipUTF8(result,540);
}
inline bool queue(const String &question,const String &answer){
 if(!writes || !mounted || question.isEmpty() || answer.isEmpty())return false;
 Entry e={};
 sanitize(question,sizeof(e.question)-1).toCharArray(e.question,sizeof(e.question));
 sanitize(answer,sizeof(e.answer)-1).toCharArray(e.answer,sizeof(e.answer));
 if(xQueueSend(writes,&e,0)!=pdTRUE){failed++;return false;}
 // The active recall cache updates immediately; SD persistence is deferred.
 addCache(question,answer);
 return true;
}
inline void task(void*){
 SD_MMC.setPins(39,38,40);
 mounted=SD_MMC.begin("/sdcard",true,false,20000,5);
 if(!mounted || SD_MMC.cardType()==CARD_NONE){
  mounted=false;
  Serial.println("[MEMORY] SD unavailable; normal voice unaffected");
 }else{
  SD_MMC.mkdir("/kitty");
  Serial.printf("[MEMORY] SD mounted: total=%llu MB free~=%llu MB\n",
    (unsigned long long)(SD_MMC.totalBytes()/1048576ULL),
    (unsigned long long)((SD_MMC.totalBytes()-SD_MMC.usedBytes())/1048576ULL));
  // Restore only the most recent bounded cache; full archive stays on SD.
  File f=SD_MMC.open("/kitty/conversations.tsv",FILE_READ);
  if(f){
   const size_t length=f.size();
   if(length>8192)f.seek(length-8192);
   if(length>8192)f.readStringUntil('\n');
   while(f.available()){
    String line=f.readStringUntil('\n');line.trim();
    int first=line.indexOf('\t'),second=line.indexOf('\t',first+1);
    if(first>=0 && second>first)addCache(line.substring(first+1,second),line.substring(second+1));
   }
   f.close();
  }
 }
 Entry e={};
 while(true){
  if(xQueueReceive(writes,&e,pdMS_TO_TICKS(1000))!=pdTRUE)continue;
  if(!mounted)continue;
  File f=SD_MMC.open("/kitty/conversations.tsv",FILE_APPEND);
  if(!f){failed++;continue;}
  // Timestamp | question | answer. One entry per successfully completed turn.
  const uint32_t ts=(uint32_t)time(nullptr);
  bool ok=f.printf("%lu\t%s\t%s\n",(unsigned long)ts,e.question,e.answer)>0;
  f.close();
  if(ok)saved++;else failed++;
  if((saved%20)==0)
   Serial.printf("[MEMORY] saved=%lu failed=%lu queue=%u\n",
     (unsigned long)saved,(unsigned long)failed,(unsigned)uxQueueMessagesWaiting(writes));
 }
}
inline void init(){
 if(!cacheMutex)cacheMutex=xSemaphoreCreateMutex();
 if(!writes)writes=xQueueCreate(10,sizeof(Entry));
 if(writes && !worker)
  xTaskCreatePinnedToCore(task,"kitty_sd",6144,nullptr,1,&worker,0);
}
inline bool ready(){return mounted;}
} // namespace KittyMemory
