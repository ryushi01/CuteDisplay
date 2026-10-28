#pragma once
// Experimental ONE-server WSS transport for Open WebUI's native Realtime bridge.
// Uses existing saved BrainAI HTTPS URL + cutedisplay-ai model + revocable sk-
// credential. No second gateway, provider URL, account password, OTP or JWT.
// REQUIRES version-checked API-key support on Open WebUI realtime WebSocket.
// Status/connection ONLY: no microphone input, audio playback, or fake listening.
// C5 left short tap toggles session; manual long-hold PTT stays unchanged.
// Links2004 arduinoWebSockets 2.7.2; ESP32 Arduino 3.3.12.
// WSS must use embedded verified ESP-IDF certificate bundle, NEVER setInsecure.
#include <Arduino.h>
#include <WiFi.h>
#include <Preferences.h>
#include <WebSocketsClient.h>
#include <esp_arduino_version.h>
#include <cJSON.h>
#include "BrainClock.h"

namespace BrainRealtimeDirect {
extern const uint8_t ca_bundle_start[] asm("_binary_x509_crt_bundle_start");
extern const uint8_t ca_bundle_end[] asm("_binary_x509_crt_bundle_end");
static WebSocketsClient ws;
static bool requested=false, started=false, connected=false, ready=false;
static uint32_t lastAttempt=0, lastPing=0;
static String url, model, key;
static String state="CALL_OFF";
static constexpr uint32_t RECONNECT_DELAY=10000;
static constexpr uint32_t PING_INTERVAL=20000;

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
inline bool valid(){
 if(WiFi.status()!=WL_CONNECTED || !BrainClock::valid())return false;
 if(!url.startsWith("https://")||url.indexOf('@')>=0||
    url.indexOf('#')>=0||url.indexOf('?')>=0||url.length()>256)return false;
 if(!model.length()||model.length()>128 || !key.startsWith("sk-"))return false;
 return true;
}
inline void stop(){
 requested=false;ready=false;connected=false;started=false;
 ws.disconnect();
 status("CALL_OFF");
}
inline void fail(const char *why){
 Serial.printf("[CALL] %s; verify Open WebUI key/call permission, TLS and patch\n",why);
 // Stop retries on rejected credentials or incompatible server.
 requested=false;ready=false;connected=false;started=false;
 ws.disconnect();
 status("CALL_ERROR");
}
inline void onEvent(WStype_t event, uint8_t *payload, size_t n){
 if(event==WStype_DISCONNECTED){
  connected=false;ready=false;
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
 if(event!=WStype_TEXT || !n || n>8192)return;
 String text;
 text.reserve(n+1);
 for(size_t i=0;i<n;i++)text+=(char)payload[i];
 cJSON* json=cJSON_Parse(text.c_str());
 if(!json)return;
 cJSON *typ=cJSON_GetObjectItem(json,"type");
 const char *type=cJSON_IsString(typ)?typ->valuestring:"";
 if(strcmp(type,"bridge.ready")==0){
  cJSON* rate=cJSON_GetObjectItem(json,"sample_rate");
  if(!cJSON_IsNumber(rate)||rate->valueint!=24000)fail("SAMPLE_RATE");
  else {ready=true;lastPing=millis();status("CALL_READY");}
 }else if(strcmp(type,"bridge.error")==0){
  // Error details may contain sensitive information. Do not log them.
  fail("AUTH_OR_CALL_PERMISSION");
 }else if(strcmp(type,"bridge.pong")==0){
  lastPing=millis();
 }else if(strcmp(type,"response.output_audio.delta")==0){
  // No mic/audio hardware in this stage. Refuse unexpected voice frames.
  fail("UNEXPECTED_AUDIO");
 }
 cJSON_Delete(json);
}
inline bool connect(){
 reload();
 if(!valid()){status("CALL_ERROR");return false;}
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
 status("CALL_OFF");
}
inline bool toggle(bool audioBusy){
 if(requested){stop();return true;}
 if(audioBusy){status("CALL_ERROR");return false;}
 reload();
 if(!valid()){status("CALL_ERROR");return false;}
 requested=true;
 return connect();
}
inline void tick(bool audioBusy){
 if(!requested)return;
 if(WiFi.status()!=WL_CONNECTED){
  if(started){ws.disconnect();started=false;connected=false;ready=false;}
  status("CALL_CONNECTING");return;
 }
 if(!started){
  if(audioBusy)return; // Do not contend with legacy manual I2S.
  if(millis()-lastAttempt<RECONNECT_DELAY)return;
  if(!connect()){requested=false;status("CALL_ERROR");}
  return;
 }
 ws.loop();
 if(ready && millis()-lastPing>PING_INTERVAL){
  ws.sendTXT("{\"type\":\"bridge.ping\"}");
  lastPing=millis();
 }
}
} // namespace BrainRealtimeDirect
