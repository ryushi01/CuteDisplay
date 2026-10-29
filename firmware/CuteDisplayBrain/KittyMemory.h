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
static volatile bool mounted=false;
static volatile uint8_t cardState=0; // 0=starting,1=ready,2=needs format/check,3=formatting,4=error
static volatile bool formatRequested=false;
inline uint8_t status(){return cardState;}
inline bool requestFormat(){
 if(cardState!=2 || formatRequested)return false;
 formatRequested=true;return true;
}
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

struct Fact { char key[32]; char value[192]; };
static Fact facts[24]={};
static volatile uint32_t sdTotalKB=0, sdUsedKB=0;
inline uint32_t capacityKB(){return sdTotalKB;}
inline uint32_t usedKB(){return sdUsedKB;}
inline void updateStorage(){
 if(!mounted)return;
 uint64_t total=SD_MMC.totalBytes(),used=SD_MMC.usedBytes();
 sdTotalKB=(uint32_t)(total/1024ULL);sdUsedKB=(uint32_t)(used/1024ULL);
}
static uint8_t factCount=0;
inline String factSummary(size_t maxLen=700){
 String out;
 if(!cacheMutex || xSemaphoreTake(cacheMutex,pdMS_TO_TICKS(3))!=pdTRUE)return out;
 for(int i=0;i<factCount;i++){out+=String(facts[i].key)+"\t"+facts[i].value+"\n";if(out.length()>=maxLen)break;}
 xSemaphoreGive(cacheMutex);return out;
}
inline bool extractFact(String utterance,String &key,String &value){
 utterance.trim();String lowered=utterance;lowered.toLowerCase();
 int pos=-1;int skip=0;
 for(const char *pattern:{"my name is ","call me ","i am called ","私の名前は","名前は"}){
  pos=lowered.indexOf(pattern);if(pos>=0){key="name";skip=strlen(pattern);break;}
 }
 if(pos<0)for(const char *pattern:{"i like ","i love ","my favorite food is ","好きな食べ物は","好きなのは"}){
  pos=lowered.indexOf(pattern);if(pos>=0){key="likes";skip=strlen(pattern);break;}
 }
 if(pos<0 && lowered.indexOf("が好き")>0){
  pos=lowered.indexOf("が好き");key="likes";value=utterance.substring(0,pos);
 }else if(pos>=0)value=utterance.substring(pos+skip);
 else {
  // Episodic memories preserve user statements about plans, events, projects,
  // friends and preferences without pretending to fully understand them.
  // Keep the exact statement as the value to avoid hallucinated facts.
  const char *signals[]={"tomorrow","next week","next month","after tomorrow","day after tomorrow",
    "yesterday","last week","going to","i will ","i'm going","i have ","we will ",
    "remember this","please remember","in two days","the day after","on saturday","on sunday","my project","i started","i bought","i visited","i met ","i prefer","remember this","remember that","i plan","i am planning","we are going","we plan",
    "明日","明後日","来週","来月","昨日","予定","行く","食べる","買った","会った",
    "demain","apres-demain","après-demain","semaine prochaine","je vais","j'aime"};
  bool relevant=false;
  for(const char *signal:signals)if(lowered.indexOf(signal)>=0){relevant=true;break;}
  if(!relevant || utterance.length()<12)return false;
  key="event";
  value=utterance;
 }
 if(key!="event")for(const char *tail:{"。","、",".","!","！","です","だよ","だわ","よ","って呼んで"}){
  int x=value.indexOf(tail);if(x>=0)value=value.substring(0,x);
 }
 value.trim();return !value.isEmpty() && value.length()<(key=="event"?180:90);
}
inline void mergeFact(const String &key,const String &value){
 if(!cacheMutex || xSemaphoreTake(cacheMutex,pdMS_TO_TICKS(5))!=pdTRUE)return;
 for(int i=0;i<factCount;i++)if(key==facts[i].key){
  value.toCharArray(facts[i].value,sizeof(facts[i].value));
  xSemaphoreGive(cacheMutex);return;
 }
 if(factCount<24){
  key.toCharArray(facts[factCount].key,sizeof(facts[factCount].key));
  value.toCharArray(facts[factCount].value,sizeof(facts[factCount].value));
  factCount++;
 }else{
  // Rotate oldest episodic memory, never evict stable profile facts.
  int victim=-1;
  for(int i=0;i<factCount;i++)
   if(strncmp(facts[i].key,"event_",6)==0){victim=i;break;}
  if(victim>=0){
   for(int i=victim;i<factCount-1;i++)facts[i]=facts[i+1];
   key.toCharArray(facts[factCount-1].key,sizeof(facts[0].key));
   value.toCharArray(facts[factCount-1].value,sizeof(facts[0].value));
  }
 }
 xSemaphoreGive(cacheMutex);
}

