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

namespace BrainRealtimeDirect {
extern const uint8_t ca_bundle_start[] asm("_binary_x509_crt_bundle_start");
extern const uint8_t ca_bundle_end[] asm("_binary_x509_crt_bundle_end");
static WebSocketsClient ws;
static bool requested=false, started=false, connected=false, ready=false;
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
// The provider must finish the initial tool-call response before bridge.respond.
static bool toolResponseFinished=false;
static String failedCallId, failedCallAnswer;
// Temporary 0..7 Kitty expression selected by realtime avatar gestures or
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
 if(m<0 || m>7 || !requested)return;
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
 if(!url.startsWith("https://")||url.indexOf('@')>=0||
    url.indexOf('#')>=0||url.indexOf('?')>=0||url.length()>256)
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
 requested=false;ready=false;connected=false;started=false;
 remoteResponse=false;streamedSpeech=false;
 delegatedCallId="";animationResponseId="";toolResponseFinished=false;
 failedCallId="";failedCallAnswer="";BrainAI::cancelCallDelegation();
 BrainRealtimeAudio::stop();
 ws.disconnect();
 status("CALL_ERROR");
}
inline void onEvent(WStype_t event, uint8_t *payload, size_t n){
 if(event==WStype_DISCONNECTED){
  pendingMood=-1;currentMood=1;lastExplicitMoodAt=0;
  connected=false;ready=false;remoteResponse=false;streamedSpeech=false;
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
 String text;
 if(!text.reserve(n+1)){fail("JSON_ALLOC");return;}
 for(size_t i=0;i<n;i++)text+=(char)payload[i];
 cJSON* json=cJSON_Parse(text.c_str());
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
  if(!remoteResponse)status("CALL_LISTENING");
 }else if(strcmp(type,"input_audio_buffer.speech_stopped")==0){
  status("CALL_THINKING");
 }else if(strcmp(type,"conversation.item.input_audio_transcription.completed")==0){
  cJSON *id=cJSON_GetObjectItem(json,"item_id");
  cJSON *transcript=cJSON_GetObjectItem(json,"transcript");
  if(cJSON_IsString(id) && cJSON_IsString(transcript) &&
     transcript->valuestring && transcript->valuestring[0]){
   queueCaption("YOU: ",transcript->valuestring);
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
    if(!delegatedCallId.isEmpty() || prompt.isEmpty() ||
       !BrainAI::startCallDelegation(prompt)){
     if(!failedCallId.isEmpty())failure="TOOL_QUEUE_FULL";
     else {failedCallId=callId;
      failedCallAnswer="I could not start the chat model. Please try again.";}

    }else{
     delegatedCallId=callId;
     toolResponseFinished=false;
     status("CALL_THINKING");
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
      static const char* const names[8]={
       "neutral","happy","sad","angry","hungry","sleepy","excited","shy"
      };
      for(int k=0;k<8;k++)if(strcmp(nameParam->valuestring,names[k])==0){
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
 ws.enableHeartbeat(15000,3000,2);
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
