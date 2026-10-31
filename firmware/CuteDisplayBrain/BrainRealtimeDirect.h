#pragma once
// Experimental ONE-server WSS transport for Open WebUI's native Realtime bridge.
// Uses existing saved BrainAI HTTPS URL + cutedisplay-ai model + revocable sk-
// credential. No second gateway, provider URL, account password, OTP or JWT.
// REQUIRES version-checked API-key support on Open WebUI realtime WebSocket.
// EXPERIMENTAL: live 24k PCM mic + speaker. Hardware testing not yet completed.
// C5 left short tap toggles session; manual long-hold PTT stays unchanged.
// Links2004 arduinoWebSockets 2.7.2; ESP32 Arduino 3.3.12.
// WSS must use embedded verified ESP-IDF certificate bundle, NEVER setInsecure.
#include <Arduino.h>
#include <WiFi.h>
#include <Preferences.h>
#include <WebSocketsClient.h>
#include <esp_arduino_version.h>
#include <cJSON.h>
#include <mbedtls/base64.h>
#include <esp_heap_caps.h>
#include "BrainClock.h"
#include "BrainAudioTest.h"
#include "BrainRealtimeAudio.h"
#include "BrainAI.h"
#include "KittyMemoryContextV6.h"

namespace BrainRealtimeDirect {
extern const uint8_t ca_bundle_start[] asm("_binary_x509_crt_bundle_start");
extern const uint8_t ca_bundle_end[] asm("_binary_x509_crt_bundle_end");
static WebSocketsClient ws;
static bool requested=false, started=false, connected=false, ready=false;
// Provider memory updates are opt-in and disabled unless the authenticated
// gateway explicitly advertises support. Never require them for a voice call.
static bool memoryRefreshSupported=false;
static bool semanticPending=false;
static String semanticRequestId,semanticSpeaker,semanticTurnId,semanticContext,semanticTranscript;
static uint32_t semanticRequestedAt=0,semanticSequence=0;
inline void clearSemanticTurn(){
 semanticPending=false;semanticRequestId="";semanticSpeaker="";semanticTurnId="";
 semanticContext="";semanticTranscript="";semanticRequestedAt=0;
}
inline void requestSemanticTurn(const String &turnId,const String &speaker,
                                const String &provenance,const String &transcript){
 // Speaker-scoped optional recall; no wait for an HTTP lookup in the audio path.
 if(!memoryRefreshSupported || !ready || speaker=="unknown" ||
    speaker.isEmpty() || transcript.isEmpty() || semanticPending)return;
 if(!speaker.startsWith("person:") || speaker.length()<=7 ||
    (provenance!="voice_probable" && provenance!="explicit_introduction") ||
    speaker.length()>60 || transcript.length()>300 ||
    turnId.isEmpty() || turnId.length()>160)return;
 String id="s"+String(++semanticSequence);
 cJSON *m=cJSON_CreateObject();
 if(!m)return;
 cJSON_AddStringToObject(m,"type","kitty.memory.semantic");
 cJSON_AddStringToObject(m,"request_id",id.c_str());
 cJSON_AddStringToObject(m,"turn_id",turnId.c_str());
 cJSON_AddStringToObject(m,"speaker_id",speaker.c_str());
 cJSON_AddStringToObject(m,"provenance",provenance.c_str());
 cJSON_AddStringToObject(m,"query",transcript.c_str());
 char *wire=cJSON_PrintUnformatted(m);cJSON_Delete(m);
 if(!wire)return;
 bool sent=ws.sendTXT(wire);free(wire);
 if(sent){semanticRequestId=id;semanticSpeaker=speaker;semanticTurnId=turnId;
          semanticPending=true;semanticRequestedAt=millis();semanticContext="";
          semanticTranscript=transcript;}
}

static uint32_t memoryFactSeen=0,memorySummarySeen=0,memoryRefreshSeq=0,memoryLastAttempt=0,memoryDaySeen=0,memoryMinuteSeen=0;
static bool remoteResponse=false, streamedSpeech=false;
static bool bargeCancelling=false;
static String deferredVoiceItem;
static String captionPending;
static String captionDeferred;
static String liveKittyCaption;
static uint32_t captionLastSent=0;
inline void appendLiveKitty(const String &delta){
 if(delta.isEmpty())return;
 if(liveKittyCaption.length()+delta.length()>760){
  int cut=(int)(liveKittyCaption.length()+delta.length()-760);
  while(cut<(int)liveKittyCaption.length() &&
    ((uint8_t)liveKittyCaption[cut]&0xC0)==0x80)cut++;
  liveKittyCaption.remove(0,cut);
 }
 liveKittyCaption+=delta;
}
static size_t captionOffset=0;
static bool captionReady=false;
// Chunk long UTF-8 captions into the existing 80-byte UART channel.
// '0' begins a new caption; '1' appends its continuation on the C5.
inline bool takeCaption(String &out){
 if(!captionReady)return false;
 const size_t remaining=captionPending.length()-captionOffset;
 size_t count=min((size_t)76,remaining);
 if(count<remaining){
  while(count>0 && ((uint8_t)captionPending[captionOffset+count]&0xC0)==0x80)count--;
 }
 if(count==0){captionReady=false;return false;}
 out=(captionOffset==0?"0":"1");
 out+=captionPending.substring(captionOffset,captionOffset+count);
 captionOffset+=count;
 if(captionOffset>=captionPending.length()){
  captionReady=false;captionPending="";captionOffset=0;
  if(!captionDeferred.isEmpty()){
   captionPending=captionDeferred;
   captionDeferred="";
   captionReady=true;
  }
 }
 return true;
}
inline void queueCaption(const char *speaker,const char *words){
 if(!words || !*words)return;
 String c=String(speaker)+String(words);
 // Bound UI-only storage, never split a UTF-8 code point.
 if(c.length()>768){
  int begin=c.length()-768;
  while(begin<c.length() && ((uint8_t)c[begin]&0xC0)==0x80)begin++;
  c=c.substring(begin);
 }
 if(captionReady){captionDeferred=c;return;}
 captionPending=c;captionOffset=0;captionReady=true;
}
static bool playbackSpeechDetected=false;
static String delegatedCallId, animationResponseId;
static String waitingDelegationId,waitingDelegationPrompt;
static uint32_t waitingDelegationAt=0;
// The provider must finish the initial tool-call response before bridge.respond.
static bool toolResponseFinished=false;
static String failedCallId, failedCallAnswer;
// Temporary 0..15 Kitty expression selected by realtime avatar gestures or
// assistant speech. No change to the model, account, or persistent C5 mood.
static int pendingMood=-1;
static uint8_t explicitMoodQueue[8];
static uint8_t moodQueueHead=0,moodQueueCount=0;
static uint32_t lastQueuedMoodSentAt=0;
inline void clearMoodQueue(){moodQueueHead=0;moodQueueCount=0;lastQueuedMoodSentAt=0;}
static uint8_t currentMood=1;
static uint32_t moodUpdatedAt=0;
static uint32_t lastExplicitMoodAt=0; // AI tool is authoritative over text heuristics
static uint32_t expressionIdleSince=0; // debounce gaps between tool responses/audio chunks
inline int emotionForText(String phrase){
 phrase.toLowerCase();
 // English, French and Japanese. Sentiment fallback is intentionally
 // conservative; explicitly AI-selected play_animation gestures have priority.
 if(phrase.indexOf("surprised")>=0 || phrase.indexOf("びっくり")>=0)return 8;
 if(phrase.indexOf("confused")>=0 || phrase.indexOf("困惑")>=0)return 9;
 if(phrase.indexOf("laugh")>=0 || phrase.indexOf("笑っ")>=0)return 10;
 if(phrase.indexOf("worried")>=0 || phrase.indexOf("心配")>=0)return 11;
 if(phrase.indexOf("playful")>=0 || phrase.indexOf("いたずら")>=0)return 12;
 if(phrase.indexOf("love")>=0 || phrase.indexOf("大好き")>=0)return 13;
 if(phrase.indexOf("bored")>=0 || phrase.indexOf("退屈")>=0)return 14;
 if(phrase.indexOf("proud")>=0 || phrase.indexOf("誇らし")>=0)return 15;
 if(phrase.indexOf("angry")>=0 || phrase.indexOf("furious")>=0 ||
    phrase.indexOf("fâché")>=0 || phrase.indexOf("怒")>=0)return 3;
 if(phrase.indexOf("sad")>=0 || phrase.indexOf("sorry")>=0 ||
    phrase.indexOf("triste")>=0 || phrase.indexOf("悲し")>=0 ||
    phrase.indexOf("ごめん")>=0)return 2;
 if(phrase.indexOf("excited")>=0 || phrase.indexOf("amazing")>=0 ||
    phrase.indexOf("wonderful")>=0 || phrase.indexOf("génial")>=0 ||
    phrase.indexOf("やった")>=0 || phrase.indexOf("すごい")>=0 ||
    phrase.indexOf("楽し")>=0)return 6;
 if(phrase.indexOf("sleepy")>=0 || phrase.indexOf("tired")>=0 ||
    phrase.indexOf("眠")>=0)return 5;
 if(phrase.indexOf("shy")>=0 || phrase.indexOf("blush")>=0 ||
    phrase.indexOf("恥ずかし")>=0 || phrase.indexOf("照れ")>=0)return 7;
 if(phrase.indexOf("hungry")>=0 || phrase.indexOf("お腹")>=0)return 4;
 if(phrase.indexOf("happy")>=0 || phrase.indexOf("嬉し")>=0 ||
    phrase.indexOf("ありがとう")>=0)return 1;
 return -1;
}
inline int emotionForGesture(String name){
 name.toLowerCase();
 if(name.indexOf("surpris")>=0||name.indexOf("shock")>=0)return 8;
 if(name.indexOf("confus")>=0||name.indexOf("puzzl")>=0)return 9;
 if(name.indexOf("laugh")>=0||name.indexOf("giggl")>=0)return 10;
 if(name.indexOf("worri")>=0||name.indexOf("nervous")>=0)return 11;
 if(name.indexOf("playful")>=0||name.indexOf("wink")>=0)return 12;
 if(name.indexOf("love")>=0||name.indexOf("heart")>=0)return 13;
 if(name.indexOf("bored")>=0||name.indexOf("unimpress")>=0)return 14;
 if(name.indexOf("proud")>=0||name.indexOf("smug")>=0)return 15;
 if(name.indexOf("angry")>=0||name.indexOf("mad")>=0||
    name.indexOf("frown")>=0)return 3;
 if(name.indexOf("sad")>=0||name.indexOf("cry")>=0||
    name.indexOf("disappoint")>=0)return 2;
 if(name.indexOf("excite")>=0||name.indexOf("cheer")>=0||
    name.indexOf("celebrat")>=0||name.indexOf("jump")>=0)return 6;
 if(name.indexOf("sleep")>=0||name.indexOf("tired")>=0)return 5;
 if(name.indexOf("shy")>=0||name.indexOf("blush")>=0||
    name.indexOf("embarrass")>=0)return 7;
 if(name.indexOf("hungry")>=0)return 4;
 if(name.indexOf("happy")>=0||name.indexOf("smile")>=0||
    name.indexOf("wave")>=0||name.indexOf("laugh")>=0)return 1;
 if(name.indexOf("neutral")>=0||name.indexOf("nod")>=0||
    name.indexOf("think")>=0||name.indexOf("look")>=0)return 0;
 return -1;
}
inline void chooseMood(int m,bool explicitGesture){
 if(m<0 || m>15 || !requested)return;
 uint32_t now=millis();
 // An explicit realtime tool choice wins for its full displayed lifetime;
 // optional fragmentary transcript keywords must never overwrite it.
 if(!explicitGesture && lastExplicitMoodAt &&
    (uint32_t)(now-lastExplicitMoodAt)<10000UL)return;
 if(!explicitGesture && (uint32_t)(now-moodUpdatedAt)<1400UL)return;
 if(explicitGesture)lastExplicitMoodAt=now;
 if(m==currentMood && !explicitGesture)return;
 currentMood=(uint8_t)m;
 if(explicitGesture){
  // Preserve all model-selected moods even when multiple tool calls complete
  // in one Arduino loop iteration. Display them sequentially during speech.
  if(moodQueueCount<8){
   explicitMoodQueue[(moodQueueHead+moodQueueCount)%8]=(uint8_t)m;
   moodQueueCount++;
  }else{
   // Keep the most recent instruction if the provider exceeds the queue.
   explicitMoodQueue[(moodQueueHead+7)%8]=(uint8_t)m;
  }
  pendingMood=-1;
 }else if(moodQueueCount==0)pendingMood=m;
 moodUpdatedAt=now;expressionIdleSince=0;
}
inline bool takeMood(uint8_t &result){
 if(!requested)return false;
 if(moodQueueCount){
  // C5 only shows AI moods when SPEAKING; do not drain the queue while
  // thinking. 850ms minimum per mood makes rapid tool calls visible.
  if(!BrainRealtimeAudio::hasSpeakerAudio() &&
     !(streamedSpeech && remoteResponse))return false;
  if(lastQueuedMoodSentAt && (uint32_t)(millis()-lastQueuedMoodSentAt)<850UL)
   return false;
  result=explicitMoodQueue[moodQueueHead];
  moodQueueHead=(moodQueueHead+1)%8;
  moodQueueCount--;
  lastQueuedMoodSentAt=millis();
  return true;
 }
 if(pendingMood<0)return false;
 result=(uint8_t)pendingMood;pendingMood=-1;return true;
}
// C5 does not have to implement any new server protocol; only S3 owns it.
static constexpr size_t MAX_EVENT_BYTES=65536;
static uint32_t lastAttempt=0, lastPing=0;
static String url, model, key;
static String state="CALL_OFF";
static constexpr uint32_t RECONNECT_DELAY=10000;
static constexpr uint32_t PING_INTERVAL=20000;

// JSON sent only from the Arduino loop and WebSocket callback (same core).
inline bool sendEvent(cJSON *obj){
 if(!obj)return false;
 char *body=cJSON_PrintUnformatted(obj);
 cJSON_Delete(obj);
 if(!body)return false;
 const bool ok=ws.sendTXT(body);
 free(body);
 return ok;
}
inline bool bridgeRespond(const char *which,const String &id){
 if(id.isEmpty()||id.length()>160)return false;
 cJSON *event=cJSON_CreateObject();
 if(!event)return false;
 cJSON_AddStringToObject(event,"type","bridge.respond");
 cJSON_AddStringToObject(event,which,id.c_str());
 return sendEvent(event);
}
// Open WebUI has a DIFFERENT continuation event for avatar/expression tools
// than for chat-model delegation. The wrong command closes the WebSocket.
inline bool bridgeAnimationRespond(const String &responseId){
 if(responseId.isEmpty()||responseId.length()>160)return false;
 cJSON *event=cJSON_CreateObject();
 if(!event)return false;
 cJSON_AddStringToObject(event,"type","bridge.animation.respond");
 cJSON_AddStringToObject(event,"response_id",responseId.c_str());
 return sendEvent(event);
}
inline bool bridgeResult(const String &id,const char *outcome,const String &answer){
 if(id.isEmpty()||id.length()>160 || answer.length()>1600)return false;
 cJSON *event=cJSON_CreateObject();
 if(!event)return false;
 cJSON_AddStringToObject(event,"type","bridge.result");
 cJSON_AddStringToObject(event,"call_id",id.c_str());
 cJSON_AddStringToObject(event,"status",outcome);
 cJSON_AddStringToObject(event,"answer",answer.c_str());
 return sendEvent(event);
}
inline bool active(){return requested;}
inline bool isReady(){return requested&&ready;}
inline String activity(){return state;}
inline void status(const char* next){
 if(state==next)return;
 state=next;
 Serial.printf("[CALL] %s\n",next);
}
inline void reload(){
 Preferences p;
 url=""; model=""; key="";
 if(p.begin("brain-ai",true)){
  url=p.getString("url","");
  model=p.getString("model","");
  key=p.getString("key","");
  p.end();
 }
 if(url.endsWith("/"))url.remove(url.length()-1);
}
// Fixed reason codes only: NEVER print the URL, model, key or their bytes.
// This local preflight does NOT validate server-side permissions or credentials.
inline const char *preflightError(){
 if(WiFi.status()!=WL_CONNECTED)return "S3_WIFI_OFFLINE";
 if(!BrainClock::valid())return "S3_CLOCK_UNSYNCED";
 if(url.isEmpty())return "OPENWEBUI_URL_MISSING";
 if(url!="https://ragnarok-project.com" &&
    !url.startsWith("https://ragnarok-project.com/"))
  return "OPENWEBUI_URL_INVALID";
 if(model.isEmpty()||model.length()>128)return "OPENWEBUI_MODEL_MISSING_OR_INVALID";
 if(!key.startsWith("sk-")||key.length()<=20)return "S3_SAVED_KEY_NOT_VALID_SK_FORMAT";
 return nullptr;
}
inline bool valid(){return preflightError()==nullptr;}
inline void diagnose(bool audioBusy){
 reload();
 const char *err=preflightError();
 if(audioBusy)Serial.println("[CALL] DIAG: AUDIO_BUSY");
 else if(err)Serial.printf("[CALL] DIAG: %s\n",err);
 else Serial.println("[CALL] DIAG: PREFLIGHT_PASS");
 Serial.printf("[CALL] DIAG: wifi_connected=%d clock_valid=%d url_configured=%d model_configured=%d sk_key_format=%d audio_busy=%d\n",
  WiFi.status()==WL_CONNECTED?1:0,BrainClock::valid()?1:0,
  !url.isEmpty()?1:0,!model.isEmpty()?1:0,
  key.startsWith("sk-")&&key.length()>20?1:0,audioBusy?1:0);
}
inline void stop(){
 clearMoodQueue();pendingMood=-1;currentMood=1;lastExplicitMoodAt=0;expressionIdleSince=0;moodUpdatedAt=0;expressionIdleSince=0;
 requested=false;ready=false;connected=false;started=false;
 clearSemanticTurn();waitingDelegationId="";waitingDelegationPrompt="";waitingDelegationAt=0;
 deferredVoiceItem="";playbackSpeechDetected=false;
 remoteResponse=false;streamedSpeech=false;
 delegatedCallId="";animationResponseId="";toolResponseFinished=false;
 failedCallId="";failedCallAnswer="";BrainAI::cancelCallDelegation();
 BrainRealtimeAudio::stop();
 ws.disconnect();
 status("CALL_OFF");
}
inline void fail(const char *why){
 clearMoodQueue();pendingMood=-1;currentMood=1;lastExplicitMoodAt=0;moodUpdatedAt=0;
 const bool localAudio=(strcmp(why,"I2S_RUNTIME")==0 ||
   strcmp(why,"AUDIO_TASK_ALLOC")==0 ||
   strncmp(why,"NO_PSRAM",8)==0 ||
   strncmp(why,"PSRAM_",6)==0 ||
   strncmp(why,"STATIC_",7)==0);
 if(localAudio)
  Serial.printf("[CALL] LOCAL AUDIO FAULT: %s (no Open WebUI configuration change needed)\n",why);
 else
  Serial.printf("[CALL] %s (WebSocket / audio protocol or hardware; check detailed preceding log)\n",why);
 // Stop retries on rejected credentials, unexpected PCM or incompatible server.
 clearSemanticTurn();waitingDelegationId="";waitingDelegationPrompt="";waitingDelegationAt=0;
 requested=false;ready=false;connected=false;started=false;
 remoteResponse=false;streamedSpeech=false;
 delegatedCallId="";animationResponseId="";toolResponseFinished=false;
 failedCallId="";failedCallAnswer="";BrainAI::cancelCallDelegation();
 BrainRealtimeAudio::stop();
 ws.disconnect();
 status("CALL_ERROR");
}
// V6 speaker recognition is probabilistic and turn-scoped; never owner auth.
static String pendingSpeakerItem, pendingSpeakerTranscript;
static uint32_t pendingSpeakerAt=0;
// Unverified conversation name: reset per call, never owner authorization.
static String introducedSpeaker;
inline String selfIntroducedSpeaker(const String &utterance){
 String key,value;
 if(!KittyMemory::extractFact(utterance,key,value) || key!="name")return "";
 value.trim();
 if(value.length()<2 || value.length()>32)return "";
 for(size_t i=0;i<value.length();i++){
  char ch=value[i];
  if(!((ch>='A'&&ch<='Z')||(ch>='a'&&ch<='z')||
       (ch>='0'&&ch<='9')||ch=='-'||ch=='_'))return "";
 }
 value.toLowerCase();return "person:"+value;
}
inline void flushPendingSpeaker(bool timedOut=false){
 if(pendingSpeakerItem.isEmpty())return;
 if(!timedOut && (uint32_t)(millis()-pendingSpeakerAt)<1100UL)return;
 (void)KittyMemory::queueAttributed(pendingSpeakerTranscript,"[voice transcript]",
   introducedSpeaker.isEmpty()?String("unknown"):introducedSpeaker,
   introducedSpeaker.isEmpty()?String("unverified"):String("explicit_introduction"));
 pendingSpeakerItem="";pendingSpeakerTranscript="";pendingSpeakerAt=0;
}

inline void onEvent(WStype_t event, uint8_t *payload, size_t n){
 if(event==WStype_DISCONNECTED){
  Serial.printf("[CALL NET] ws_disconnected requested=%d connected=%d ready=%d state=%s wifi=%d rssi=%d free_internal=%lu largest_internal=%lu free_psram=%lu buffered_ms=%lu skipped_ms=%lu\\n",
   requested?1:0,connected?1:0,ready?1:0,state.c_str(),
   WiFi.status()==WL_CONNECTED?1:0,WiFi.RSSI(),
   (unsigned long)heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
   (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
   (unsigned long)heap_caps_get_free_size(MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT),
   (unsigned long)BrainRealtimeAudio::bufferedMs(),
   (unsigned long)BrainRealtimeAudio::droppedSpeakerMs());
  pendingMood=-1;currentMood=1;lastExplicitMoodAt=0;
  connected=false;ready=false;remoteResponse=false;streamedSpeech=false;
  memoryRefreshSupported=false;memoryRefreshSeq=0;clearSemanticTurn();introducedSpeaker="";
  waitingDelegationId="";waitingDelegationPrompt="";waitingDelegationAt=0;
 deferredVoiceItem="";playbackSpeechDetected=false;
  delegatedCallId="";animationResponseId="";toolResponseFinished=false;
  failedCallId="";failedCallAnswer="";BrainAI::cancelCallDelegation();
  BrainRealtimeAudio::stop();
  if(requested)status("CALL_CONNECTING");
  return;
 }
 if(event==WStype_CONNECTED){
  connected=true;
  cJSON* auth=cJSON_CreateObject();
  if(!auth){fail("JSON");return;}
  cJSON_AddStringToObject(auth,"type","auth");
  cJSON_AddStringToObject(auth,"token",key.c_str());
  cJSON_AddStringToObject(auth,"model_id",model.c_str());
  // Optional server-side feature negotiation. Unpatched/older Open WebUI
  // safely ignores this field and preserves the proven audio path.
  // It enables set_expression ONLY for this Kitty-capable S3, never for
  // ordinary browser/mobile voice clients.
  cJSON_AddBoolToObject(auth,"kitty_expressions",true);
  cJSON_AddBoolToObject(auth,"kitty_memory_refresh",true);
  // Opt in to gateway voice recognition when running the V6 experimental build.
  // Older gateways ignore this field and preserve existing realtime behavior.
  cJSON_AddBoolToObject(auth,"kitty_voice_v6",true);
  memoryRefreshSupported=false;memoryRefreshSeq=0;
  memoryDaySeen=BrainClock::localDayKey();
  memoryMinuteSeen=BrainClock::valid()?(uint32_t)(time(nullptr)/60):0;
  memoryFactSeen=KittyMemory::factRevision;
  memorySummarySeen=KittyMemory::summaryRevision;
  // Only ephemeral facts travel with this authenticated session. No server storage.
  String facts=KittyMemoryContextV6::snapshot(580,170,820);
  if(!facts.isEmpty())cJSON_AddStringToObject(auth,"kitty_sd_memory",facts.c_str());
  char* json=cJSON_PrintUnformatted(auth);
  cJSON_Delete(auth);
  if(!json){fail("JSON");return;}
  bool sent=ws.sendTXT(json);
  free(json);
  if(!sent)fail("AUTH_TX");
  return;
 }
 if(event!=WStype_TEXT)return;
 if(!n||n>MAX_EVENT_BYTES){fail("OVERSIZED_EVENT");return;}
 // JSON parsing happens only on the Arduino loop (Core 1). Never parse on
 // the 24kHz I2S task, and never log transcription or response audio.
 // Parse the bounded WebSocket payload directly. Avoid duplicating up to
 // tens of KB of base64 TTS JSON in internal heap on every audio frame.
 cJSON* json=cJSON_ParseWithLength((const char*)payload,n);
 if(!json){fail("JSON_PARSE");return;}
 cJSON *typ=cJSON_GetObjectItem(json,"type");
 const char *type=cJSON_IsString(typ)?typ->valuestring:"";
 const char *failure=nullptr;
 if(strcmp(type,"bridge.ready")==0){
  cJSON* rate=cJSON_GetObjectItem(json,"sample_rate");
  if(!cJSON_IsNumber(rate)||rate->valueint!=24000)failure="SAMPLE_RATE";
  else if(!BrainRealtimeAudio::start(BrainAudioTest::micGain,
                                     BrainAudioTest::speakerVolume))
   failure=BrainRealtimeAudio::issue(); // precise local allocation reason
  else{
   ready=true;lastPing=millis();status("CALL_CONNECTING");
  }
 }else if(strcmp(type,"kitty.memory.capabilities")==0){
  cJSON* flag=cJSON_GetObjectItem(json,"refresh");
  memoryRefreshSupported=cJSON_IsTrue(flag);
  Serial.printf("[CALL MEMORY] live_refresh=%d\n",memoryRefreshSupported?1:0);
 }else if(strcmp(type,"kitty.memory.refreshed")==0){
  // ACK only: never log the user's personal memory text.
  Serial.println("[CALL MEMORY] context refresh accepted");
 }else if(strcmp(type,"bridge.error")==0){
  failure="AUTH_OR_PROVIDER_ERROR"; // Never log server's sensitive detail.
 }else if(strcmp(type,"bridge.pong")==0){
  lastPing=millis();
 }else if(strcmp(type,"response.created")==0){
  remoteResponse=true;streamedSpeech=false;expressionIdleSince=0;
  liveKittyCaption="";captionLastSent=0;
  playbackSpeechDetected=false;
  bargeCancelling=false;BrainRealtimeAudio::resetBarge();
  BrainRealtimeAudio::setRemoteReply(true);
  status("CALL_THINKING");
 }else if(strcmp(type,"response.done")==0){
  remoteResponse=false;bargeCancelling=false;
  // Keep the microphone muted during the chat-model handoff; otherwise the
  // provider might transcribe the user again while a tool answer is pending.
  const bool waitingForTool=!delegatedCallId.isEmpty() || !failedCallId.isEmpty();
  BrainRealtimeAudio::setRemoteReply(waitingForTool);
  if(waitingForTool)toolResponseFinished=true;
  if(!animationResponseId.isEmpty()){
   cJSON *response=cJSON_GetObjectItem(json,"response");
   cJSON *rid=cJSON_GetObjectItem(response,"id");
   if(cJSON_IsString(rid) && animationResponseId==rid->valuestring){
    if(!bridgeAnimationRespond(animationResponseId))
      failure="ANIMATION_CONTINUE";
    animationResponseId="";
   }
  }
 }else if(strcmp(type,"input_audio_buffer.speech_started")==0){
  // A new utterance invalidates an earlier speaker-specific result immediately.
  clearSemanticTurn();
  if(!remoteResponse)status("CALL_LISTENING");
 }else if(strcmp(type,"input_audio_buffer.speech_stopped")==0){
  status("CALL_THINKING");
 }else if(strcmp(type,"kitty.memory.semantic.result")==0){
  cJSON *id=cJSON_GetObjectItem(json,"request_id");
  cJSON *sid=cJSON_GetObjectItem(json,"speaker_id");
  cJSON *ctx=cJSON_GetObjectItem(json,"context");
  cJSON *turn=cJSON_GetObjectItem(json,"turn_id");
  if(semanticPending && cJSON_IsString(turn) && semanticTurnId==turn->valuestring && cJSON_IsString(id) && cJSON_IsString(sid) &&
     cJSON_IsString(ctx) && semanticRequestId==id->valuestring &&
     semanticSpeaker==sid->valuestring &&
     (uint32_t)(millis()-semanticRequestedAt)<1500UL){
   // Do not inject per-speaker results into session-wide memory: that
   // could expose one guest's facts to the next speaker. A per-turn
   // upstream context scope is required before using the payload.
   semanticContext=KittyMemory::clipUTF8(String(ctx->valuestring),640);
   semanticPending=false;
  }
 }else if(strcmp(type,"kitty.speaker.result")==0){
  cJSON *id=cJSON_GetObjectItem(json,"item_id");
  cJSON *sid=cJSON_GetObjectItem(json,"speaker_id");
  cJSON *conf=cJSON_GetObjectItem(json,"confidence");
  if(cJSON_IsString(id) && pendingSpeakerItem==id->valuestring &&
     !pendingSpeakerTranscript.isEmpty()){
   String speaker="unknown",source="unverified";
   if(cJSON_IsString(sid) && cJSON_IsString(conf) &&
      strlen(sid->valuestring)<60){
    if(strcmp(conf->valuestring,"probable")==0 &&
       strncmp(sid->valuestring,"person:",7)==0 && strlen(sid->valuestring)>7){
     speaker=String(sid->valuestring);source="voice_probable";
    }else if(strcmp(conf->valuestring,"claimed")==0 &&
              strncmp(sid->valuestring,"person:",7)==0 &&
              strlen(sid->valuestring)>7){
     // Any introduced person is a claim, never verified owner authentication.
     // Reject control characters to preserve TSV-based speaker boundaries.
     bool safe=true;
     for(const char *p=sid->valuestring;*p;++p)
      if((unsigned char)*p<32 || *p==127){safe=false;break;}
     if(safe){speaker=String(sid->valuestring);source="explicit_introduction";}
    }
   }
   // Enforce the same identifier safety for probabilistic recognition.
   if(speaker!="unknown"){
    for(size_t k=0;k<speaker.length();++k){
     uint8_t c=(uint8_t)speaker[k];
     if(c<=32 || c==127){speaker="unknown";source="unverified";break;}
    }
   }
   if(speaker=="unknown" && !introducedSpeaker.isEmpty()){
    speaker=introducedSpeaker;source="explicit_introduction";
   }
   (void)KittyMemory::queueAttributed(pendingSpeakerTranscript,"[voice transcript]",
                                     speaker,source);
   // Self-claimed identity must not unlock semantic private-memory lookup.
   if(source=="voice_probable")
    requestSemanticTurn(pendingSpeakerItem,speaker,source,pendingSpeakerTranscript);
   pendingSpeakerItem="";pendingSpeakerTranscript="";pendingSpeakerAt=0;
  }
 }else if(strcmp(type,"conversation.item.input_audio_transcription.completed")==0){
  cJSON *id=cJSON_GetObjectItem(json,"item_id");
  cJSON *transcript=cJSON_GetObjectItem(json,"transcript");
  if(cJSON_IsString(transcript) &&
     transcript->valuestring && transcript->valuestring[0]){
   Serial.println("[MEMORY] Realtime user transcript received");
   // A new transcript invalidates every earlier speaker-scoped recall.
   clearSemanticTurn();
   // Await the bounded turn-linked speaker result briefly, but never delay
   // replying or block audio. Unknown is persisted on timeout.
   flushPendingSpeaker(true);
   if(cJSON_IsString(id) && id->valuestring && strlen(id->valuestring)<=160){
    pendingSpeakerItem=String(id->valuestring);
    pendingSpeakerTranscript=KittyMemory::clipUTF8(String(transcript->valuestring),254);
    String intro=selfIntroducedSpeaker(pendingSpeakerTranscript);
    if(!intro.isEmpty())introducedSpeaker=intro;
    pendingSpeakerAt=millis();
   }else{
    (void)KittyMemory::queue(String(transcript->valuestring),"[voice transcript]");
   }
   queueCaption("YOU: ",transcript->valuestring);
   // Realtime voice often responds without delegated BrainAI chat;
   // archive the transcript independently of whether delegation occurs.
   // The answer may arrive later, but user facts must not be dropped.
   if(!cJSON_IsString(id)){cJSON_Delete(json);return;}
   String item(id->valuestring);
   if(remoteResponse || BrainRealtimeAudio::hasSpeakerAudio() ||
      !delegatedCallId.isEmpty() || !animationResponseId.isEmpty()){
    // Accept speech during playback. Don't interrupt Kitty: answer it
    // after speaker PCM and the current response have both finished.
    deferredVoiceItem=item;
    Serial.println("[CALL] DEFERRED_VOICE: captured during reply");
   }else if(!bridgeRespond("item_id",item)){
    failure="VOICE_TURN_REQUEST";
   }else status("CALL_THINKING");
  }
 }else if(strcmp(type,"conversation.item.input_audio_transcription.failed")==0){
  status("CALL_LISTENING");
 }else if(strcmp(type,"response.output_item.done")==0){
  cJSON *item=cJSON_GetObjectItem(json,"item");
  cJSON *kind=cJSON_GetObjectItem(item,"type");
  cJSON *name=cJSON_GetObjectItem(item,"name");
  cJSON *state=cJSON_GetObjectItem(item,"status");
  cJSON *id=cJSON_GetObjectItem(item,"call_id");
  if(cJSON_IsString(kind)&&strcmp(kind->valuestring,"function_call")==0 &&
     cJSON_IsString(name)&&cJSON_IsString(state)&&
     strcmp(state->valuestring,"completed")==0 && cJSON_IsString(id)){
   String callId(id->valuestring);
   if(strcmp(name->valuestring,"generate_chat_completion")==0){
    cJSON *arg=cJSON_GetObjectItem(item,"arguments");
    cJSON *args=cJSON_IsString(arg)?cJSON_Parse(arg->valuestring):nullptr;
    cJSON *request=cJSON_GetObjectItem(args,"request");
    String prompt=cJSON_IsString(request)?String(request->valuestring):String("");
    if(args)cJSON_Delete(args);
    // The realtime voice engine delegates substantive questions to the
    // SAME saved Open WebUI chat model. No second server or key.
    // Use attributed context only if the delegated model request exactly
    // matches the transcript which produced this semantic lookup. No
    // guessing from conversation order, speaker names or similar phrasing.
    // A matching in-flight lookup receives at most 80ms of *nonblocking*
    // grace while ws.loop() continues. Never wait for a different prompt.
    if(semanticPending && !semanticTranscript.isEmpty() &&
       prompt==semanticTranscript && waitingDelegationId.isEmpty() &&
       delegatedCallId.isEmpty() && deferredVoiceItem.isEmpty()){
      waitingDelegationId=callId;
      waitingDelegationPrompt=prompt;
      waitingDelegationAt=millis();
    }else{
      String scoped="";
      if(!semanticPending && !semanticContext.isEmpty() &&
         !semanticTranscript.isEmpty() && prompt==semanticTranscript &&
         (uint32_t)(millis()-semanticRequestedAt)<1500UL &&
         deferredVoiceItem.isEmpty() && delegatedCallId.isEmpty())
        scoped=semanticContext;
      clearSemanticTurn();
      if(!delegatedCallId.isEmpty() || !waitingDelegationId.isEmpty() ||
         prompt.isEmpty() || !BrainAI::startCallDelegation(prompt,scoped)){
        if(!failedCallId.isEmpty())failure="TOOL_QUEUE_FULL";
        else {failedCallId=callId;
         failedCallAnswer="I could not start the chat model. Please try again.";}
      }else{
        delegatedCallId=callId;
        toolResponseFinished=false;
        status("CALL_THINKING");
      }
    }
   }else if(strcmp(name->valuestring,"set_expression")==0 ||
             strcmp(name->valuestring,"play_animation")==0){
    // New set_expression tool has a fixed eight-emotion allowlist and is
    // offered only after S3 capability negotiation. Keep legacy avatar
    // gestures working for servers that already have them.
    // Honor ONLY gestures explicitly validated by the existing bridge;
    // never send unsolicited function/tool calls to the model.
    cJSON *arg=cJSON_GetObjectItem(item,"arguments");
    cJSON *args=cJSON_IsString(arg)?cJSON_Parse(arg->valuestring):nullptr;
    bool expressionTool=strcmp(name->valuestring,"set_expression")==0;
    cJSON *nameParam=cJSON_GetObjectItem(args,expressionTool?"emotion":"name");
    int mood=-1;
    if(cJSON_IsString(nameParam)){
     if(expressionTool){
      static const char* const names[16]={
       "neutral","happy","sad","angry","hungry","sleepy","excited","shy",
       "surprised","confused","laughing","worried","playful","love","bored","proud"
      };
      for(int k=0;k<16;k++)if(strcmp(nameParam->valuestring,names[k])==0){
       mood=k;break;
      }
     }else mood=emotionForGesture(nameParam->valuestring);
    }
    const bool allowed=cJSON_IsTrue(cJSON_GetObjectItem(json,"animation_valid"));
    if(args)cJSON_Delete(args);
    const bool started=allowed && mood>=0;
    if(started){
     chooseMood(mood,true);
     Serial.printf("[CALL FACE] AI set expression=%d (%s)\n",mood,
                   expressionTool?"set_expression":"play_animation");
    }
    cJSON *out=cJSON_CreateObject();
    if(out){
     cJSON_AddStringToObject(out,"type","bridge.animation.result");
     cJSON_AddStringToObject(out,"call_id",callId.c_str());
     cJSON_AddStringToObject(out,"status",started?"started":"unavailable");
     cJSON *rid=cJSON_GetObjectItem(json,"response_id");
     if(cJSON_IsString(rid))animationResponseId=rid->valuestring;
     if(!sendEvent(out))failure="ANIMATION_RESULT";
    }else failure="ANIMATION_ALLOC";
   }
  }
 }else if(strcmp(type,"response.output_audio_transcript.delta")==0 ||
          strcmp(type,"response.output_audio_transcript.done")==0 ||
          strcmp(type,"response.text.delta")==0 ||
          strcmp(type,"response.text.done")==0){
  const bool done=strstr(type,".done")!=nullptr;
  cJSON *speech=cJSON_GetObjectItem(json,done?"transcript":"delta");
  if(!cJSON_IsString(speech))speech=cJSON_GetObjectItem(json,done?"text":"transcript");
  if(cJSON_IsString(speech) && speech->valuestring){
   String excerpt(speech->valuestring);
   if(done){
    // Final transcript is a full snapshot, not a delta.
    if(excerpt.length())liveKittyCaption=excerpt;
    queueCaption("KITTY: ",liveKittyCaption.c_str());
   }else{
    appendLiveKitty(excerpt);
    if((uint32_t)(millis()-captionLastSent)>100UL){
     queueCaption("KITTY: ",liveKittyCaption.c_str());
     captionLastSent=millis();
    }
   }
   int mood=emotionForText(excerpt);
   if(mood>=0)chooseMood(mood,false);
  }
 }else if(strcmp(type,"response.output_audio.delta")==0 ||
          strcmp(type,"response.audio.delta")==0){
  if(bargeCancelling){cJSON_Delete(json);return;}
  cJSON *delta=cJSON_GetObjectItem(json,"delta");
  if(!ready || !cJSON_IsString(delta))failure="BAD_AUDIO_FRAME";
  else{
   size_t encoded=strlen(delta->valuestring);
   // Each provider event must fit in bounded PSRAM; no oversized allocations.
   if(!encoded || encoded>48000 || (encoded&3u))failure="AUDIO_DELTA_SIZE";
   else{
    size_t capacity=(encoded/4)*3;
    uint8_t *pcm=(uint8_t*)heap_caps_malloc(capacity,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if(!pcm)failure="AUDIO_PSRAM";
    else{
     size_t decoded=0;
     int rc=mbedtls_base64_decode(pcm,capacity,&decoded,
          (const unsigned char*)delta->valuestring,encoded);
     if(rc!=0 || !decoded || (decoded&1u))failure="AUDIO_DELTA_BASE64";
     else if(!BrainRealtimeAudio::queueSpeaker(pcm,decoded))
       failure="SPEAKER_BUFFER_UNAVAILABLE";
     else {
      // Incoming TTS can arrive faster than playback; the PSRAM ring
      // absorbs those bursts without disconnecting an authenticated call.
      static uint32_t lastPressureLog=0;
      if(BrainRealtimeAudio::speakerOverrunEvents &&
         millis()-lastPressureLog>=5000UL){
       lastPressureLog=millis();
       Serial.printf("[CALL AUDIO] speaker buffer pressure: buffered=%lu ms peak=%lu ms skipped=%lu ms (call retained)\n",
        (unsigned long)BrainRealtimeAudio::bufferedMs(),
        (unsigned long)BrainRealtimeAudio::peakSpeakerMs(),
        (unsigned long)BrainRealtimeAudio::droppedSpeakerMs());
      }
      streamedSpeech=true;status("CALL_SPEAKING");
     }
     heap_caps_free(pcm);
    }
   }
  }
 }
 cJSON_Delete(json);
 if(failure)fail(failure);
}
inline bool connect(){
 reload();
 if(!valid()){
  const char *reason=preflightError();
  Serial.printf("[CALL] PREFLIGHT REFUSED: %s\n",reason?reason:"UNKNOWN");
  status("CALL_ERROR");return false;
 }
 int end=url.indexOf('/',8);
 String authority=end<0?url.substring(8):url.substring(8,end);
 if(authority.isEmpty()||authority.indexOf('[')>=0||
    authority.indexOf(']')>=0||authority.indexOf(' ')>=0){
  status("CALL_ERROR");return false;
 }
 int split=authority.indexOf(':');
 String host=split<0?authority:authority.substring(0,split);
 uint16_t port=443;
 if(split>=0){
  String value=authority.substring(split+1);
  if(value.isEmpty()||value.length()>5){status("CALL_ERROR");return false;}
  for(size_t i=0;i<value.length();i++)
   if(value[i]<'0'||value[i]>'9'){status("CALL_ERROR");return false;}
  unsigned long number=value.toInt();
  if(number==0||number>65535){status("CALL_ERROR");return false;}
  port=(uint16_t)number;
 }
 if(host.isEmpty()){status("CALL_ERROR");return false;}
 String path=end<0?"":url.substring(end);
 path+="/api/v1/audio/realtime";
 // Distinct in-memory bundle: no TLS disable and no user-supplied certificate.
 const size_t bytes=(size_t)(ca_bundle_end-ca_bundle_start);
 if(bytes<100||bytes>200000){status("CALL_ERROR");return false;}
 ws.onEvent(onEvent);
 ws.beginSslWithBundle(host.c_str(),port,path.c_str(),ca_bundle_start,bytes);
 ws.setReconnectInterval(RECONNECT_DELAY);
 // Allow brief CPU/TLS scheduling stalls without falsely disconnecting voice.
 ws.enableHeartbeat(20000,8000,3);
 started=true;connected=false;ready=false;lastAttempt=millis();
 status("CALL_CONNECTING");
 return true;
}
inline void init(){
 pendingMood=-1;currentMood=1;lastExplicitMoodAt=0;moodUpdatedAt=0;
 requested=false;started=false;connected=false;ready=false;
 remoteResponse=false;streamedSpeech=false;delegatedCallId="";animationResponseId="";
 toolResponseFinished=false;failedCallId="";failedCallAnswer="";
 status("CALL_OFF");
}
inline bool toggle(bool audioBusy){
 if(requested){stop();return true;}
 if(audioBusy){
  Serial.println("[CALL] PREFLIGHT REFUSED: AUDIO_BUSY");
  status("CALL_ERROR");return false;
 }
 reload();
 const char *reason=preflightError();
 // Network and SNTP are transient. Do not require the user to repeatedly
 // press Call while the S3 is finishing startup after a firmware upload.
 if(reason && strcmp(reason,"S3_WIFI_OFFLINE")!=0 &&
    strcmp(reason,"S3_CLOCK_UNSYNCED")!=0){
  Serial.printf("[CALL] PREFLIGHT REFUSED: %s\n",reason);
  status("CALL_ERROR");return false;
 }
 requested=true;
 if(!reason && !connect()){
  requested=false; // Permanent validation failure is OFF, not a hidden session.
  status("CALL_ERROR");
  return false;
 }
 if(reason)status("CALL_CONNECTING");
 return true;
}
inline void tick(bool audioBusy){
 flushPendingSpeaker(false);
 if(semanticPending && (uint32_t)(millis()-semanticRequestedAt)>1500UL)
  clearSemanticTurn();
 if(!requested)return;
 if(WiFi.status()!=WL_CONNECTED){
  if(started){BrainRealtimeAudio::stop();ws.disconnect();started=false;connected=false;ready=false;}
  status("CALL_CONNECTING");return;
 }
 if(!BrainClock::valid()){
  if(started){
   BrainRealtimeAudio::stop();ws.disconnect();
   started=false;connected=false;ready=false;
  }
  status("CALL_CONNECTING");return;
 }
 if(!started){
  if(audioBusy)return; // Do not contend with legacy manual I2S.
  if(millis()-lastAttempt<RECONNECT_DELAY)return;
  if(!connect()){requested=false;status("CALL_ERROR");}
  return;
 }
 ws.loop();
 if(!requested)return; // A callback may have rejected the session.
 if(!waitingDelegationId.isEmpty() &&
    (!semanticPending || (uint32_t)(millis()-waitingDelegationAt)>=80UL)){
  String callId=waitingDelegationId, prompt=waitingDelegationPrompt;
  waitingDelegationId="";waitingDelegationPrompt="";waitingDelegationAt=0;
  String scoped="";
  if(!semanticPending && !semanticContext.isEmpty() &&
     prompt==semanticTranscript && deferredVoiceItem.isEmpty() &&
     (uint32_t)(millis()-semanticRequestedAt)<1500UL)
    scoped=semanticContext;
  clearSemanticTurn();
  if(!delegatedCallId.isEmpty() || !BrainAI::startCallDelegation(prompt,scoped)){
   if(failedCallId.isEmpty()){
    failedCallId=callId;
    failedCallAnswer="I could not start the chat model. Please try again.";
   }
  }else{
   delegatedCallId=callId;toolResponseFinished=false;status("CALL_THINKING");
  }
 }
 if(toolResponseFinished && !failedCallId.isEmpty()){
  String id=failedCallId,answer=failedCallAnswer;
  failedCallId="";failedCallAnswer="";toolResponseFinished=false;
  if(!bridgeResult(id,"failed",answer) ||
     !bridgeRespond("call_id",id)){fail("TOOL_FAILURE_RESULT");return;}
 }
 if(toolResponseFinished && !delegatedCallId.isEmpty()){
  String answer;
  bool ok=false;
  if(BrainAI::takeCallDelegation(answer,ok)){
   String doneId=delegatedCallId;
   delegatedCallId="";toolResponseFinished=false;
   if(ok && !answer.isEmpty())queueCaption("KITTY: ",answer.c_str());
   if(!bridgeResult(doneId,ok?"completed":"failed",answer)||
      !bridgeRespond("call_id",doneId)){
    fail("DELEGATION_RESULT_SEND");return;
   }
   status("CALL_THINKING");
  }
 }
 // Update changed facts without reconnecting, only while voice output and
 // delegated responses are idle. Old gateways never advertise capability.
 if(ready && memoryRefreshSupported && !remoteResponse &&
    !BrainRealtimeAudio::hasSpeakerAudio() &&
    delegatedCallId.isEmpty() && failedCallId.isEmpty() &&
    animationResponseId.isEmpty() && deferredVoiceItem.isEmpty() &&
    waitingDelegationId.isEmpty() && !semanticPending &&
    (uint32_t)(millis()-memoryLastAttempt)>=3000UL &&
    (KittyMemory::factRevision!=memoryFactSeen ||
     KittyMemory::summaryRevision!=memorySummarySeen ||
     (BrainClock::localDayKey() && BrainClock::localDayKey()!=memoryDaySeen) ||
     (BrainClock::valid() && (uint32_t)(time(nullptr)/60)!=memoryMinuteSeen))){
  memoryLastAttempt=millis();
  uint32_t factVersion=KittyMemory::factRevision;
  uint32_t summaryVersion=KittyMemory::summaryRevision;
  uint32_t calendarDay=BrainClock::localDayKey();
  uint32_t calendarMinute=BrainClock::valid()?(uint32_t)(time(nullptr)/60):0;
  String context=KittyMemoryContextV6::snapshot(550,160,820);
  cJSON *message=cJSON_CreateObject();
  if(message){
   cJSON_AddStringToObject(message,"type","kitty.memory.refresh");
   cJSON_AddNumberToObject(message,"revision",++memoryRefreshSeq);
   cJSON_AddStringToObject(message,"memory",context.c_str());
   char *wire=cJSON_PrintUnformatted(message);
   if(wire){
    if(ws.sendTXT(wire)){memoryFactSeen=factVersion;memorySummarySeen=summaryVersion;memoryDaySeen=calendarDay;memoryMinuteSeen=calendarMinute;}
    free(wire);
   }
   cJSON_Delete(message);
  }
 }
 if(ready){
  // Chat model deltas are produced on a separate task. Copy via FreeRTOS
  // queue; emit the first phrase early, then cap screen updates to ~8Hz.
  String piece;
  for(int i=0;i<5 && BrainAI::takeCallStream(piece);i++)
   appendLiveKitty(piece);
  if(!liveKittyCaption.isEmpty() &&
     (uint32_t)(millis()-captionLastSent)>=125UL &&
     (!delegatedCallId.isEmpty())){
   queueCaption("KITTY: ",liveKittyCaption.c_str());
   captionLastSent=millis();
  }
  if(BrainRealtimeAudio::failed()){
   Serial.printf("[CALL] I2S driver fault: %s\n",BrainRealtimeAudio::issue());
   fail("I2S_RUNTIME");return;
  }
  if(BrainRealtimeAudio::initialized()){
   if(BrainRealtimeAudio::takeBargeRequest()){
    // Listening continues while Kitty finishes her sentence.
    // Do not cancel provider or drain the speaker ring.
    playbackSpeechDetected=true;
    Serial.printf("[CALL] OVERLAP_VOICE: mic=%lu speaker_output=%lu detections=%lu\\n",
      (unsigned long)BrainRealtimeAudio::nearMicLevel(),
      (unsigned long)BrainRealtimeAudio::playbackReferenceLevel(),
      (unsigned long)BrainRealtimeAudio::overlapCount());
   }
   // 20ms mono little-endian PCM16, encoded as a native Open WebUI event.
   // Never send more than 2 frames per tick (40ms maximum).
   for(int n=0;n<2;n++){
    BrainRealtimeAudio::Frame frame={};
    if(!BrainRealtimeAudio::takeMic(frame))break;
    unsigned char encoded[4*((sizeof(frame.pcm)+2)/3)+4]={0};
    size_t produced=0;
    if(mbedtls_base64_encode(encoded,sizeof(encoded),&produced,
        (const unsigned char*)frame.pcm,sizeof(frame.pcm))!=0){
     fail("MIC_ENCODE");return;
    }
    String payload;
    if(!payload.reserve(produced+60)){fail("MIC_JSON_ALLOC");return;}
    payload="{\"type\":\"input_audio_buffer.append\",\"audio\":\"";
    payload+=(const char*)encoded;
    payload+="\"}";
    if(!ws.sendTXT(payload)){fail("MIC_SEND");return;}
   }
   if(!deferredVoiceItem.isEmpty() && !remoteResponse &&
      !BrainRealtimeAudio::hasSpeakerAudio() &&
      delegatedCallId.isEmpty() && failedCallId.isEmpty() &&
      animationResponseId.isEmpty()){
    String item=deferredVoiceItem;
    deferredVoiceItem="";
    playbackSpeechDetected=false;
    if(!bridgeRespond("item_id",item)){fail("DEFERRED_VOICE_REQUEST");return;}
    Serial.println("[CALL] DEFERRED_VOICE: processing saved utterance");
    status("CALL_THINKING");
   }
   if(BrainRealtimeAudio::hasSpeakerAudio() || (streamedSpeech&&remoteResponse)){
    expressionIdleSince=0;
    status("CALL_SPEAKING");
   }else if(remoteResponse || !delegatedCallId.isEmpty() ||
             !failedCallId.isEmpty() || !animationResponseId.isEmpty()){
    status("CALL_THINKING");
   }else{
    // An empty speaker ring can occur between tool calls or audio frames.
    // Never erase a freshly-selected emotion on the first idle tick.
    // A completed spoken turn must remain idle for a grace period before
    // reverting to the normal face. New audio/tool activity cancels this.
    if(!expressionIdleSince)expressionIdleSince=millis();
    if(currentMood!=1 && (uint32_t)(millis()-expressionIdleSince)>=2000UL){
     currentMood=1;
     pendingMood=1;
     moodUpdatedAt=millis();
     lastExplicitMoodAt=0;
     Serial.println("[CALL FACE] spoken turn idle; reset mood=1");
    }
    streamedSpeech=false;
    status("CALL_LISTENING");
   }
  }
 }
 if(ready && millis()-lastPing>PING_INTERVAL){
  if(!ws.sendTXT("{\"type\":\"bridge.ping\"}")){fail("PING_SEND");return;}
  lastPing=millis();
 }
}
} // namespace BrainRealtimeDirect
