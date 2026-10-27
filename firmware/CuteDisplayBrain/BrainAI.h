#pragma once
// Experimental S3-owned Open WebUI client. NEVER share bearer token with C5.
#include <Arduino.h>
#include <WiFi.h>
#include <Preferences.h>
#include <esp_http_client.h>
#include <cJSON.h>
#include <time.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include "CuteLink.h"

namespace BrainAI {
struct Packet { char kind[12]; char text[81]; };
static QueueHandle_t out=nullptr;
static TaskHandle_t worker=nullptr;
static volatile bool busy=false;
static uint16_t uartSeq=52000,pending=0;
static Packet outstanding={};
static uint32_t pendingAt=0;
static uint8_t retries=0;
static String fragment,staged;
static bool failed=false;
static bool doneSeen=false;
static uint32_t requestStarted=0,firstTokenAt=0,lastTextFlush=0;
static uint32_t emittedBytes=0,ackedBytes=0,packetCount=0;
static String provisioningField,provisioningBuffer;
static size_t provisioningExpected=0;
static uint32_t provisioningAt=0;

inline void init(){if(!out)out=xQueueCreate(16,sizeof(Packet));}
inline bool sendPacket(const char *kind,const String &payload) {
 if(!out || payload.length()>80)return false;
 Packet row={};
 strlcpy(row.kind,kind,sizeof(row.kind));
 payload.toCharArray(row.text,sizeof(row.text));
 return xQueueSend(out,&row,pdMS_TO_TICKS(10000))==pdTRUE;
}
inline void releaseText(bool force=false){
 while(staged.length() >= 64 || (force && !staged.isEmpty())) {
  size_t len=min((size_t)72,staged.length());
  while(len>0 && len<staged.length() && ((uint8_t)staged[len]&0xC0)==0x80)len--;
  if(len==0)break;
  String part=staged.substring(0,len);
  if(!sendPacket("AI_DATA",part)){failed=true;return;}
  emittedBytes+=len;
  lastTextFlush=millis();
  staged.remove(0,len);
 }
}
inline void processSSELine(String line){
 line.trim();
 if(!line.startsWith("data:"))return;
 String body=line.substring(5);body.trim();
 if(body=="[DONE]"){doneSeen=true;return;}
 if(body.isEmpty()||body.length()>8192)return;
 cJSON *root=cJSON_Parse(body.c_str());
 if(!root)return;
 cJSON *choices=cJSON_GetObjectItem(root,"choices");
 cJSON *first=cJSON_IsArray(choices)?cJSON_GetArrayItem(choices,0):nullptr;
 cJSON *delta=cJSON_GetObjectItem(first,"delta");
 cJSON *txt=cJSON_GetObjectItem(delta,"content");
 if(!cJSON_IsString(txt)){
  cJSON *msg=cJSON_GetObjectItem(first,"message");
  txt=cJSON_GetObjectItem(msg,"content");
 }
 if(cJSON_IsString(txt) && txt->valuestring){
  // Single stream delta; never split a multi-byte Unicode scalar on the UART.
  String chunk(txt->valuestring);
  if(!firstTokenAt && !chunk.isEmpty()){
   firstTokenAt=millis();
   Serial.printf("[AI PERF] First token in %lums\n",(unsigned long)(firstTokenAt-requestStarted));
  }
  if(staged.length()+chunk.length()<=512)staged+=chunk;
  else failed=true;
  releaseText(false);
  // First phrase appears immediately rather than waiting for 64 bytes.
  if(emittedBytes==0 && staged.length()>=12)releaseText(true);
 }
 cJSON_Delete(root);
}
static String sseBuffer;
static esp_err_t event(esp_http_client_event_t *e){
 if(e->event_id==HTTP_EVENT_ON_DATA && e->data && e->data_len>0){
  const char *bytes=(const char*)e->data;
  for(int i=0;i<e->data_len && !failed;i++){
   char ch=bytes[i];
   if(ch=='\n'){
    processSSELine(sseBuffer);sseBuffer="";
   }else if(ch!='\r'){
    if(sseBuffer.length()<8192)sseBuffer+=ch;else failed=true;
   }
  }
  // Flush partial phrases after a pause in token generation.
  if(staged.length()>=12 && millis()-lastTextFlush>280)releaseText(true);
 }
 return ESP_OK;
}
inline void run(void*){
 Preferences prefs;String url,model,key,ca,prompt;
 if(prefs.begin("brain-ai",true)){
  url=prefs.getString("url","");
  model=prefs.getString("model","");
  key=prefs.getString("key","");
  ca=prefs.getString("ca","");
  prompt=prefs.getString("prompt","");
  prefs.end();
 }
 if(WiFi.status()!=WL_CONNECTED || !url.startsWith("https://") ||
    url.indexOf('@')>=0 || url.indexOf('#')>=0 ||
    model.isEmpty() || key.isEmpty() || ca.indexOf("BEGIN CERTIFICATE")<0 ||
    prompt.isEmpty()){
  Serial.println("[AI] HTTPS, CA, WiFi or saved configuration missing");
  sendPacket("AI_END","");
  busy=false;worker=nullptr;vTaskDelete(nullptr);return;
 }
 // TLS certificate date verification requires system clock.
 configTime(0,0,"pool.ntp.org","time.google.com");
 for(int i=0;i<50 && time(nullptr)<1700000000;i++)vTaskDelay(pdMS_TO_TICKS(200));
 if(time(nullptr)<1700000000){
  Serial.println("[AI] Clock not synchronized; refusing HTTPS");
  sendPacket("AI_END","");
  busy=false;worker=nullptr;vTaskDelete(nullptr);return;
 }
 init();
 sendPacket("AI_BEGIN","");
 failed=false;doneSeen=false;sseBuffer="";staged="";
 requestStarted=millis();firstTokenAt=0;lastTextFlush=millis();
 emittedBytes=0;ackedBytes=0;packetCount=0;
 String address=url;
 if(address.endsWith("/"))address.remove(address.length()-1);
 address+="/api/chat/completions";
 cJSON *root=cJSON_CreateObject();
 cJSON_AddStringToObject(root,"model",model.c_str());
 cJSON_AddBoolToObject(root,"stream",true);
 cJSON *msgs=cJSON_AddArrayToObject(root,"messages");
 cJSON *m=cJSON_CreateObject();
 cJSON_AddStringToObject(m,"role","user");
 cJSON_AddStringToObject(m,"content",prompt.c_str());
 cJSON_AddItemToArray(msgs,m);
 char *json=cJSON_PrintUnformatted(root);
 cJSON_Delete(root);
 if(json){
  esp_http_client_config_t cfg={};
  cfg.url=address.c_str();
  cfg.cert_pem=ca.c_str();
  cfg.event_handler=event;
  cfg.timeout_ms=60000;
  cfg.buffer_size=4096;
  esp_http_client_handle_t http=esp_http_client_init(&cfg);
  if(http){
   String auth="Bearer "+key;
   esp_http_client_set_method(http,HTTP_METHOD_POST);
   esp_http_client_set_header(http,"Authorization",auth.c_str());
   esp_http_client_set_header(http,"Content-Type","application/json");
   esp_http_client_set_header(http,"Accept","text/event-stream");
   esp_http_client_set_post_field(http,json,strlen(json));
   esp_err_t rc=esp_http_client_perform(http);
   int code=esp_http_client_get_status_code(http);
   Serial.printf("[AI] Request finished: HTTP=%d transport=%d\n",code,(int)rc);
   if(rc!=ESP_OK || code!=200 || !doneSeen)failed=true;
   esp_http_client_cleanup(http);
  }else failed=true;
  free(json);
 }else failed=true;
 releaseText(true);
 sendPacket("AI_END","");
 Serial.printf("[AI PERF] Generated UART bytes=%lu acked=%lu packets=%lu total=%lums\n",
  (unsigned long)emittedBytes,(unsigned long)ackedBytes,(unsigned long)packetCount,
  (unsigned long)(millis()-requestStarted));
 Serial.println(failed?"[AI] Stream ended with an error":"[AI] Stream complete");
 busy=false;worker=nullptr;vTaskDelete(nullptr);
}
inline bool start(){
 init();
 if(busy || !out)return false;
 busy=true;failed=false;
 if(xTaskCreatePinnedToCore(run,"brain_ai",16384,nullptr,1,&worker,0)!=pdPASS){
  busy=false;worker=nullptr;return false;
 }
 return true;
}
inline bool provision(const String &cmd,String &reply){
 if(cmd.startsWith("AI:BEGIN:")){
  int cut=cmd.indexOf(':',9);
  if(cut<0){reply="ERR:AI_FORMAT";return true;}
  String field=cmd.substring(9,cut);
  size_t size=(size_t)cmd.substring(cut+1).toInt();
  size_t limit=field=="C"?4096:field=="P"?1024:field=="K"?256:field=="U"?256:field=="M"?128:0;
  if(busy || !limit || !size || size>limit){reply="ERR:AI_SIZE";return true;}
  provisioningField=field;provisioningExpected=size;provisioningBuffer="";
  provisioningAt=millis();reply="ACK:AI_BEGIN";return true;
 }
 if(cmd.startsWith("AI:DATA:")){
  if(provisioningField.isEmpty() || millis()-provisioningAt>30000){
   reply="ERR:AI_SESSION";return true;
  }
  String hex=cmd.substring(8);
  if(hex.length()>80||hex.length()%2){reply="ERR:AI_DATA";return true;}
  for(size_t i=0;i<hex.length();i+=2){
   char x=hex[i],y=hex[i+1];
   auto num=[](char c)->int{
    if(c>='0'&&c<='9')return c-'0';
    if(c>='a'&&c<='f')return c-'a'+10;
    if(c>='A'&&c<='F')return c-'A'+10;return -1;
   };
   int hi=num(x),lo=num(y);
   if(hi<0||lo<0 || provisioningBuffer.length()>=provisioningExpected){
    reply="ERR:AI_DATA";return true;
   }
   provisioningBuffer+=(char)((hi<<4)|lo);
  }
  provisioningAt=millis();reply="ACK:AI_DATA";return true;
 }
 if(cmd=="AI:END"){
  if(provisioningField.isEmpty() || provisioningBuffer.length()!=provisioningExpected){
   reply="ERR:AI_INCOMPLETE";return true;
  }
  // Note: credentials saved only after a complete encrypted BLE transaction.
  Preferences prefs;
  bool ok=prefs.begin("brain-ai",false);
  if(ok){
   String key=provisioningField=="U"?"url":provisioningField=="M"?"model":
              provisioningField=="K"?"key":provisioningField=="C"?"ca":"prompt";
   ok=prefs.putString(key.c_str(),provisioningBuffer)==provisioningBuffer.length();
   prefs.end();
  }
  provisioningBuffer="";provisioningField="";
  reply=ok?"ACK:AI_SAVED":"ERR:AI_NVS";return true;
 }
 if(cmd=="AI:GO"){reply=start()?"ACK:AI_STARTED":"ERR:AI_BUSY";return true;}
 return false;
}
inline void onAck(uint16_t seq,const String &type,const String &payload){
 if(!pending||seq!=pending)return;
 if(type=="ACK" && payload=="AI"){
  if(!strcmp(outstanding.kind,"AI_DATA"))ackedBytes+=strlen(outstanding.text);
  packetCount++;
  pending=0;retries=0;return;
 }
 // NACK or bad ACK: stop streaming until a fresh request.
 Serial.printf("[AI] UART rejected packet %u: %s %s\n",seq,type.c_str(),payload.c_str());
 pending=0;failed=true;
}
inline void tick(Stream &uart,bool allow){
 if(!out || !allow)return;
 if(pending){
  if(millis()-pendingAt<1800)return;
  if(++retries>4){Serial.println("[AI] UART ACK timeout");pending=0;failed=true;return;}
  CuteLink::send(uart,pending,outstanding.kind,outstanding.text);
  pendingAt=millis();return;
 }
 Packet next={};
 if(xQueueReceive(out,&next,0)!=pdTRUE)return;
 outstanding=next;
 if(++uartSeq==0)++uartSeq;
 pending=uartSeq;
 CuteLink::send(uart,pending,outstanding.kind,outstanding.text);
 pendingAt=millis();retries=0;
}
} // namespace BrainAI
