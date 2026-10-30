#pragma once
// Kitty Updater V6: opt-in HTTPS/443 read-only OTA manifest preflight.
// Does not write flash, change boot partition, reboot, or expose LAN OTA.
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include "KittyMemorySyncV6.h"
#include "KittyOTASafety.h"
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
inline void preflight(){
 if(!configured()||WiFi.status()!=WL_CONNECTED){
  Serial.println("[OTA HTTPS] disabled / WiFi offline");return;
 }
 const auto safety=KittyOTASafety::inspect();
 Serial.printf("[OTA HTTPS] inactive_slot=%lu rollback_supported=%d rollback_pending=%d\n",
  (unsigned long)safety.nextBytes,safety.rollbackSupported?1:0,safety.rollbackPending?1:0);
 WiFiClientSecure tls;
 tls.setCACert(KITTY_SYNC_V6_CA_PEM);
 HTTPClient http;
 http.setConnectTimeout(3000);
 http.setTimeout(6000);
 if(!http.begin(tls,ENDPOINT)){
  Serial.println("[OTA HTTPS] connection init failed");return;
 }
 http.addHeader("Authorization",String("Bearer ")+KITTY_SYNC_V6_DEVICE_TOKEN);
 const int code=http.GET();
 if(code!=200){
  Serial.printf("[OTA HTTPS] manifest HTTP=%d (no flash write)\n",code);
  http.end();return;
 }
 const String body=http.getString();
 http.end();
 if(body.length()>2048){
  Serial.println("[OTA HTTPS] manifest too large");return;
 }
 const String release=field(body,"release_id");
 const String sizeText=field(body,"size");
 const String sha=field(body,"sha256");
 const String imagePath=field(body,"image_path");
 const uint32_t size=(uint32_t)sizeText.toInt();
 if(release.length()<12||release.length()>80||!isHexDigest(sha)||
    imagePath!="/kitty-v6/update/image"||
    String(size)!=sizeText||size<1024||!KittyOTASafety::fitsInactiveSlot(size)){
  Serial.println("[OTA HTTPS] manifest invalid / inactive slot too small");return;
 }
 Serial.printf("[OTA HTTPS] release=%s bytes=%lu sha256=%s\n",
  release.c_str(),(unsigned long)size,sha.c_str());
 Serial.println("[OTA HTTPS] PREFLIGHT_PASS; DOWNLOAD_AND_FLASH_DISABLED");
}
} // namespace KittyHTTPSOTA
