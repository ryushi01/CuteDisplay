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
static String delegatedCallId, animationResponseId;
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
 requested=false;ready=false;connected=false;started=false;
 remoteResponse=false;streamedSpeech=false;
 delegatedCallId="";animationResponseId="";BrainAI::cancelCallDelegation();
 BrainRealtimeAudio::stop();
 ws.disconnect();
 status("CALL_OFF");
}
inline void fail(const char *why){
 Serial.printf("[CALL] %s; verify Open WebUI key/call permission, TLS and patch\n",why);
 // Stop retries on rejected credentials, unexpected PCM or incompatible server.
 requested=false;ready=false;connected=false;started=false;
 remoteResponse=false;streamedSpeech=false;
 delegatedCallId="";animationResponseId="";BrainAI::cancelCallDelegation();
 BrainRealtimeAudio::stop();
 ws.disconnect();
 status("CALL_ERROR");
}
inline void onEvent(WStype_t event, uint8_t *payload, size_t n){
 if(event==WStype_DISCONNECTED){
  connected=false;ready=false;remoteResponse=false;streamedSpeech=false;
  delegatedCallId="";animationResponseId="";BrainAI::cancelCallDelegation();
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
   failure="I2S_START";
  else{
   ready=true;lastPing=millis();status("CALL_CONNECTING");
  }
 }else if(strcmp(type,"bridge.error")==0){
  failure="AUTH_OR_PROVIDER_ERROR"; // Never log server's sensitive detail.
 }else if(strcmp(type,"bridge.pong")==0){
  lastPing=millis();
 }else if(strcmp(type,"response.created")==0){
  remoteResponse=true;streamedSpeech=false;
  BrainRealtimeAudio::setRemoteReply(true);
  status("CALL_THINKING");
 }else if(strcmp(type,"response.done")==0){
  remoteResponse=false;
  BrainRealtimeAudio::setRemoteReply(false);
  if(!animationResponseId.isEmpty()){
   cJSON *response=cJSON_GetObjectItem(json,"response");
   cJSON *rid=cJSON_GetObjectItem(response,"id");
   if(cJSON_IsString(rid) && animationResponseId==rid->valuestring){
    if(!bridgeRespond("response_id",animationResponseId))
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
     transcript->valuestring && transcript->valuestring[0] &&
     !remoteResponse && delegatedCallId.isEmpty()){
   // Open WebUI turn_detection explicitly sets create_response=false.
   // Without bridge.respond the user would never get a spoken answer.
   if(!bridgeRespond("item_id",String(id->valuestring)))
    failure="VOICE_TURN_REQUEST";
   else status("CALL_THINKING");
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
     if(!bridgeResult(callId,"failed","I could not start the chat model. Please try again.")||
        !bridgeRespond("call_id",callId))failure="DELEGATION_REJECTED";
    }else{
     delegatedCallId=callId;
     status("CALL_THINKING");
    }
   }else if(strcmp(name->valuestring,"play_animation")==0){
    cJSON *out=cJSON_CreateObject();
    cJSON_AddStringToObject(out,"type","bridge.animation.result");
    cJSON_AddStringToObject(out,"call_id",callId.c_str());
    cJSON_AddStringToObject(out,"status","unavailable");
    cJSON *rid=cJSON_GetObjectItem(json,"response_id");
    if(cJSON_IsString(rid))animationResponseId=rid->valuestring;
    if(!sendEvent(out))failure="ANIMATION_RESULT";
   }
  }
 }else if(strcmp(type,"response.output_audio.delta")==0 ||
          strcmp(type,"response.audio.delta")==0){
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
       failure="SPEAKER_QUEUE_OVERFLOW";
     else {streamedSpeech=true;status("CALL_SPEAKING");}
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
 requested=false;started=false;connected=false;ready=false;
 remoteResponse=false;streamedSpeech=false;delegatedCallId="";animationResponseId="";
 status("CALL_OFF");
}
inline bool toggle(bool audioBusy){
 if(requested){stop();return true;}
 if(audioBusy){
  Serial.println("[CALL] PREFLIGHT REFUSED: AUDIO_BUSY");
  status("CALL_ERROR");return false;
 }
 reload();
 if(!valid()){status("CALL_ERROR");return false;}
 requested=true;
 if(!connect()){
  requested=false; // Failed first start is OFF, not a hidden active session.
  status("CALL_ERROR");
  return false;
 }
 return true;
}
inline void tick(bool audioBusy){
 if(!requested)return;
 if(WiFi.status()!=WL_CONNECTED){
  if(started){BrainRealtimeAudio::stop();ws.disconnect();started=false;connected=false;ready=false;}
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
 if(!delegatedCallId.isEmpty()){
  String answer;
  bool ok=false;
  if(BrainAI::takeCallDelegation(answer,ok)){
   String doneId=delegatedCallId;
   delegatedCallId="";
   if(!bridgeResult(doneId,ok?"completed":"failed",answer)||
      !bridgeRespond("call_id",doneId)){
    fail("DELEGATION_RESULT_SEND");return;
   }
   status("CALL_THINKING");
  }
 }
 if(ready){
  if(BrainRealtimeAudio::failed()){fail("I2S_RUNTIME");return;}
  if(BrainRealtimeAudio::initialized()){
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
   if(BrainRealtimeAudio::hasSpeakerAudio() || (streamedSpeech&&remoteResponse)){
    status("CALL_SPEAKING");
   }else if(remoteResponse){
    status("CALL_THINKING");
   }else{
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
