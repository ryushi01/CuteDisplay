#pragma once
// EXPERIMENTAL opt-in secure *status-only* gateway client. Audio is NOT yet sent.
// Credentials persist across S3 resets; never store WebUI password, TOTP or JWT.
// On a WSS certificate error this client FAILS CLOSED (requires installed CA).
// Requires Arduino WebSockets library 2.7.2 with ESP32 core 3.3.12.
#include <Arduino.h>
#include <Preferences.h>
#include <WiFi.h>
#include <WebSocketsClient.h>
#include <mbedtls/md.h>
#include <cJSON.h>
#include "BrainAI.h"

namespace BrainRealtime {
static WebSocketsClient socket;
static bool started=false,authenticated=false,ready=false,requested=false,autoStart=false;
static String url,deviceKey,caPem;
static String activeField,buffer;
static size_t expected=0;
static uint32_t lastProvision=0;
static String phase="OFF";
static constexpr char DEVICE_ID[]="kitty-s3";
static constexpr size_t MAX_CA=4096;
static constexpr size_t MAX_URL=256;

inline bool validHex(const String &s){
 if(s.length()!=64)return false;
 for(size_t i=0;i<s.length();++i)if(!isxdigit((unsigned char)s[i]))return false;
 return true;
}
inline bool validURL(const String &u){
 if(!u.startsWith("wss://") || u.indexOf('@')>=0 || u.indexOf('#')>=0 ||
    u.indexOf('?')>=0 || u.length()>MAX_URL)return false;
 int hostStart=6, hostEnd=u.indexOf('/',hostStart);
 String authority=hostEnd<0?u.substring(hostStart):u.substring(hostStart,hostEnd);
 if(authority.isEmpty()||authority.indexOf(' ')>=0||authority.indexOf('[')>=0||
    authority.indexOf(']')>=0)return false;
 int colon=authority.indexOf(':');
 if(colon>=0){
  String port=authority.substring(colon+1);
  authority=authority.substring(0,colon);
  if(port.isEmpty()||port.length()>5)return false;
  for(size_t i=0;i<port.length();i++)if(port[i]<'0'||port[i]>'9')return false;
  int number=port.toInt();
  if(number<=0||number>65535)return false;
 }
 return !authority.isEmpty() && authority.indexOf(':')<0;
 // Hostname still MUST match the configured TLS certificate.
}
inline void state(const char *value){
 if(phase==value)return;
 phase=value;
 Serial.printf("[RT] %s\n",value);
 BrainAI::report(value);
}
inline void load(){
 Preferences p;
 if(!p.begin("brain-rt",true))return;
 url=p.getString("url","");
 deviceKey=p.getString("secret","");
 caPem=p.getString("ca","");
 autoStart=p.getBool("auto",false);
 p.end();
}
inline void onSocket(WStype_t kind,uint8_t *payload,size_t length){
 if(kind==WStype_DISCONNECTED){
  authenticated=false;ready=false;
  if(started)state("CONNECTING");
  return;
 }
 if(kind==WStype_CONNECTED){
  state("CONNECTING");return;
 }
 if(kind==WStype_BIN){
  // Audio playback requires shared-clock I2S ownership. Do not silently
  // drop streaming in production; this experimental build forbids mic/audio.
  state("ERROR");requested=false;socket.disconnect();return;
 }
 if(kind!=WStype_TEXT || length>2048)return;
 String json;
 json.reserve(length+1);
 for(size_t i=0;i<length;i++)json+=(char)payload[i];
 cJSON *root=cJSON_Parse(json.c_str());
 if(!root)return;
 cJSON *typ=cJSON_GetObjectItem(root,"type");
 String type=cJSON_IsString(typ)?String(typ->valuestring):String("");
 if(type=="auth.challenge"){
  cJSON *raw=cJSON_GetObjectItem(root,"nonce");
  String nonce=cJSON_IsString(raw)?String(raw->valuestring):String("");
  bool ok=nonce.length()==48;
  for(size_t i=0;i<nonce.length();i++)if(!isxdigit((unsigned char)nonce[i]))ok=false;
  if(!ok || !validHex(deviceKey)){state("ERROR");socket.disconnect();}
  else{
   String msg=String("CuteDisplay-RT-v1|")+DEVICE_ID+"|"+nonce;
   uint8_t secret[32],mac[32];
   for(int i=0;i<32;i++){
    auto nibble=[](char ch)->uint8_t{
     return (uint8_t)(ch<='9'?ch-'0':(ch|32)-'a'+10);
    };
    secret[i]=(nibble(deviceKey[i*2])<<4)|nibble(deviceKey[i*2+1]);
   }
   const mbedtls_md_info_t *info=mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
   int rc=mbedtls_md_hmac(info,secret,sizeof(secret),
                          (const unsigned char*)msg.c_str(),msg.length(),mac);
   memset(secret,0,sizeof(secret));
   if(rc!=0){state("ERROR");socket.disconnect();}
   else{
    static const char digits[]="0123456789abcdef";
    char proof[65]={0};
    for(int i=0;i<32;i++){proof[2*i]=digits[mac[i]>>4];proof[2*i+1]=digits[mac[i]&15];}
    memset(mac,0,sizeof(mac));
    cJSON *auth=cJSON_CreateObject();
    if(auth){
     cJSON_AddStringToObject(auth,"type","auth");
     cJSON_AddStringToObject(auth,"device_id",DEVICE_ID);
     cJSON_AddStringToObject(auth,"proof",proof);
     char *str=cJSON_PrintUnformatted(auth);
     if(str){socket.sendTXT(str);free(str);}
     cJSON_Delete(auth);
    }
    memset(proof,0,sizeof(proof));
   }
  }
 }else if(type=="auth.ok"){
  authenticated=true;state("CONNECTING");
 }else if(type=="session.ready"){
  ready=true;state("LISTENING");
 }else if(type=="state"){
  cJSON *v=cJSON_GetObjectItem(root,"value");
  if(cJSON_IsString(v)&&v->valuestring){
   String label=v->valuestring;
   if(label=="THINKING"||label=="SPEAKING"||
      label=="LISTENING"||label=="USER_SPEAKING"||label=="MUTED")
      state(label=="USER_SPEAKING"?"LISTENING":label.c_str());
  }
 }else if(type=="error"){
  state("ERROR");
  requested=false;
  socket.disconnect();
 }else if(type=="caption"){
  // Caption-to-C5 uses existing ACK-controlled UART stream in next milestone.
  // Do not print or retain users' speech in the serial log.
 }
 cJSON_Delete(root);
}
inline void stop(){
 requested=false;started=false;authenticated=false;ready=false;
 socket.disconnect();
 state("OFF");
}
inline bool start(){
 if(started)return true;
 if(WiFi.status()!=WL_CONNECTED || !validURL(url) || !validHex(deviceKey) ||
    caPem.indexOf("-----BEGIN CERTIFICATE-----")<0 ||
    caPem.indexOf("-----END CERTIFICATE-----")<0){state("ERROR");return false;}
 // Only an explicitly configured certificate may authenticate the gateway.
 int base=6,slash=url.indexOf('/',base);
 String authority=slash<0?url.substring(base):url.substring(base,slash);
 String path=slash<0?"/":url.substring(slash);
 int colon=authority.indexOf(':');
 String host=colon<0?authority:authority.substring(0,colon);
 uint16_t port=colon<0?443:(uint16_t)authority.substring(colon+1).toInt();
 socket.onEvent(onSocket);
 // Never call beginSSL(host,port,path) without a CA: that can disable checks.
 socket.beginSslWithCA(host.c_str(),port,path.c_str(),caPem.c_str());
 socket.setReconnectInterval(6000);
 socket.enableHeartbeat(15000,3000,2);
 started=true;requested=true;state("CONNECTING");
 return true;
}
inline void init(){
 load();
 // "Auto call on boot" is an explicit setting, off by default for privacy.
 requested=autoStart;
}
inline void tick(bool audioBusy){
 if(requested && !started && !audioBusy && WiFi.status()==WL_CONNECTED)start();
 if(started){
  if(!requested || WiFi.status()!=WL_CONNECTED){stop();return;}
  socket.loop();
 }
}
inline bool active(){return started;}
inline bool isReady(){return ready;}
inline bool provision(const String &cmd,String &reply){
 if(cmd=="RT:STATUS"){
  reply=String("ACK:RT_")+phase;return true;
 }
 if(cmd=="RT:START"){
  requested=true;
  reply=start()?"ACK:RT_CONNECTING":"ERR:RT_CONFIG_WIFI_TLS";return true;
 }
 if(cmd=="RT:STOP"){
  stop();reply="ACK:RT_OFF";return true;
 }
 if(cmd=="RT:CLEAR"){
  stop();Preferences p;
  if(p.begin("brain-rt",false)){p.clear();p.end();}
  url="";caPem="";deviceKey="";autoStart=false;
  reply="ACK:RT_CLEARED";return true;
 }
 if(cmd=="RT:AUTO:0"||cmd=="RT:AUTO:1"){
  autoStart=cmd.endsWith("1");
  Preferences p;
  bool ok=p.begin("brain-rt",false);
  if(ok){ok=p.putBool("auto",autoStart)==1;p.end();}
  reply=ok?"ACK:RT_AUTO":"ERR:RT_NVS";return true;
 }
 if(cmd.startsWith("RT:BEGIN:")){
  int sep=cmd.indexOf(':',9);
  if(sep<0){reply="ERR:RT_FORMAT";return true;}
  String field=cmd.substring(9,sep);
  String count=cmd.substring(sep+1);
  size_t limit=field=="U"?MAX_URL:field=="S"?64:field=="C"?MAX_CA:0;
  size_t size=(size_t)count.toInt();
  if(!limit || size==0 || size>limit || count!=String(size)){
   reply="ERR:RT_SIZE";return true;
  }
  activeField=field;expected=size;buffer="";buffer.reserve(expected);
  lastProvision=millis();
  reply="ACK:RT_BEGIN";return true;
 }
 if(cmd.startsWith("RT:DATA:")){
  if(activeField.isEmpty() || millis()-lastProvision>30000){
   reply="ERR:RT_SESSION";return true;
  }
  String hex=cmd.substring(8);
  if(hex.isEmpty() || hex.length()>80 || hex.length()%2){
   reply="ERR:RT_DATA";return true;
  }
  for(size_t i=0;i<hex.length();i+=2){
   char ch1=hex[i],ch2=hex[i+1];
   if(!isxdigit((unsigned char)ch1)||!isxdigit((unsigned char)ch2)||
      buffer.length()>=expected){reply="ERR:RT_DATA";return true;}
   auto digit=[](char ch)->uint8_t{return ch<='9'?ch-'0':(ch|32)-'a'+10;};
   buffer+=(char)((digit(ch1)<<4)|digit(ch2));
  }
  lastProvision=millis();
  reply="ACK:RT_DATA";return true;
 }
 if(cmd=="RT:END"){
  bool valid=buffer.length()==expected;
  if(activeField=="U")valid=valid&&validURL(buffer);
  else if(activeField=="S")valid=valid&&validHex(buffer);
  else if(activeField=="C")valid=valid&&buffer.indexOf("-----BEGIN CERTIFICATE-----")>=0&&
                                buffer.indexOf("-----END CERTIFICATE-----")>=0;
  else valid=false;
  if(!valid){buffer="";activeField="";reply="ERR:RT_FIELD";return true;}
  Preferences p;
  bool ok=p.begin("brain-rt",false);
  String key=activeField=="U"?"url":activeField=="S"?"secret":"ca";
  if(ok){ok=p.putString(key.c_str(),buffer)==buffer.length();p.end();}
  if(ok){
   // Reconnect on next explicit START; do not disrupt an existing call.
   if(activeField=="U")url=buffer;
   if(activeField=="S")deviceKey=buffer;
   if(activeField=="C")caPem=buffer;
  }
  buffer="";activeField="";expected=0;
  reply=ok?"ACK:RT_SAVED":"ERR:RT_NVS";return true;
 }
 return false;
}
}
