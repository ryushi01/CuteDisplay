#pragma once
// Kitty Updater V6: opt-in HTTPS/443 read-only OTA manifest preflight.
// Does not write flash, change boot partition, reboot, or expose LAN OTA.
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include "KittyMemorySyncV6.h"
#include "KittyOTASafety.h"
#include "KittyOTAWriter.h"
#include "KittyOTAFrames.h"
namespace KittyHTTPSOTA {
static constexpr char ENDPOINT[]="https://ragnarok-project.com/kitty-v6/update/manifest";
inline bool configured() {
 return KittyMemorySyncV6::configured();
}
inline bool isHexDigest(const String &s){
 if(s.length()!=64)return false;
 for(size_t i=0;i<s.length();++i)
  if(!isxdigit((unsigned char)s[i]))return false;
 return true;
}
inline String field(const String &json,const char *name){
 String needle=String("\"")+name+"\"";
 int p=json.indexOf(needle);
 if(p<0)return "";
 p=json.indexOf(':',p+needle.length());
 if(p<0)return "";
 p++;
 while(p<(int)json.length() && isspace((unsigned char)json[p]))p++;
 if(p>=(int)json.length())return "";
 if(json[p]=='"'){
  int end=json.indexOf('"',p+1);
  if(end<0)return "";
  return json.substring(p+1,end);
 }
 int end=p;
 while(end<(int)json.length() && isdigit((unsigned char)json[end]))end++;
 return json.substring(p,end);
}
struct Manifest { String release; String sha; uint32_t size=0; bool valid=false; };
inline bool parseManifest(const String &body,Manifest &m){
 if(body.length()>2048)return false;
 m.release=field(body,"release_id");
 String sizeText=field(body,"size");
 m.sha=field(body,"sha256");
 String imagePath=field(body,"image_path");
 m.size=(uint32_t)sizeText.toInt();
 m.valid=m.release.length()>=12 && m.release.length()<=80 &&
   isHexDigest(m.sha) && imagePath=="/kitty-v6/update/image" &&
   String(m.size)==sizeText && KittyOTASafety::fitsInactiveSlot(m.size);
 return m.valid;
}
inline bool getManifest(Manifest &m){
 if(!configured()||WiFi.status()!=WL_CONNECTED)return false;
 WiFiClientSecure tls; tls.setCACert(KITTY_SYNC_V6_CA_PEM);
 HTTPClient http;http.setConnectTimeout(3000);http.setTimeout(6000);
 http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS);
 if(!http.begin(tls,ENDPOINT))return false;
 http.addHeader("Authorization",String("Bearer ")+KITTY_SYNC_V6_DEVICE_TOKEN);
 const int code=http.GET();
 if(code!=200){Serial.printf("[OTA HTTPS] manifest HTTP=%d\\n",code);http.end();return false;}
 const int len=http.getSize();
 if(len<0 || len>2048){http.end();return false;}
 String body=http.getString();http.end();
 return parseManifest(body,m);
}
inline void preflight(){
 if(!configured()||WiFi.status()!=WL_CONNECTED){
  Serial.println("[OTA HTTPS] disabled / WiFi offline");return;
 }
 const auto safety=KittyOTASafety::inspect();
 Serial.printf("[OTA HTTPS] inactive_slot=%lu rollback_supported=%d rollback_pending=%d\n",
  (unsigned long)safety.nextBytes,safety.rollbackSupported?1:0,safety.rollbackPending?1:0);
 Manifest m;
 if(!getManifest(m)){
  Serial.println("[OTA HTTPS] manifest unavailable or invalid");return;
 }
 Serial.printf("[OTA HTTPS] release=%s bytes=%lu sha256=%s\\n",
  m.release.c_str(),(unsigned long)m.size,m.sha.c_str());
 Serial.println("[OTA HTTPS] PREFLIGHT_PASS; NO FLASH WRITE");
}

// Explicit serial-only stage; never arms boot or reboots. Requires user confirmation.
// This function is intentionally not connected to a background task or remote control.
inline bool stageToInactiveSlot(bool (*stillIdle)()){
 Manifest m;
 if(!stillIdle || !stillIdle() || !getManifest(m)){
  Serial.println("[OTA HTTPS] stage refused: busy / manifest unavailable");return false;
 }
 const auto safety=KittyOTASafety::inspect();
 if(safety.rollbackPending || !safety.rollbackSupported){
  Serial.println("[OTA HTTPS] stage blocked: bootloader rollback not verified");return false;
 }
 uint8_t digest[32]={0};
 if(!KittyOTAFrames::hexDecode(m.sha,digest,sizeof(digest))){
  Serial.println("[OTA HTTPS] invalid digest");return false;
 }
 WiFiClientSecure tls;tls.setCACert(KITTY_SYNC_V6_CA_PEM);
 HTTPClient http;http.setConnectTimeout(3000);http.setTimeout(6000);
 http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS);
 if(!http.begin(tls,"https://ragnarok-project.com/kitty-v6/update/image"))return false;
 http.addHeader("Authorization",String("Bearer ")+KITTY_SYNC_V6_DEVICE_TOKEN);
 const int status=http.GET();
 if(status!=200 || http.getSize()!=(int)m.size){
  Serial.printf("[OTA HTTPS] image rejected HTTP=%d length=%d\\n",status,http.getSize());
  http.end();return false;
 }
 KittyOTAWriter::Session writer;
 if(!stillIdle()||!writer.begin(m.size,digest,true)){
  http.end();return false;
 }
 WiFiClient *stream=http.getStreamPtr();
 uint8_t buffer[2048];
 uint32_t received=0;
 uint32_t lastProgress=millis();
 bool ok=true;
 while(received<m.size){
  if(!stillIdle() || WiFi.status()!=WL_CONNECTED){ok=false;break;}
  int available=stream->available();
  if(available<=0){
   if(!http.connected() || (uint32_t)(millis()-lastProgress)>10000UL){
    ok=false;break;
   }
   delay(5);continue;
  }
  size_t take=(size_t)available;
  if(take>sizeof(buffer))take=sizeof(buffer);
  if(take>m.size-received)take=m.size-received;
  int n=stream->readBytes(buffer,take);
  if(n<=0 || !writer.append(buffer,(size_t)n)){ok=false;break;}
  received+=(uint32_t)n;lastProgress=millis();
  if((received%131072UL)<(uint32_t)n)
   Serial.printf("[OTA HTTPS] staged %lu/%lu\\n",(unsigned long)received,(unsigned long)m.size);
 }
 if(ok)ok=stillIdle() && writer.complete(true);
 if(!ok)writer.abort();
 http.end();
 Serial.printf("[OTA HTTPS] %s bytes=%lu boot_switched=0 reboot=0\\n",
  ok?"INACTIVE_SLOT_VERIFIED":"STAGE_ABORTED",(unsigned long)received);
 return ok;
}
} // namespace KittyHTTPSOTA