inline bool queue(const String &question,const String &answer){
 if(!writes || !mounted || question.isEmpty() || answer.isEmpty()){Serial.printf("[MEMORY] enqueue refused mounted=%d queue=%d\n",mounted?1:0,writes?1:0);return false;}
 Entry e={};
 sanitize(question,sizeof(e.question)-1).toCharArray(e.question,sizeof(e.question));
 sanitize(answer,sizeof(e.answer)-1).toCharArray(e.answer,sizeof(e.answer));
 if(xQueueSend(writes,&e,0)!=pdTRUE){failed++;return false;}
 String key,value;if(extractFact(question,key,value) && key!="event")mergeFact(key,value);
 // The active recall cache updates immediately; SD persistence is deferred.
 addCache(question,answer);
 return true;
}

#include <esp_heap_caps.h>

// Compact SD-only topical index. A memory record is a dated exchange; index
// entries store only topic/term fingerprints and archive offsets, never secrets.
struct IndexRow { uint32_t offset; uint32_t topics; uint32_t terms; uint32_t time; };
static IndexRow *indexRows=nullptr;
static size_t indexCount=0;
static constexpr size_t INDEX_MAX=150000; // 2.4 MB PSRAM, archive never truncated
struct SearchRequest { char query[192]; uint32_t serial; };
static QueueHandle_t searches=nullptr;
static uint32_t nextSerial=0, finishedSerial=0;
static String searchReply;
static const char *topicWords[13]={
 "travel trip vacation kyoto osaka tokyo hotel flight train 旅行 旅 京都 大阪 東京 vacances voyage",
 "food eat restaurant cooking dinner lunch sushi ramen pizza 食事 料理 美味 レストラン manger cuisine",
 "family friend birthday wife husband child mother father 家族 友達 誕生日 母 父 famille ami",
 "work job office support customer project 仕事 職場 会社 案件 projet travail",
 "health doctor sleep exercise sick pain 健康 病院 体調 運動 sommeil sante",
 "music movie anime game book film 映画 音楽 ゲーム 本 アニメ musique",
 "weather rain sunny cold hot season 天気 雨 暑 寒 晴 気温 meteo",
 "money shopping buy price saving finance 買 購入 お金 値段 費用 argent achat",
 "kitty cutedisplay esp32 firmware camera display audio speaker microphone sdcard",
 "schedule tomorrow yesterday next week month year appointment date 予定 明日 昨日 来週 来月 去年 rendezvous",
 "love feelings worried sad happy angry emotional 気持 愛 心配 悲し 幸せ amour triste",
 "home house pet cat dog garden move 家 自宅 引越 猫 犬 maison chien",
 "name called nickname identity remember my name 名前 名 呼び 覚え 私の名前 名前は je m appelle prénom nom"
};
inline uint32_t topicsFor(String s){
 s.toLowerCase();
 uint32_t bits=0;
 for(int i=0;i<13;i++){
  String terms=String(topicWords[i])+" ";
  int at=0;
  while(at<(int)terms.length()){
   int end=terms.indexOf(' ',at);
   if(end<0)end=terms.length();
   String token=terms.substring(at,end);
   if(token.length()>=3 && s.indexOf(token)>=0){bits|=1UL<<i;break;}
   at=end+1;
  }
 }
 return bits;
}
inline uint32_t termBits(String s){
 s.toLowerCase();
 uint32_t bits=0;
 // Deterministic ASCII/UTF-8 3-byte ngrams allow approximate matching of
 // names, Japanese strings and repeated subject terms across languages.
 for(size_t i=0;i+2<s.length();i++){
  uint32_t h=2166136261UL;
  for(int j=0;j<3;j++)h=(h^(uint8_t)s[i+j])*16777619UL;
  bits|=1UL<<(h%32);
 }
 return bits;
}
inline void readIndex(){
 if(!mounted)return;
 File f=SD_MMC.open("/kitty/memory.idx",FILE_READ);
 if(!f)return;
 size_t count=min((size_t)(f.size()/sizeof(IndexRow)),INDEX_MAX);
 // Most recently written entries take priority on an oversized archive.
 if((size_t)f.size()/sizeof(IndexRow)>count)
  f.seek(f.size()-count*sizeof(IndexRow));
 if(indexRows && count){
  const size_t n=f.read((uint8_t*)indexRows,count*sizeof(IndexRow));
  indexCount=n/sizeof(IndexRow);
 }
 f.close();
 Serial.printf("[MEMORY] indexed=%u entries, SD-only archive\n",(unsigned)indexCount);
}
inline void appendIndex(const Entry &entry,uint32_t offset,uint32_t timestamp){
 IndexRow row={offset,topicsFor(String(entry.question)+" "+entry.answer),
               termBits(String(entry.question)+" "+entry.answer),timestamp};
 File f=SD_MMC.open("/kitty/memory.idx",FILE_APPEND);
 if(f){f.write((const uint8_t*)&row,sizeof(row));f.close();}
 if(indexRows){
  if(indexCount==INDEX_MAX){
   memmove(indexRows,indexRows+1,(INDEX_MAX-1)*sizeof(IndexRow));
   indexCount--;
  }
  indexRows[indexCount++]=row;
 }
}
inline void searchOnSD(const SearchRequest &q){
 String query(q.query);
 const uint32_t topics=topicsFor(query),bits=termBits(query);
 struct Rank { int score; uint32_t offset; };
 Rank best[3]={{0,0},{0,0},{0,0}};
 if(indexRows){
  for(int i=(int)indexCount-1;i>=0;i--){
   IndexRow row=indexRows[i];
   int score=__builtin_popcount(row.terms&bits);
   if(topics && (row.topics&topics))score+=12;
   // Topic match is mandatory: avoid hallucinated memories from 32-bit\n   // fingerprint collisions on unrelated conversations.\n   if(!topics || !(row.topics&topics) || score<12)continue;
   for(int k=0;k<3;k++)if(score>best[k].score){
    for(int j=2;j>k;j--)best[j]=best[j-1];
    best[k]={score,row.offset};break;
   }
   if((i&1023)==0)vTaskDelay(1); // yield to realtime I2S
  }
 }
 String result;
 File archive=SD_MMC.open("/kitty/conversations.tsv",FILE_READ);
 if(archive){
  for(int i=0;i<3;i++){
   if(best[i].score<=0 || !archive.seek(best[i].offset))continue;
   String line=archive.readStringUntil('\n');
   int a=line.indexOf('\t'),b=line.indexOf('\t',a+1);
   if(a<0 || b<0)continue;
   result+=line.substring(a+1,b)+" => "+line.substring(b+1)+"\n";
   if(result.length()>850)break;
  }
  archive.close();
 }
 if(cacheMutex && xSemaphoreTake(cacheMutex,pdMS_TO_TICKS(10))==pdTRUE){
  searchReply=clipUTF8(result,850);
  finishedSerial=q.serial;
  xSemaphoreGive(cacheMutex);
 }
}
inline uint32_t requestSearch(const String &query){
 if(!mounted || !searches || !indexRows || !indexCount || !topicsFor(query))return 0;
 SearchRequest q={};
 sanitize(query,sizeof(q.query)-1).toCharArray(q.query,sizeof(q.query));
 q.serial=++nextSerial;
 xQueueOverwrite(searches,&q);
 return q.serial;
}
inline String takeSearch(uint32_t serial){
 if(!serial || !cacheMutex || xSemaphoreTake(cacheMutex,pdMS_TO_TICKS(2))!=pdTRUE)return "";
 String value=finishedSerial==serial?searchReply:String("");
 xSemaphoreGive(cacheMutex);
 return value;
}

