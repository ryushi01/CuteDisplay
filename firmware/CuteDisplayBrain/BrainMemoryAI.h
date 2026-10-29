#pragma once
// Optional, low-priority memory *analysis*. Persistent writes remain on S3 SD worker.
// This file MUST NOT run from realtime audio/WebSocket callbacks.
#include <esp_http_client.h>
#include <cJSON.h>
namespace BrainMemoryAI {
static TaskHandle_t worker=nullptr;
static volatile bool running=false, abortRequested=false;
static volatile uint32_t lastInteractiveAt=0;
static volatile bool interactive=true;
static constexpr uint32_t IDLE_MS=20000UL;
static constexpr uint32_t RETRY_GAP_MS=10000UL;
static uint32_t lastAttempt=0;
static String pending;
// No more than one inference at once. Model is shared with live conversation.
inline void tick(bool busy){
 uint32_t now=millis();
 if(busy){interactive=true;lastInteractiveAt=now;abortRequested=true;return;}
 if(interactive){interactive=false;lastInteractiveAt=now;}
 if(running || WiFi.status()!=WL_CONNECTED ||
    (uint32_t)(now-lastInteractiveAt)<IDLE_MS ||
    (uint32_t)(now-lastAttempt)<RETRY_GAP_MS)return;
 if(pending.isEmpty() && !KittyMemory::takeConsolidationCandidate(pending))return;
 lastAttempt=now;abortRequested=false;
 running=true;
 if(xTaskCreatePinnedToCore([](void*){
   // Take only one bounded user utterance from the SD worker's RAM queue.
   String utterance=pending;pending="";
   auto finish=[](){running=false;worker=nullptr;vTaskDelete(nullptr);};
   if(abortRequested || interactive || utterance.length()<12){finish();return;}
   String l=utterance;l.toLowerCase();
   // Conservative candidate filter: avoid Ollama requests for jokes,
   // questions, greetings and the majority of ordinary conversation.
   if(l.indexOf('?')>=0 || l.indexOf("？")>=0 ||
      (l.indexOf("i ")<0 && l.indexOf("my ")<0 && l.indexOf("im ")<0 &&
       l.indexOf("je ")<0 && l.indexOf("j'")<0 &&
       l.indexOf("私は")<0 && l.indexOf("私の")<0 && l.indexOf("今日は")<0)){
     finish();return;
   }
   Preferences prefs;String url,model,key;
   if(prefs.begin("brain-ai",true)){
    url=prefs.getString("url","");model=prefs.getString("model","");
    key=prefs.getString("key","");prefs.end();
   }
   if(!url.startsWith("https://") || url.indexOf('@')>=0 ||
      model.isEmpty() || key.isEmpty() || abortRequested){finish();return;}
   if(url.endsWith("/"))url.remove(url.length()-1);
   url+="/api/chat/completions";
   cJSON *root=cJSON_CreateObject();
   cJSON_AddStringToObject(root,"model",model.c_str());
   cJSON_AddBoolToObject(root,"stream",false);
   cJSON_AddNumberToObject(root,"max_tokens",160);
   cJSON *messages=cJSON_AddArrayToObject(root,"messages");
   cJSON *system=cJSON_CreateObject();
   cJSON_AddStringToObject(system,"role","system");
   cJSON_AddStringToObject(system,"content",
    "Extract ONLY clearly explicit durable user preferences from the utterance. "
    "Return compact JSON only: {\"facts\":[{\"kind\":\"likes\",\"subject\":\"chocolate\"}]}. "
    "Allowed kind: likes, dislikes. Max 3 items. Subject must be concrete and "
    "independently meaningful (no it/this/that/one, questions, guesses, vague "
    "references or inferred emotions). A later dislike supersedes a like for "
    "the SAME subject. If no explicit stable preferences, return {\"facts\":[]}. "
    "Never extract preferences about the assistant, hypothetical examples or jokes.");
   cJSON_AddItemToArray(messages,system);
   cJSON *user=cJSON_CreateObject();
   cJSON_AddStringToObject(user,"role","user");
   cJSON_AddStringToObject(user,"content",utterance.c_str());
   cJSON_AddItemToArray(messages,user);
   char *payload=cJSON_PrintUnformatted(root);cJSON_Delete(root);
   if(!payload){finish();return;}
   String reply;reply.reserve(512);
   struct Response {String *text;};
   Response response={&reply};
   esp_http_client_config_t cfg={};
   cfg.url=url.c_str();
   cfg.crt_bundle_attach=esp_crt_bundle_attach; // Same verified CA bundle as BrainAI.
   cfg.timeout_ms=1600; // Short network read timeout; never on audio task.
   cfg.user_data=&response;
   cfg.event_handler=[](esp_http_client_event_t *e)->esp_err_t {
    if(abortRequested || interactive)return ESP_FAIL;
    if(e->event_id==HTTP_EVENT_ON_DATA && e->data_len>0){
     auto *res=(Response*)e->user_data;
     if(res && res->text && res->text->length()+e->data_len<=2048)
      res->text->concat((const char*)e->data,(unsigned int)e->data_len);
    }
    return ESP_OK;
   };
   esp_http_client_handle_t http=esp_http_client_init(&cfg);
   if(http && !abortRequested){
    String auth="Bearer "+key;
    esp_http_client_set_method(http,HTTP_METHOD_POST);
    esp_http_client_set_header(http,"Authorization",auth.c_str());
    esp_http_client_set_header(http,"Content-Type","application/json");
    esp_http_client_set_post_field(http,payload,strlen(payload));
    esp_err_t rc=esp_http_client_perform(http);
    int status=esp_http_client_get_status_code(http);
    if(rc==ESP_OK && status==200 && !abortRequested && !interactive){
     cJSON *outer=cJSON_Parse(reply.c_str());
     cJSON *choices=cJSON_GetObjectItem(outer,"choices");
     cJSON *first=cJSON_GetArrayItem(choices,0);
     cJSON *message=cJSON_GetObjectItem(first,"message");
     cJSON *content=cJSON_GetObjectItem(message,"content");
     if(cJSON_IsString(content)){
      const char *raw=content->valuestring;
      // Some chat models wrap JSON in a markdown fence; parse first object.
      String body(raw);int start=body.indexOf('{'),end=body.lastIndexOf('}');
      if(start>=0 && end>start){
       cJSON *parsed=cJSON_Parse(body.substring(start,end+1).c_str());
       cJSON *facts=cJSON_GetObjectItem(parsed,"facts");
       if(cJSON_IsArray(facts) && cJSON_GetArraySize(facts)<=3){
        int accepted=0;
        cJSON *item=nullptr;
        cJSON_ArrayForEach(item,facts){
         cJSON *kind=cJSON_GetObjectItem(item,"kind");
         cJSON *subject=cJSON_GetObjectItem(item,"subject");
         if(!cJSON_IsString(kind)||!cJSON_IsString(subject))continue;
         String k(kind->valuestring),v(subject->valuestring);
         if((k=="likes"||k=="dislikes") &&
            KittyMemory::meaningfulPreferenceSubject(v) &&
            !abortRequested && !interactive &&
            KittyMemory::proposeConsolidatedFact(k,v))accepted++;
        }
        if(accepted)Serial.printf("[MEMORY AI] proposed=%d (idle)\\n",accepted);
       }
       if(parsed)cJSON_Delete(parsed);
      }
     }
     if(outer)cJSON_Delete(outer);
    }else if(!abortRequested)Serial.printf("[MEMORY AI] skipped HTTP=%d err=%d\\n",status,(int)rc);
   }
   if(http)esp_http_client_cleanup(http);
   free(payload);
   finish();
  },"kitty_memory_ai",12288,nullptr,1,&worker,0)!=pdPASS){
   running=false;worker=nullptr;
 }
}
} // namespace BrainMemoryAI
