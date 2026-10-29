#pragma once
// UTC SNTP service for S3 Brain. Does not block BLE, UART, audio or AI.
#include <Arduino.h>
#include <WiFi.h>
#include <time.h>
#include <Preferences.h>
#include "esp_sntp.h"
#include "CuteLink.h"
namespace BrainClock {
static bool running=false;
static uint8_t zone=0; // Japan default; persisted on S3.
static constexpr const char *TZ_RULES[]={
 "JST-9","UTC0","CET-1CEST,M3.5.0/2,M10.5.0/3",
 "EST5EDT,M3.2.0/2,M11.1.0/2",
 "PST8PDT,M3.2.0/2,M11.1.0/2",
 "GMT0BST,M3.5.0/1,M10.5.0/2",
 "AEST-10AEDT,M10.1.0/2,M4.1.0/3"
};
inline bool valid();
static void setZone(uint8_t n){
 if(n>=sizeof(TZ_RULES)/sizeof(TZ_RULES[0]))return;
 zone=n;setenv("TZ",TZ_RULES[n],1);tzset();
}
inline void init(){
 Preferences p;if(p.begin("brain-clock",true)){setZone(p.getUChar("zone",0));p.end();}
 else setZone(0);
}
inline bool configure(const String &cmd){
 if(!cmd.startsWith("TIME:ZONE:"))return false;
 String value=cmd.substring(10);
 if(value.isEmpty()||value.length()>2)return false;
 for(char c:value)if(c<'0'||c>'9')return false;
 int n=value.toInt();if(n<0||n>=int(sizeof(TZ_RULES)/sizeof(TZ_RULES[0])))return false;
 setZone(uint8_t(n));
 Preferences p;if(p.begin("brain-clock",false)){p.putUChar("zone",zone);p.end();}
 Serial.printf("[S3 TIME] Zone selection=%u (POSIX TZ rule), clock remains UTC internally\n",(unsigned)zone);
 return true;
}
// Date context is recomputed from the configured local timezone for each
// request, not cached at boot. This survives midnight without a reboot.
inline uint32_t localDayKey(){
 if(!valid())return 0;
 time_t now=time(nullptr);struct tm t={};localtime_r(&now,&t);
 return (uint32_t)((t.tm_year+1900)*10000+(t.tm_mon+1)*100+t.tm_mday);
}
inline String calendarContext(){
 if(!valid())return "";
 time_t now=time(nullptr);struct tm t={};localtime_r(&now,&t);
 const char *days[]={"Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"};
 char date[40]={};snprintf(date,sizeof(date),"%04d-%02d-%02d %02d:%02d",
   t.tm_year+1900,t.tm_mon+1,t.tm_mday,t.tm_hour,t.tm_min);
 String out="Device local date/time: ";out+=date;out+=" (";
 out+=days[t.tm_wday];out+="). Timezone: ";out+=TZ_RULES[zone];
 out+=". Today means this local calendar day; yesterday is the previous calendar day.";
 out+=" A past plan is historical, not automatically completed; never claim it occurred without confirmation.";
 return out;
}
inline String localHHMM(){
 if(!valid())return "";
 time_t now=time(nullptr);tm local={};localtime_r(&now,&local);
 char buf[6];snprintf(buf,sizeof(buf),"%02d:%02d",local.tm_hour,local.tm_min);
 return String(buf);
}
static uint32_t lastDisplayAt=0;
static uint32_t lastDisplayMinute=UINT32_MAX;
inline void sendDisplay(Stream &uart,bool ready){
 if(!ready||!valid())return;
 uint32_t minute=(uint32_t)(time(nullptr)/60);
 if(minute==lastDisplayMinute && millis()-lastDisplayAt<30000UL)return;
 // No C5 ACK needed: fresh clock is broadcast every 30s or minute-change.
 // S3 always sends fully formatted local time; C5 needs no timezone database.
 String label=localHHMM();if(label.length()!=5)return;
 static uint16_t clockSeq=60000;if(++clockSeq==0)clockSeq=1;
 CuteLink::send(uart,clockSeq,"CLOCK",label);
 lastDisplayMinute=minute;lastDisplayAt=millis();
}

static uint32_t nextAttempt=0,lastReport=0;
static uint8_t phase=0; // 1 gateway, 2 public
static char gatewayHost[20]={0}; // lwIP SNTP keeps hostname pointers: never use local String.c_str().
static constexpr uint32_t CHECK_MS=60000;
inline bool valid(){
 time_t now=time(nullptr);
 return now>=1735689600LL && now<4102444800LL;
}
inline void stop(){
 if(running)esp_sntp_stop();
 running=false;phase=0;nextAttempt=0;
}
inline void configureServers(bool useGateway){
 esp_sntp_stop();
 esp_sntp_setoperatingmode(SNTP_OPMODE_POLL);
 if(useGateway){
  esp_sntp_setservername(0,gatewayHost);
  esp_sntp_setservername(1,"time.google.com");
  esp_sntp_setservername(2,"pool.ntp.org");
 }else{
  esp_sntp_setservername(0,"time.google.com");
  esp_sntp_setservername(1,"pool.ntp.org");
  esp_sntp_setservername(2,"time.cloudflare.com");
 }
 esp_sntp_set_sync_mode(SNTP_SYNC_MODE_IMMED);
 esp_sntp_set_sync_interval(3600000UL);
 esp_sntp_init();
}
inline void begin(){
 IPAddress gateway=WiFi.gatewayIP();
 bool hasGateway=gateway!=IPAddress(0,0,0,0) &&
                 gateway!=IPAddress(255,255,255,255) && gateway[0]<224;
 if(hasGateway){
  String address=gateway.toString();
  strlcpy(gatewayHost,address.c_str(),sizeof(gatewayHost));
 }else gatewayHost[0]=0;
 configureServers(hasGateway);
 running=true;phase=hasGateway?1:2;
 nextAttempt=millis()+(hasGateway?10000UL:120000UL);
 Serial.printf("[S3 TIME] SNTP started: %s, backups public NTP; gateway=%s, DNS=%s\n",
  hasGateway?"gateway first":"public NTP",hasGateway?gatewayHost:"none",WiFi.dnsIP().toString().c_str());
}
inline void tick(bool online){
 if(!online){if(running)stop();return;}
 if(!running){begin();return;}
 uint32_t now=millis();
 if(valid()){
  if((uint32_t)(now-lastReport)>=CHECK_MS){
   lastReport=now;
   Serial.printf("[S3 TIME] UTC valid: %lld\n",(long long)time(nullptr));
  }
  return;
 }
 if((int32_t)(now-nextAttempt)<0)return;
 if(phase==1){
  configureServers(false);phase=2;nextAttempt=now+120000UL;
  Serial.println("[S3 TIME] Gateway has not synchronized; switched to public NTP");
 }else{
  // Public NTP may be blocked by a firewall; avoid continually resetting SNTP.
  // Let the built-in SNTP retry schedule operate and log actionable network info.
  nextAttempt=now+120000UL;
  IPAddress resolved;
  bool dnsOK=WiFi.hostByName("time.google.com",resolved);
  Serial.printf("[S3 TIME] Still unsynchronized; public NTP active, DNS=%s (%s), check UDP/123\n",
   dnsOK?"OK":"FAIL",dnsOK?resolved.toString().c_str():"unresolved");
 }
}
} // namespace BrainClock
