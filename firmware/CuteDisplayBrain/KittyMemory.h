#pragma once
// Kitty SD-only long-term archive v1. Nothing is persisted to a server.
// All filesystem I/O is restricted to a low-priority task on CPU0.
// Realtime audio, WebSocket callbacks and the main loop never touch SD_MMC.
#include <Arduino.h>
#include <FS.h>
#include <SD_MMC.h>
#include <ff.h>
#include <time.h>

namespace KittyMemory {
static constexpr size_t SLOT_BYTES=768;
struct Entry { char question[256]; char answer[512]; };
static QueueHandle_t writes=nullptr;
// Bounded RAM handoff to the optional idle-only AI consolidator.
// Never waits on inference, and never touches SD in a network task.
struct ConsolidationCandidate { char utterance[256]; };
static QueueHandle_t consolidationCandidates=nullptr;
struct ConsolidatedFact { char key[32]; char value[128]; };
static QueueHandle_t consolidatedFacts=nullptr;
inline bool takeConsolidationCandidate(String &value){
 ConsolidationCandidate item={};
 if(!consolidationCandidates || xQueueReceive(consolidationCandidates,&item,0)!=pdTRUE)return false;
 value=String(item.utterance);return !value.isEmpty();
}
inline bool proposeConsolidatedFact(const String &key,const String &value){
 if(!consolidatedFacts || key.isEmpty() || value.isEmpty() || key.length()>31 || value.length()>112)return false;
 ConsolidatedFact item={};key.toCharArray(item.key,sizeof(item.key));value.toCharArray(item.value,sizeof(item.value));
 return xQueueSend(consolidatedFacts,&item,0)==pdTRUE;
}

static TaskHandle_t worker=nullptr;
static volatile bool mounted=false;
static volatile uint8_t cardState=0; // 0=starting,1=ready,2=needs format/check,3=formatting,4=error
static volatile bool formatRequested=false;
inline uint8_t status(){return cardState;}
inline bool requestFormat(){
 if(cardState==0 || cardState==3 || formatRequested)return false;
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
static constexpr size_t MAX_FACTS=256;
static Fact *facts=nullptr; // PSRAM catalog; SD remains durable
// Future lifecycle metadata will be stored alongside the catalog.
static uint32_t *factUpdated=nullptr;
static uint32_t *factExpires=nullptr;
static volatile uint32_t sdTotalKB=0, sdUsedKB=0;
inline uint32_t capacityKB(){return sdTotalKB;}
inline uint32_t usedKB(){return sdUsedKB;}
inline void updateStorage(){
 if(!mounted)return;
 uint64_t total=SD_MMC.totalBytes(),used=SD_MMC.usedBytes();
 sdTotalKB=(uint32_t)(total/1024ULL);sdUsedKB=(uint32_t)(used/1024ULL);
}
static size_t factCount=0;
static volatile uint32_t factRevision=0, memorizedNoticeSeq=0;
inline String factSummary(size_t maxLen=700){
 String out;
 if(!facts || !cacheMutex || xSemaphoreTake(cacheMutex,pdMS_TO_TICKS(3))!=pdTRUE)return out;
 // Keep realtime memory bounded and multilingual-topic context visible,
 // even when many older preference slots are occupied.
 for(int pass=0;pass<3;pass++){
  int count=(int)factCount;
  for(int n=0;n<count;n++){
   int i=pass==2?(count-1-n):n;
   String k(facts[i].key);
   bool episodic=k.startsWith("note_") || k.startsWith("event_");
   bool important=k=="name" || k=="home" || k=="work" || k.startsWith("context_");
   if((pass==0 && !important) ||
      (pass==1 && (important || episodic)) ||
      (pass==2 && !episodic))continue;
   String record=k+"\t"+facts[i].value+"\n";
   if(out.length()+record.length()>maxLen)continue;
   out+=record;
  }
 }
 xSemaphoreGive(cacheMutex);return out;
}
// Recoverable SD fact snapshots: never truncate the only good copy.
inline bool persistFacts(){
 if(!facts || factCount==0)return false;
 const char *tmp="/kitty/facts.next",*main="/kitty/facts.tsv",*backup="/kitty/facts.bak";
 SD_MMC.remove(tmp);
 File f=SD_MMC.open(tmp,FILE_WRITE);
 if(!f)return false;
 // Copy one small fact at a time rather than assembling a 50KB+ String.
 // Never hold the cache mutex while writing to the SD card.
 bool ok=true;
 for(size_t i=0;i<factCount;i++){
  Fact item={};
  if(!cacheMutex || xSemaphoreTake(cacheMutex,pdMS_TO_TICKS(50))!=pdTRUE){ok=false;break;}
  item=facts[i];
  xSemaphoreGive(cacheMutex);
  const uint32_t changed=factUpdated?factUpdated[i]:0;
  const uint32_t expiry=factExpires?factExpires[i]:0;
  if(f.printf("%s\t%s\t%lu\t%lu\n",item.key,item.value,
      (unsigned long)changed,(unsigned long)expiry)<=0){ok=false;break;}
  if((i&31)==0)vTaskDelay(1);
 }
 f.flush();f.close();
 if(!ok){SD_MMC.remove(tmp);return false;}
 if(SD_MMC.exists(main)){
  SD_MMC.remove(backup);
  if(!SD_MMC.rename(main,backup)){SD_MMC.remove(tmp);return false;}
 }
 if(!SD_MMC.rename(tmp,main)){
  if(SD_MMC.exists(backup))SD_MMC.rename(backup,main);
  return false;
 }
 return true;
}
inline void mergeFact(const String &key,const String &value);
inline void restoreFactSnapshots(){
 const char* candidates[]={"/kitty/facts.tsv","/kitty/facts.bak"};
 for(const char *path:candidates){
  File f=SD_MMC.open(path,FILE_READ);if(!f)continue;
  size_t before=factCount;
  while(f.available()){
   String line=f.readStringUntil('\n');int tab=line.indexOf('\t');
   if(tab>0 && tab<32 && line.length()<280){
    int second=line.indexOf('\t',tab+1);
    int third=second>=0?line.indexOf('\t',second+1):-1;
    String k=line.substring(0,tab);
    String v=second>=0?line.substring(tab+1,second):line.substring(tab+1);
    mergeFact(k,v);
    if(second>=0 && third>second && factCount && factUpdated){
     // Metadata is optional: legacy two-column snapshots still load.
     for(size_t i=0;i<factCount;i++)if(k==facts[i].key){
      factUpdated[i]=(uint32_t)line.substring(second+1,third).toInt();
      if(factExpires)factExpires[i]=(uint32_t)line.substring(third+1).toInt();
      break;
     }
    }
   }
  }
  f.close();
  if(factCount>before){
   if(String(path)!="/kitty/facts.tsv")Serial.println("[MEMORY] recovered facts from backup");
   break;
  }
 }
}
inline bool extractFact(String utterance,String &key,String &value){
 utterance.trim();if(utterance.length()<5)return false;
 String lower=utterance;lower.toLowerCase();
 int pos=-1,skip=0;
 for(const char* marker:{"my name is ","my name's ","my name’s ","i am called ","i'm called ","i’m called ","you can call me ","please call me ","call me ","i go by ","everyone calls me ","people call me ","je m’appelle ","je m'appelle ","mon prénom est ","mon prenom est ","je suis appelé ","je suis appelée ","私の名前は","名前は","私の名前は、","僕の名前は","わたしの名前は"}){
  pos=lower.indexOf(marker);if(pos>=0){key="name";skip=strlen(marker);break;}
 }
 // Plain English "I'm Shana"/"I am Shana" is an introduction only when
 // the remaining words form a short name, not a sentence about an activity.
 if(pos<0 && lower.indexOf('?')<0 && lower.indexOf("？")<0){
  for(const char* marker:{"i'm ","i’m ","i am "}){
   if(!lower.startsWith(marker))continue;
   String candidate=utterance.substring(strlen(marker));candidate.trim();
   for(const char* tail:{".","!","。","です"})if(candidate.endsWith(tail))
    candidate.remove(candidate.length()-strlen(tail));
   candidate.trim();
   String c=candidate;c.toLowerCase();
   bool sentence=false;
   for(const char* word:{"busy","working","going","feeling","happy","sad",
     "tired","hungry","at ","in ","on ","from ","with ","not ","very ",
     "a ","an ","the ","here","there","doing","looking","trying",
     "planning","thinking","sorry","ready","fine","good","sick"}){
    if(c==word || c.startsWith(word)){sentence=true;break;}
   }
   int spaces=0;bool letters=true;
   for(size_t i=0;i<candidate.length();i++){
    char ch=candidate[i];
    if(ch==' ')spaces++;
    else if(!((ch>='A' && ch<='Z')||(ch>='a' && ch<='z')||ch=='-'||ch=='\'')){
     letters=false;break;
    }
   }
   if(!sentence && letters && spaces<=2 && candidate.length()>=2 && candidate.length()<=40){
    key="name";value=candidate;pos=-2;
   }
   break;
  }
 }
 // Self-introduction without the literal word 'name'.
 if(pos<0){
  for(const char* marker:{"私はシャナ","僕はシャナ","わたしはシャナ","私はしゃな","僕はしゃな"}){
   if(lower.startsWith(marker)){key="name";value="Shana";pos=-2;break;}
  }
 }
 if(pos<0)for(const char* marker:{"i live in ","i moved to ","i now live in ","j'habite à ","j'habite a ","住んでいるのは"}){
  pos=lower.indexOf(marker);if(pos>=0){key="home";skip=strlen(marker);break;}
 }
 if(pos<0)for(const char* marker:{"i work at ","i now work at ","i work for ","je travaille chez ","勤務先は"}){
  pos=lower.indexOf(marker);if(pos>=0){key="work";skip=strlen(marker);break;}
 }
 // Fast multilingual context classification, without extra model inference.
 // Preserve negation and time qualifiers in the value; same topic replaces
 // older temporary statements rather than manufacturing permanent traits.
 if(pos<0 && lower.indexOf('?')<0 && lower.indexOf("？")<0){
  struct Rule { const char* key; const char* trigger; };
  static const Rule rules[]={
   {"context_work_availability","busy with work"},
   {"context_work_availability","too busy to take"},
   {"context_work_availability","cannot take holidays"},
   {"context_work_availability","can't take holidays"},
   {"context_work_availability","je suis occupé"},
   {"context_work_availability","je suis occupée"},
   {"context_work_availability","trop de travail"},
   {"context_work_availability","pas prendre de vacances"},
   {"context_work_availability","仕事が忙しい"},
   {"context_work_availability","休暇を取れない"},
   {"context_work_availability","休みが取れない"},
   {"context_upcoming_plan","tonight i"},
   {"context_upcoming_plan","tomorrow i"},
   {"context_upcoming_plan","i plan to"},
   {"context_upcoming_plan","i'm going to"},
   {"context_upcoming_plan","ce soir je"},
   {"context_upcoming_plan","demain je"},
   {"context_upcoming_plan","je vais "},
   {"context_upcoming_plan","今夜は"},
   {"context_upcoming_plan","明日は"},
   {"context_upcoming_plan","予定がある"},
   {"context_upcoming_plan","する予定"},
   {"context_hobby","my hobby is"},
   {"context_hobby","my hobbies are"},
   {"context_hobby","mon passe-temps"},
   {"context_hobby","mes loisirs"},
   {"context_hobby","私の趣味は"},
   {"context_hobby","趣味は"}
  };
  for(const auto &rule:rules){
   if(lower.indexOf(rule.trigger)>=0){
    key=rule.key;value=utterance;pos=-2;break;
   }
  }
 }
 // Consolidate declarative attributes under a stable subject (not all
 // user statements are food, plans or preferences).
 if(pos==-1){
  int subjectStart=lower.indexOf("my ");
  int predicate=subjectStart>=0?lower.indexOf(" is ",subjectStart+3):-1;
  if(subjectStart>=0 && predicate>subjectStart+3 && predicate-subjectStart<=42){
   String subject=lower.substring(subjectStart+3,predicate);
   subject.trim();
   if(subject.length()>1 && subject.indexOf('?')<0){
    uint32_t h=2166136261UL;
    for(size_t i=0;i<subject.length();i++)h=(h^(uint8_t)subject[i])*16777619UL;
    char code[16];snprintf(code,sizeof(code),"%08lx",(unsigned long)h);
    key=String("attr_")+code;
    value=subject+": "+utterance.substring(predicate+4);
    pos=-2; // extracted a subject-value pair, no substring offset needed
   }
  }
 }
 if(pos==-1)for(const char* marker:{"i no longer like ","i don't like ","i do not like ","i dislike ","i hate ","je n'aime pas ","je déteste ","je deteste ","もう好きじゃない"}){
  pos=lower.indexOf(marker);if(pos>=0){key="dislikes";skip=strlen(marker);break;}
 }
 if(pos==-1)for(const char* marker:{"i like ","i love ","j'aime ","j’adore ","j'adore ","my favorite food is ","好きな食べ物は","好きなのは"}){
  pos=lower.indexOf(marker);if(pos>=0){key="likes";skip=strlen(marker);break;}
 }
 if(pos==-1 && lower.indexOf("が好き")>0){
  key="likes";value=utterance.substring(0,lower.indexOf("が好き"));
  // Japanese topic and subject markers are not part of the liked object.
  for(const char* prefix:{"私は","僕は","俺は","わたしは","私が","僕が","俺が","わたしが"}){
   if(value.startsWith(prefix)){value.remove(0,strlen(prefix));break;}
  }
  value.trim();
 }else if(pos>=0){
  value=utterance.substring(pos+skip);
 }else if(pos==-1){
  // Broad topic capture: don't restrict memories to hardcoded food/events.
  // Explicit remember requests and personal statements are preserved as
  // concise, dated notes. Avoid archiving routine questions and greetings.
  bool explicitSave=false;
  for(const char* marker:{"remember ","remember this","don't forget","please remember",
    "覚えて","記憶して","souviens-toi","rappelle-toi"}){
   if(lower.indexOf(marker)>=0){explicitSave=true;break;}
  }
  bool personal=false;
  for(const char* marker:{"i ","i'm ","i’ve ","i've ","my ","mine ","we ","our ",
    "私は","私が","私の","僕は","僕の","俺は","うちは",
    "je ","j'ai ","mon ","ma ","mes ","nous ","notre "}){
   if(lower.indexOf(marker)>=0){personal=true;break;}
  }
  // Avoid turning questions and one-word acknowledgements into "facts".
  if((!explicitSave && !personal) || lower.indexOf('?')>=0 ||
     lower.indexOf("？")>=0 || utterance.length()<12)return false;
  key="note";
  value=utterance;
  // Strip metacommands to store the underlying fact, not the instruction.
  for(const char* marker:{"please remember this:","remember this:","remember that ",
    "please remember ","remember ","覚えておいて","覚えてね"}){
   String m(marker);int start=lower.indexOf(m);
   if(start>=0 && start<=12){
    value=utterance.substring(start+m.length());value.trim();break;
   }
  }
 }
 if(key!="note")for(const char* ending:{"。","、",".","!","！","です","だよ","だわ","よ","って呼んで"}){
  int k=value.indexOf(ending);if(k>=0)value=value.substring(0,k);
 }
 value.trim();
 if(key=="name"){
  // Trim multilingual self-introduction endings.
  for(const char* suffix:{"と申します","といいます","と言います","です","だよ","だ","って呼んで","と呼んで","と呼んでください"}){
   if(value.endsWith(suffix)){value.remove(value.length()-strlen(suffix));break;}
  }
  if(value.startsWith("シャナ") || value.startsWith("しゃな"))value="Shana";
  if(value.startsWith("、") || value.startsWith(" "))value.remove(0,value.startsWith("、")?strlen("、"):1);
  for(const char* suffix:{"よろしくお願いします","よろしくね"})if(value.endsWith(suffix))value.remove(value.length()-strlen(suffix));
  for(const char* suffix:{" please"," okay"," ok"})if(value.endsWith(suffix))value.remove(value.length()-strlen(suffix));
  value.trim();
 }
 // Do not chop off a UTF-8 scalar or store a sprawling paragraph.
 if(value.length()>112)value=clipUTF8(value,112);
 return value.length()>=2;
}
// Stable compact identity for related preference subjects. No embeddings on the S3.
inline String normalizeSubject(String value){
 value.trim();value.toLowerCase();
 while(value.endsWith(".")||value.endsWith("!")||value.endsWith("。"))value.remove(value.length()-1);
 return clipUTF8(value,72);
}
inline String preferenceKey(const String &kind,const String &value){
 String normalized=normalizeSubject(value);
 uint32_t h=2166136261UL;
 for(size_t i=0;i<normalized.length();i++)h=(h^(uint8_t)normalized[i])*16777619UL;
 char buf[16];snprintf(buf,sizeof(buf),"%08lx",(unsigned long)h);
 return String("pref_")+buf;
}
inline bool isEpisodic(const String &key){
 return key.startsWith("note_")||key.startsWith("event_");
}
inline uint32_t expiryForFact(const String &key,const String &value){
 time_t now=time(nullptr);
 if(now<1700000000)return 0; // Do not expire anything before NTP sync.
 if(key!="context_upcoming_plan" && !key.startsWith("event_"))return 0;
 String text=value;text.toLowerCase();
 if(text.indexOf("tomorrow")>=0 || text.indexOf("demain")>=0 ||
    text.indexOf("明日")>=0)return (uint32_t)now+48UL*3600UL;
 if(text.indexOf("today")>=0 || text.indexOf("aujourd")>=0 ||
    text.indexOf("今日")>=0)return (uint32_t)now+24UL*3600UL;
 // No guessed expiry for undated plans: they require explicit correction.
 return 0;
}
inline bool meaningfulPreferenceSubject(String subject);
inline void mergeFact(const String &key,const String &value){
 if(!facts || !cacheMutex || xSemaphoreTake(cacheMutex,pdMS_TO_TICKS(5))!=pdTRUE)return;
 // Consolidate exact duplicates and corrections: dislikes replace likes
 // for the same subject, while different preferences coexist.
 String normalized=normalizeSubject(value);
 String finalKey=key;
 if((key=="likes"||key=="dislikes") && !meaningfulPreferenceSubject(value)){xSemaphoreGive(cacheMutex);return;}
 if(key=="likes"||key=="dislikes")finalKey=preferenceKey(key,value);
 for(int i=0;i<factCount;i++){
  if(finalKey==facts[i].key){
   // Keep multiple likes; a correction to the same subject supersedes it.
   String entry=(key=="dislikes"||key=="likes")?key+":"+value:value;
   // Repeating an unchanged fact is not a new memory event.
   if(entry==String(facts[i].value)){xSemaphoreGive(cacheMutex);return;}
   entry.toCharArray(facts[i].value,sizeof(facts[i].value));
   if(factUpdated)factUpdated[i]=(uint32_t)time(nullptr);
   if(factExpires)factExpires[i]=expiryForFact(key,value);
   factRevision++;
   xSemaphoreGive(cacheMutex);return;
  }
  if(isEpisodic(key) && isEpisodic(String(facts[i].key)) &&
      normalizeSubject(String(facts[i].value))==normalized){
   xSemaphoreGive(cacheMutex);return;
  }
 }
 String stored=(key=="likes"||key=="dislikes")?key+":"+value:value;
 if(factCount<MAX_FACTS){
  finalKey.toCharArray(facts[factCount].key,sizeof(facts[factCount].key));
  stored.toCharArray(facts[factCount].value,sizeof(facts[factCount].value));
  if(factUpdated)factUpdated[factCount]=(uint32_t)time(nullptr);
  if(factExpires)factExpires[factCount]=expiryForFact(key,value);
  factCount++;factRevision++;
 }else{
  // Fixed memory budget: rotate episodic notes first, preserving identity
  // and known preferences until new information needs the slots.
  int victim=-1;
  for(int i=0;i<factCount;i++)if(isEpisodic(String(facts[i].key))){victim=i;break;}
  if(victim<0 && finalKey!="name" && finalKey!="home" && finalKey!="work"){
   for(int i=0;i<factCount;i++)if(String(facts[i].key).startsWith("pref_")){victim=i;break;}
  }
  if(victim>=0){
   for(int i=victim;i<factCount-1;i++)facts[i]=facts[i+1];
   finalKey.toCharArray(facts[factCount-1].key,sizeof(facts[0].key));
   stored.toCharArray(facts[factCount-1].value,sizeof(facts[0].value));
   factRevision++;
  }
 }
 xSemaphoreGive(cacheMutex);
}


// Explicit weekday work statements share a stable key across EN/FR/JA.
inline bool parseWorkday(String phrase,String &key,String &value){
 phrase.toLowerCase();
 const char* labels[]={"monday","tuesday","wednesday","thursday","friday","saturday","sunday"};
 const char* french[]={"lundi","mardi","mercredi","jeudi","vendredi","samedi","dimanche"};
 const char* japanese[]={"月曜","火曜","水曜","木曜","金曜","土曜","日曜"};
 bool work=phrase.indexOf("work")>=0||phrase.indexOf("travail")>=0||phrase.indexOf("働")>=0||phrase.indexOf("仕事")>=0;
 if(!work)return false;
 for(int i=0;i<7;i++)if(phrase.indexOf(labels[i])>=0||phrase.indexOf(french[i])>=0||phrase.indexOf(japanese[i])>=0){
  bool neg=phrase.indexOf("no longer")>=0||phrase.indexOf("don't")>=0||phrase.indexOf("do not")>=0||
    phrase.indexOf("ne travaille plus")>=0||phrase.indexOf("ne travaille pas")>=0||
    phrase.indexOf("働かない")>=0||phrase.indexOf("働きません")>=0||phrase.indexOf("仕事はない")>=0;
  key=String("routine_work_")+labels[i];value=neg?"not working":"working";return true;
 }
 return false;
}
inline bool gymCancellation(const String &utterance){
 String s=utterance;s.toLowerCase();
 return s.indexOf("gym")>=0 && (s.indexOf("cancel")>=0 ||
    s.indexOf("not going")>=0 || s.indexOf("won't go")>=0);
}
inline void removeSupersededGymPlan(){
 if(!cacheMutex || xSemaphoreTake(cacheMutex,pdMS_TO_TICKS(5))!=pdTRUE)return;
 for(int i=0;i<factCount;){
  String k(facts[i].key),v(facts[i].value);v.toLowerCase();
  if(isEpisodic(k) && v.indexOf("gym")>=0 &&
    v.indexOf("tomorrow")>=0 && v.indexOf("cancel")<0 &&
    v.indexOf("not going")<0 && v.indexOf("won't go")<0){
   for(int j=i;j<factCount-1;j++)facts[j]=facts[j+1];
   factCount--;
  }else i++;
 }
 xSemaphoreGive(cacheMutex);
}
inline bool meaningfulPreferenceSubject(String subject){
 subject.trim();subject.toLowerCase();
 while(subject.endsWith(".")||subject.endsWith("!")||subject.endsWith("。"))subject.remove(subject.length()-1);
 subject.trim();
 if(subject.length()<3 || subject.length()>72)return false;
 for(const char* v:{"it","this","that","them","those","these","one","something","anything","everything","the joke","that joke","this joke","what food i dislike","what i like","what i dislike","you","your joke"})
  if(subject==v)return false;
 for(const char* prefix:{"and ","what ","how ","why ","if ","because ","when ","the one ","that one ","your "})
  if(subject.startsWith(prefix))return false;
 return true;
}
inline bool pruneInvalidPreferences(){
 bool changed=false;
 if(!cacheMutex || xSemaphoreTake(cacheMutex,pdMS_TO_TICKS(5))!=pdTRUE)return false;
 for(int i=0;i<factCount;){
  String k(facts[i].key),v(facts[i].value);
  int sep=v.indexOf(':');
  if(k.startsWith("pref_") && sep>=0 && !meaningfulPreferenceSubject(v.substring(sep+1))){
   for(int j=i;j<factCount-1;j++)facts[j]=facts[j+1];
   factCount--;changed=true;
  }else i++;
 }
 xSemaphoreGive(cacheMutex);
 return changed;
}
inline void consolidatePreferences(const String &utterance){
 // Break short compound English statements into independent preference facts.
 // Generic subjects: food, games, people, music, hobbies, technology, etc.
 String lowered=utterance;lowered.toLowerCase();
 // An interrogative is not a new personal preference.
 if(lowered.indexOf('?')>=0 || lowered.indexOf("？")>=0 ||
    lowered.indexOf("what ")>=0 || lowered.indexOf("which ")>=0 ||
    lowered.indexOf("do i ")>=0 || lowered.indexOf("can you ")>=0)return;
 const char *markers[]={"i no longer like ","i don't like ","i do not like ",
   "i dislike ","i hate ","i like ","i love ","but hate ","but dislike ",
   "but i hate ","but i dislike ","but i like ","but i love "};
 const bool negative[]={true,true,true,true,true,false,false,true,true,true,true,false,false};
 size_t cursor=0;bool active=false;bool dislike=false;
 while(cursor<utterance.length()){
  int best=-1;int bestPos=utterance.length();
  for(int i=0;i<13;i++){
   int at=lowered.indexOf(markers[i],cursor);
   if(at>=0 && at<bestPos){best=i;bestPos=at;}
  }
  if(active){
   size_t end=best>=0?(size_t)bestPos:utterance.length();
   String group=utterance.substring(cursor,end);
   group.replace(", and "," and ");group.replace(", "," and ");
   int at=0;
   while(at<(int)group.length()){
    int split=group.indexOf(" and ",at);
    if(split<0)split=group.length();
    String subject=group.substring(at,split);subject.trim();
    for(const char *tail:{".","!","。"," but"," though"}){
     if(subject.endsWith(tail))subject.remove(subject.length()-strlen(tail));
    }
    subject.trim();
    if(subject.startsWith("and "))subject.remove(0,4);
    if(subject.startsWith("especially "))subject.remove(0,11);
    subject.trim();
    if(meaningfulPreferenceSubject(subject) &&
       subject.indexOf('?')<0 && subject.indexOf("？")<0)
     mergeFact(dislike?"dislikes":"likes",subject);
    at=split+5;
   }
  }
  if(best<0)break;
  dislike=negative[best];active=true;
  cursor=bestPos+strlen(markers[best]);
 }
}

inline bool queue(const String &question,const String &answer){
 if(!writes || !mounted || question.isEmpty() || answer.isEmpty()){Serial.printf("[MEMORY] enqueue refused mounted=%d queue=%d\n",mounted?1:0,writes?1:0);return false;}
 Entry e={};
 sanitize(question,sizeof(e.question)-1).toCharArray(e.question,sizeof(e.question));
 sanitize(answer,sizeof(e.answer)-1).toCharArray(e.answer,sizeof(e.answer));
 if(xQueueSend(writes,&e,0)!=pdTRUE){failed++;return false;}
 // Facts are merged exclusively in the SD worker, so revision detection
 // and snapshot persistence cannot miss an early RAM-only mutation.
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
// Language-independent topic aliases: retrieve related history without an
// extra model request or SD I/O on the audio path. This is lexical semantic
// expansion (not embedding/vector search).
inline uint32_t semanticTopics(String q){
 q.toLowerCase();
 uint32_t topics=topicsFor(q);
 const char *food[]={"like","enjoy","favorite","favourite","prefer","aime","adore","préfère","préf","好き","好物","好み","何が好き","食べ物",nullptr};
 for(int i=0;food[i];i++)if(q.indexOf(food[i])>=0){topics|=1UL<<1;break;}
 const char *work[]={"career","profession","employer","occupation","métier","emploi","職業","働","勤務",nullptr};
 for(int i=0;work[i];i++)if(q.indexOf(work[i])>=0){topics|=1UL<<3;break;}
 const char *identity[]={"who am i","who i am","my identity","comment je m'appelle","quel est mon nom","私の名前","名前を",nullptr};
 for(int i=0;identity[i];i++)if(q.indexOf(identity[i])>=0){topics|=1UL<<12;break;}
 return topics;
}
inline String semanticFactRecall(const String &query,size_t limit=280){
 String result;
 if(!facts || !cacheMutex || xSemaphoreTake(cacheMutex,pdMS_TO_TICKS(2))!=pdTRUE)return result;
 uint32_t topics=semanticTopics(query);
 String lower=query;lower.toLowerCase();
 bool preferences=(topics&(1UL<<1)) || lower.indexOf("prefer")>=0 || lower.indexOf("好き")>=0;
 // Iterate recent facts first, prioritizing identity and matching preferences.
 for(int i=(int)factCount-1;i>=0;i--){
  String key(facts[i].key),value(facts[i].value);
  bool selected=(preferences && key.startsWith("pref_")) ||
   ((topics&(1UL<<12)) && key=="name") ||
   ((topics&(1UL<<3)) && (key=="work" || key=="context_work_availability")) ||
   ((topics&(1UL<<9)) && key=="context_upcoming_plan") ||
   ((topics&(1UL<<11)) && key=="home");
  if(!selected)continue;
  String line=key+"\\t"+value+"\\n";
  if(result.length()+line.length()>limit)continue;
  result+=line;
 }
 xSemaphoreGive(cacheMutex);
 return result;
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
 const uint32_t topics=semanticTopics(query),bits=termBits(query);
 struct Rank { int score; uint32_t offset; };
 Rank best[3]={{0,0},{0,0},{0,0}};
 if(indexRows){
  for(int i=(int)indexCount-1;i>=0;i--){
   // Yield in fixed slices, even when candidates fail the topic filter.
   // Keeps large 150k-row scans cooperative with the Core 0 I2S task.
   if((i&255)==0)vTaskDelay(1);
   IndexRow row=indexRows[i];
   int score=__builtin_popcount(row.terms&bits);
   if(topics && (row.topics&topics))score+=12;
   // Topic match is mandatory: avoid hallucinated memories from 32-bit\n   // fingerprint collisions on unrelated conversations.\n   if(!topics || !(row.topics&topics) || score<12)continue;
   for(int k=0;k<3;k++)if(score>best[k].score){
    for(int j=2;j>k;j--)best[j]=best[j-1];
    best[k]={score,row.offset};break;
   }
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
 if(!mounted || !searches || !indexRows || !indexCount || !semanticTopics(query))return 0;
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
 if(!facts)facts=(Fact*)heap_caps_calloc(MAX_FACTS,sizeof(Fact),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 if(!facts)Serial.println("[MEMORY] ERROR: PSRAM fact catalog unavailable");
 if(!factUpdated)factUpdated=(uint32_t*)heap_caps_calloc(MAX_FACTS,sizeof(uint32_t),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 if(!factExpires)factExpires=(uint32_t*)heap_caps_calloc(MAX_FACTS,sizeof(uint32_t),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 SD_MMC.setPins(39,38,40);
 mounted=SD_MMC.begin("/sdcard",true,false,20000,5);
 cardState=mounted?1:2;
 if(!mounted || SD_MMC.cardType()==CARD_NONE){
  mounted=false;
  Serial.println("[MEMORY] SD mount failed: card may need FAT formatting, be damaged, or be missing; no auto erase");
 }else{
  SD_MMC.mkdir("/kitty");
  updateStorage();
  if(facts)restoreFactSnapshots();
  if(pruneInvalidPreferences()){
   persistFacts();
   Serial.println("[MEMORY] pruned ambiguous preferences");
  }
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
  // S3's network task proposes changes only; the SD worker owns persistence.
  ConsolidatedFact aiFact={};
  if(mounted && consolidatedFacts && xQueueReceive(consolidatedFacts,&aiFact,0)==pdTRUE){
   String kind(aiFact.key),subject(aiFact.value);
   bool preference=(kind=="likes"||kind=="dislikes") && meaningfulPreferenceSubject(subject);
   int colon=subject.indexOf(':');
   String topic=colon>0?subject.substring(0,colon):String("");
   String detail=colon>0?subject.substring(colon+1):String("");
   bool situation=kind=="situation" && (topic=="work_availability" ||
     topic=="upcoming_plan" || topic=="hobby") && detail.length()>=5 &&
     detail.length()<=90 && detail.indexOf('?')<0;
   if(preference || situation){
    uint32_t before=factRevision;
    if(preference)mergeFact(kind,subject);
    else mergeFact("context_"+topic,detail);
    if(factRevision!=before){
     if(persistFacts())memorizedNoticeSeq++;
     Serial.printf("[MEMORY AI] consolidated %s\n",kind.c_str());
    }
   }
  }
  static uint32_t lastStorageAt=0;
  if(mounted && (uint32_t)(millis()-lastStorageAt)>30000UL){updateStorage();lastStorageAt=millis();}
  if(formatRequested){
   formatRequested=false;
   const bool wasMounted=mounted;
   cardState=3;mounted=false; // suspend enqueue and memory I/O during format
   Serial.println("[MEMORY] FORMATTING: permanently erasing all SD content");
   if(writes)xQueueReset(writes);
   if(searches)xQueueReset(searches);
   if(consolidationCandidates)xQueueReset(consolidationCandidates);
   if(consolidatedFacts)xQueueReset(consolidatedFacts);
   bool ok=false;
   if(wasMounted){
    // Unlike begin(format_if_mount_failed=true), f_mkfs reformats even a
    // previously healthy FAT volume. The SD worker is the only FS owner.
    BYTE* work=(BYTE*)heap_caps_malloc(4096,MALLOC_CAP_8BIT);
    if(work){
     MKFS_PARM opt={};opt.fmt=FM_FAT|FM_FAT32;opt.n_fat=1;
     FRESULT result=f_mkfs("0:",&opt,work,4096);
     free(work);
     Serial.printf("[MEMORY] FAT format result=%d\\n",(int)result);
     ok=(result==FR_OK);
    }
    SD_MMC.end();
    if(ok)ok=SD_MMC.begin("/sdcard",true,false,20000,5);
   }else{
    // Mount failed: allow the Arduino SD driver to initialize and
    // format an unmountable FAT volume.
    SD_MMC.end();
    ok=SD_MMC.begin("/sdcard",true,true,20000,5);
   }
   mounted=ok && SD_MMC.cardType()!=CARD_NONE;
   if(mounted){
    SD_MMC.mkdir("/kitty");
    if(cacheMutex && xSemaphoreTake(cacheMutex,pdMS_TO_TICKS(500))==pdTRUE){
     if(facts)memset(facts,0,MAX_FACTS*sizeof(Fact));factCount=0;factRevision++;
     for(auto &v:recent)v="";
     recentCount=0;recentNext=0;
     xSemaphoreGive(cacheMutex);
    }
    indexCount=0;finishedSerial=0;nextSerial=0;searchReply="";
    saved=0;failed=0;updateStorage();cardState=1;
    Serial.println("[MEMORY] FORMAT COMPLETE: card mounted, memory cache cleared");
   }else{
    cardState=4;
    Serial.println("[MEMORY] FORMAT FAILED: check SD card and wiring");
   }
   continue;
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
   if(consolidationCandidates && strlen(e.question)>=12){
    ConsolidationCandidate c={};strlcpy(c.utterance,e.question,sizeof(c.utterance));
    // Drop oldest if overloaded: never block speech or the SD archive.
    if(xQueueSend(consolidationCandidates,&c,0)!=pdTRUE){
     ConsolidationCandidate old={};xQueueReceive(consolidationCandidates,&old,0);
     xQueueSend(consolidationCandidates,&c,0);
    }
   }
   uint32_t revisionBefore=factRevision;
   String routineKey,routineValue;
   if(parseWorkday(String(e.question),routineKey,routineValue)){
    String oldValue;
    if(facts && cacheMutex && xSemaphoreTake(cacheMutex,pdMS_TO_TICKS(5))==pdTRUE){
     for(size_t i=0;i<factCount;i++)if(routineKey==facts[i].key){oldValue=facts[i].value;break;}
     xSemaphoreGive(cacheMutex);
    }
    if(!oldValue.isEmpty() && oldValue!=routineValue){
     File history=SD_MMC.open("/kitty/corrections.tsv",FILE_APPEND);
     if(history){history.printf("%lu\\t%s\\t%s\\t%s\\n",(unsigned long)ts,routineKey.c_str(),oldValue.c_str(),routineValue.c_str());history.close();}
    }
    mergeFact(routineKey,routineValue);
   }
   String key,value;if(extractFact(e.question,key,value)){
    if(key=="note")key="note_"+String(ts%1000000UL)+"_"+String(saved%100UL);
    // Persist parsed facts on the SD worker, never on the audio callback.
    mergeFact(key,value);
   }
   if(gymCancellation(String(e.question)))removeSupersededGymPlan();
   consolidatePreferences(String(e.question));
   {
    if(factRevision!=revisionBefore && persistFacts())memorizedNoticeSeq++;
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
 if(!consolidationCandidates)consolidationCandidates=xQueueCreate(8,sizeof(ConsolidationCandidate));
 if(!consolidatedFacts)consolidatedFacts=xQueueCreate(8,sizeof(ConsolidatedFact));
 if(!searches)searches=xQueueCreate(1,sizeof(SearchRequest));
 if(writes && !worker)
  xTaskCreatePinnedToCore(task,"kitty_sd",6144,nullptr,1,&worker,0);
}
inline bool ready(){return mounted;}
} // namespace KittyMemory