inline void task(void*){
 SD_MMC.setPins(39,38,40);
 mounted=SD_MMC.begin("/sdcard",true,false,20000,5);
 cardState=mounted?1:2;
 if(!mounted || SD_MMC.cardType()==CARD_NONE){
  mounted=false;
  Serial.println("[MEMORY] SD mount failed: card may need FAT formatting, be damaged, or be missing; no auto erase");
 }else{
  SD_MMC.mkdir("/kitty");
  updateStorage();
  File factFile=SD_MMC.open("/kitty/facts.tsv",FILE_READ);
  if(factFile){while(factFile.available()){String line=factFile.readStringUntil('\n');int t=line.indexOf('\t');if(t>0)mergeFact(line.substring(0,t),line.substring(t+1));}factFile.close();}
  indexRows=(IndexRow*)heap_caps_malloc(INDEX_MAX*sizeof(IndexRow),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
  if(!indexRows)Serial.println("[MEMORY] PSRAM index unavailable; recent cache only");
  readIndex();
  // Rebuild an absent index from the SD-only archive. Old conversations
  // remain recoverable after an interrupted or missing index file.
  if(indexRows && indexCount==0){
   File archive=SD_MMC.open("/kitty/conversations.tsv",FILE_READ);
   if(archive){
    Serial.println("[MEMORY] rebuilding missing SD search index");
    unsigned rebuilt=0;
    while(archive.available()){
     uint32_t offset=(uint32_t)archive.position();
     String line=archive.readStringUntil('\\n');
     int a=line.indexOf('\\t'),b=line.indexOf('\\t',a+1);
     if(a>=0 && b>a){
      Entry item={};
      line.substring(a+1,b).toCharArray(item.question,sizeof(item.question));
      line.substring(b+1).toCharArray(item.answer,sizeof(item.answer));
      appendIndex(item,offset,(uint32_t)line.substring(0,a).toInt());
      rebuilt++;
     }
     if((rebuilt%256)==0)vTaskDelay(1);
    }
    archive.close();
    Serial.printf("[MEMORY] rebuilt=%u index entries\\n",rebuilt);
   }
  }
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
 SearchRequest query={};
 while(true){
  static uint32_t lastStorageAt=0;
  if(mounted && (uint32_t)(millis()-lastStorageAt)>30000UL){updateStorage();lastStorageAt=millis();}
  if(formatRequested && cardState==2){
   formatRequested=false;
   cardState=3;
   Serial.println("[MEMORY] FORMATTING: requested explicitly; all card data will be erased");
   SD_MMC.end();
   mounted=SD_MMC.begin("/sdcard",true,true,20000,5);
   if(mounted && SD_MMC.cardType()!=CARD_NONE){
    cardState=1;SD_MMC.mkdir("/kitty");updateStorage();
    if(!indexRows)indexRows=(IndexRow*)heap_caps_malloc(INDEX_MAX*sizeof(IndexRow),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    indexCount=0;readIndex();
    Serial.println("[MEMORY] FORMAT COMPLETE: SD ready");
   }else{
    mounted=false;cardState=4;
    Serial.println("[MEMORY] FORMAT FAILED: check card and connections");
   }
  }
  if(searches && xQueueReceive(searches,&query,0)==pdTRUE && mounted)searchOnSD(query);
  if(xQueueReceive(writes,&e,pdMS_TO_TICKS(15))!=pdTRUE)continue;
  if(!mounted)continue;
  File f=SD_MMC.open("/kitty/conversations.tsv",FILE_APPEND);
  if(!f){failed++;continue;}
  // Timestamp | question | answer. One entry per successfully completed turn.
  const uint32_t ts=(uint32_t)time(nullptr);
  uint32_t offset=(uint32_t)f.size();
  bool ok=f.printf("%lu\t%s\t%s\n",(unsigned long)ts,e.question,e.answer)>0;
  f.close();
  if(ok){saved++;appendIndex(e,offset,ts);
   String key,value;if(extractFact(e.question,key,value)){
    if(key=="event")key="event_"+String(ts%1000000UL)+"_"+String(saved%100UL);
    mergeFact(key,value);File ff=SD_MMC.open("/kitty/facts.tsv","w");
    if(ff){ff.print(factSummary(6000));ff.close();}
    Serial.printf("[MEMORY] saved fact key=%s total=%u\n",key.c_str(),(unsigned)factCount);
   }
  }else failed++;
  updateStorage();
  if((saved%20)==0)
   Serial.printf("[MEMORY] saved=%lu failed=%lu queue=%u\n",
     (unsigned long)saved,(unsigned long)failed,(unsigned)uxQueueMessagesWaiting(writes));
 }
}
inline void init(){
 if(!cacheMutex)cacheMutex=xSemaphoreCreateMutex();
 if(!writes)writes=xQueueCreate(10,sizeof(Entry));
 if(!searches)searches=xQueueCreate(1,sizeof(SearchRequest));
 if(writes && !worker)
  xTaskCreatePinnedToCore(task,"kitty_sd",6144,nullptr,1,&worker,0);
}
inline bool ready(){return mounted;}
} // namespace KittyMemory
