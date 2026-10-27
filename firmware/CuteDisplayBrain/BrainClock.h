#pragma once
// UTC SNTP service for S3 Brain. Does not block BLE, UART, audio or AI.
#include <Arduino.h>
#include <WiFi.h>
#include <time.h>
#include "esp_sntp.h"
namespace BrainClock {
static bool running=false;
static uint32_t nextAttempt=0,lastReport=0;
static constexpr uint32_t RETRY_MS=30000;
static constexpr uint32_t CHECK_MS=60000;
inline bool valid(){
 time_t now=time(nullptr);
 return now>=1735689600LL && now<4102444800LL;
}
inline void stop(){
 if(running) {esp_sntp_stop();running=false;}
 nextAttempt=0;
}
inline void begin(){
 // Gateway first; if no reply, SNTP rotates to public servers on its own.
 IPAddress gateway=WiFi.gatewayIP();
 String gw=gateway.toString();
 esp_sntp_stop();
 esp_sntp_setoperatingmode(SNTP_OPMODE_POLL);
 esp_sntp_setservername(0,(gateway!=IPAddress(0,0,0,0)?gw.c_str():"time.google.com"));
 esp_sntp_setservername(1,"time.google.com");
 esp_sntp_setservername(2,"pool.ntp.org");
 esp_sntp_set_sync_mode(SNTP_SYNC_MODE_IMMED);
 esp_sntp_set_sync_interval(3600000UL); // hourly automatic synchronization
 esp_sntp_init();
 running=true;
 nextAttempt=millis()+RETRY_MS;
 Serial.printf("[S3 TIME] SNTP enabled: primary=%s, backup=time.google.com,pool.ntp.org (UTC)\n",
   gateway!=IPAddress(0,0,0,0)?gw.c_str():"time.google.com");
}
inline void tick(bool online){
 if(!online){if(running)stop();return;}
 if(!running){begin();return;}
 uint32_t now=millis();
 if(valid()){
  if(now-lastReport>=CHECK_MS){
   lastReport=now;
   Serial.printf("[S3 TIME] UTC valid: %lld\n",(long long)time(nullptr));
  }
 }else if((int32_t)(now-nextAttempt)>=0){
  // Restart with public server first if the gateway doesn't serve UDP/123.
  esp_sntp_stop();
  esp_sntp_setoperatingmode(SNTP_OPMODE_POLL);
  esp_sntp_setservername(0,"time.google.com");
  esp_sntp_setservername(1,"pool.ntp.org");
  esp_sntp_setservername(2,"time.cloudflare.com");
  esp_sntp_set_sync_interval(3600000UL);
  esp_sntp_init();
  nextAttempt=now+RETRY_MS;
  Serial.println("[S3 TIME] No sync from gateway; public NTP active, retrying");
 }
}
} // namespace BrainClock
