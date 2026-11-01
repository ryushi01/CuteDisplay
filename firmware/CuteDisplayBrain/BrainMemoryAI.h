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
// Circuit breaker: one failed idle HTTP request pauses inference until reboot.
// Original summary jobs stay in the SD journal, with no new Mac requests.
static volatile bool pausedAfterHttpFailure=false;
// Default OFF: background inference must be explicitly enabled from physical USB.
// Volatile by design: a reboot cannot accidentally resume Mac GPU work.
static volatile bool operatorEnabled=false;
static volatile uint32_t requestStartedAt=0;
static constexpr uint32_t TOTAL_BUDGET_MS=30000UL;
inline void setEnabled(bool enabled){operatorEnabled=enabled;if(!enabled)abortRequested=true;}
static String pending;
static bool pendingSummary=false;
static bool pendingSummaryOwnerVerified=false;
static uint32_t pendingSummaryConversation=0;
static uint32_t pendingSummaryJobEnd=0;
// No more than one inference at once. Model is shared with live conversation.
inline void tick(bool busy){
 uint32_t now=millis();
 if(busy){interactive=true;lastInteractiveAt=now;abortRequested=true;return;}
 if(interactive){interactive=false;lastInteractiveAt=now;}
 if(running && requestStartedAt && (uint32_t)(now-requestStartedAt)>TOTAL_BUDGET_MS){
  abortRequested=true;operatorEnabled=false;pausedAfterHttpFailure=true;
  // Do not free a worker blocked inside TLS; it will exit when the client returns.
 }
 if(running || !operatorEnabled || pausedAfterHttpFailure || WiFi.status()!=WL_CONNECTED ||
    (uint32_t)(now-lastInteractiveAt)<IDLE_MS ||
    (uint32_t)(now-lastAttempt)<RETRY_GAP_MS)return;
 if(pending.isEmpty()){
  // Summaries only run after conversational work is idle, never during calls.
  pendingSummary=KittyMemory::takeSummaryCandidate(pending,pendingSummaryOwnerVerified,pendingSummaryConversation,pendingSummaryJobEnd);
  if(!pendingSummary && !KittyMemory::takeConsolidationCandidate(pending))return;
 }
 lastAttempt=now;abortRequested=false;
 requestStartedAt=now;running=true;
 if(xTaskCreatePinnedToCore([](void*){
   // Take only one bounded user utterance from the SD worker's RAM queue.
   String utterance=pending;
   bool summarize=pendingSummary;
   bool summaryOwnerVerified=pendingSummaryOwnerVerified;
   uint32_t summaryConversation=pendingSummaryConversation;
   uint32_t summaryJobEnd=pendingSummaryJobEnd;
   // Keep the pending candidate until the model returns an accepted result.
   // Interrupted network/model work must be retried, not silently lost.
   auto finish=[](bool accepted=false){
    if(accepted){pending="";pendingSummary=false;
     pendingSummaryOwnerVerified=false;pendingSummaryConversation=0;pendingSummaryJobEnd=0;}
    // One USB opt-in authorizes at most one inference request, even on success.
    // Pending durable jobs are left for the next deliberate session.
    operatorEnabled=false;
    running=false;requestStartedAt=0;worker=nullptr;vTaskDelete(nullptr);
   };
   if(abortRequested || interactive || !operatorEnabled){finish();return;}
   if(utterance.length()<12){finish(true);return;}
   String l=utterance;l.toLowerCase();
   // Conservative candidate filter: avoid Ollama requests for jokes,
   // questions, greetings and the majority of ordinary conversation.
   if(!summarize && (l.indexOf('?')>=0 || l.indexOf("？")>=0 ||
      (l.indexOf("i ")<0 && l.indexOf("my ")<0 && l.indexOf("im ")<0 &&
       l.indexOf("je ")<0 && l.indexOf("j'")<0 &&
       l.indexOf("私は")<0 && l.indexOf("私の")<0 && l.indexOf("今日は")<0))){
     finish(true);return;
   }
   Preferences prefs;String url,model,key;
   if(prefs.begin("brain-ai",true)){
    url=prefs.getString("url","");model=prefs.getString("model","");
    key=prefs.getString("key","");prefs.end();
   }
   if(!operatorEnabled || !url.startsWith("https://") || url.indexOf('@')>=0 ||
      model.isEmpty() || key.isEmpty() || abortRequested){finish();return;}
   if(url.endsWith("/"))url.remove(url.length()-1);
   url+="/api/chat/completions";
   cJSON *root=cJSON_CreateObject();
   cJSON_AddStringToObject(root,"model",model.c_str());
   cJSON_AddBoolToObject(root,"stream",false);
   cJSON_AddNumberToObject(root,"max_tokens",96);
   cJSON *messages=cJSON_AddArrayToObject(root,"messages");
   cJSON *system=cJSON_CreateObject();
   cJSON_AddStringToObject(system,"role","system");
   cJSON_AddStringToObject(system,"content",summarize?
    "Summarize these user statements into ONE compact, factual memory of at most 180 characters. "
    "Preserve explicitly mentioned project decisions, changes, and future plans. "
    "Never invent details, never infer identities, and avoid speculative facts. "
    "Respond with JSON only: {\"summary\":\"...\"}. "
    "If nothing meaningful was discussed, return {\"summary\":\"\"}." :
    "Extract ONLY explicitly stated personal facts from the user utterance in English, French, or Japanese. "
    "Return compact JSON only: {\"facts\":[{\"kind\":\"likes\",\"subject\":\"chocolate\"}]}. "
    "Allowed kind: likes, dislikes, situation. For situation use subject as " 
    "a canonical topic identifier: work_availability, upcoming_plan, or hobby; " 
    "include detail as concise English or original-language description and " 
    "do not imply the situation is permanent. Max 3 items. Subject must be concrete and "
    "independently meaningful (no it/this/that/one, questions, guesses, vague "
    "references or inferred emotions). A later dislike supersedes a like for "
    "the SAME subject. If no explicit stable preferences, return {\"facts\":[]}. "
    "Never extract preferences about the assistant, hypothetical examples or jokes.");
   cJSON_AddItemToArray(messages,system);
   cJSON *user=cJSON_CreateObject();
   cJSON_AddStringToObject(user,"role","user");
   // Bound model input for predictable Mac-side compute. Original full turns
   // remain in the SD journal; this is only the ephemeral inference prompt.
   String inferenceInput=summarize?KittyMemory::clipUTF8(utterance,440):KittyMemory::clipUTF8(utterance,220);
   cJSON_AddStringToObject(user,"content",inferenceInput.c_str());
   cJSON_AddItemToArray(messages,user);
   char *payload=cJSON_PrintUnformatted(root);cJSON_Delete(root);
   if(!payload){finish();return;}
   String reply;reply.reserve(12288);
   struct Response {String *text; uint32_t firstDataAt=0; uint32_t bytes=0; int status=0; bool connected=false; bool truncated=false;};
   Response response={&reply};
   esp_http_client_config_t cfg={};
   cfg.url=url.c_str();
   cfg.crt_bundle_attach=esp_crt_bundle_attach; // Verified HTTPS to remote Open WebUI.
   cfg.timeout_ms=15000; // Idle-only inference, never on realtime/audio task.
   cfg.user_data=&response;
   cfg.event_handler=[](esp_http_client_event_t *e)->esp_err_t {
    if(abortRequested || interactive || !operatorEnabled ||
       (requestStartedAt && (uint32_t)(millis()-requestStartedAt)>TOTAL_BUDGET_MS))return ESP_FAIL;
    auto *res=(Response*)e->user_data;
    if(!res)return ESP_OK;
    if(e->event_id==HTTP_EVENT_ON_CONNECTED)res->connected=true;
    if(e->event_id==HTTP_EVENT_ON_DATA && e->data_len>0){
     if(!res->firstDataAt)res->firstDataAt=millis();
     res->bytes+=(uint32_t)e->data_len;
     if(res->text && res->text->length()+(size_t)e->data_len<=16384)
      res->text->concat((const char*)e->data,(unsigned int)e->data_len);
     else if(res->text)res->truncated=true;
    }
    return ESP_OK;
   };
   esp_http_client_handle_t http=esp_http_client_init(&cfg);
   bool accepted=false;
   if(http && !abortRequested){
    String auth="Bearer "+key;
    esp_http_client_set_method(http,HTTP_METHOD_POST);
    esp_http_client_set_header(http,"Authorization",auth.c_str());
    esp_http_client_set_header(http,"Content-Type","application/json");
    esp_http_client_set_post_field(http,payload,strlen(payload));
    uint32_t startedAt=millis();
    esp_err_t rc=esp_http_client_perform(http);
    uint32_t elapsed=(uint32_t)(millis()-startedAt);
    int status=esp_http_client_get_status_code(http);
    // Classify the COMPLETE HTTP reply without exposing content, tokens or memories.
    // A 200 status may still contain HTML (reverse proxy/login), SSE, or malformed JSON.
    size_t first=0;
    while(first<reply.length() && (reply[first]==' ' || reply[first]=='\\n' ||
          reply[first]=='\\r' || reply[first]=='\\t'))first++;
    int format=0; // 0 empty, 1 JSON-like, 2 HTML-like, 3 SSE-like, 4 other
    if(first<reply.length()){
     char ch=reply[first];
     format=(ch=='{' || ch=='[')?1:(ch=='<'?2:(reply.startsWith("data:",first)?3:4));
    }
    if(rc==ESP_OK && status==200 && !abortRequested && !interactive){
     cJSON *outer=(format==1 && !response.truncated)?cJSON_Parse(reply.c_str()):nullptr;
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
       if(summarize){
        cJSON *sentence=cJSON_GetObjectItem(parsed,"summary");
        if(cJSON_IsString(sentence) && sentence->valuestring &&
           !abortRequested && !interactive)
          accepted=KittyMemory::proposeSummary(String(sentence->valuestring),summaryOwnerVerified,summaryConversation,summaryJobEnd);
       }
       cJSON *facts=cJSON_GetObjectItem(parsed,"facts");
       if(!summarize && cJSON_IsArray(facts) && cJSON_GetArraySize(facts)<=3){
        int accepted=0;
        cJSON *item=nullptr;
        cJSON_ArrayForEach(item,facts){
         cJSON *kind=cJSON_GetObjectItem(item,"kind");
         cJSON *subject=cJSON_GetObjectItem(item,"subject");
         if(!cJSON_IsString(kind)||!cJSON_IsString(subject))continue;
         String k(kind->valuestring),v(subject->valuestring);
         if((k=="likes"||k=="dislikes"||k=="situation") &&
            (k=="situation" ? (v=="work_availability"||v=="upcoming_plan"||v=="hobby") : KittyMemory::meaningfulPreferenceSubject(v)) &&
            !abortRequested && !interactive &&
            KittyMemory::proposeConsolidatedFact(k,k=="situation" ? v+":"+String(cJSON_IsString(cJSON_GetObjectItem(item,"detail"))?cJSON_GetObjectItem(item,"detail")->valuestring:"") : v))accepted++;
        }
        if(accepted)Serial.printf("[MEMORY AI] proposed=%d (idle)\\n",accepted);
       }
       if(parsed)cJSON_Delete(parsed);
      }
     }
     // Report metadata only: never print response text or private memory.
     Serial.printf("[MEMORY AI] result HTTP=%d elapsed_ms=%lu rx_bytes=%lu truncated=%d format=%d json=%d choices=%d content=%d accepted=%d\\n",
       status,(unsigned long)elapsed,(unsigned long)response.bytes,response.truncated?1:0,format,
       outer?1:0,cJSON_IsArray(choices)?1:0,cJSON_IsString(content)?1:0,accepted?1:0);
     if(outer)cJSON_Delete(outer);
    }else if(abortRequested || interactive || !operatorEnabled){
     Serial.printf("[MEMORY AI] interrupted HTTP=%d err=%d elapsed_ms=%lu connected=%d rx_bytes=%lu\\n",
       status,(int)rc,(unsigned long)elapsed,response.connected?1:0,(unsigned long)response.bytes);
    }else if(!abortRequested && !interactive){
     pausedAfterHttpFailure=true;
     Serial.printf("[MEMORY AI] skipped HTTP=%d err=%d elapsed_ms=%lu connected=%d first_data=%d rx_bytes=%lu; idle AI paused until reboot\\n",status,(int)rc,(unsigned long)elapsed,response.connected?1:0,response.firstDataAt?1:0,(unsigned long)response.bytes);
    }
   }
   if(requestStartedAt && (uint32_t)(millis()-requestStartedAt)>TOTAL_BUDGET_MS){
    pausedAfterHttpFailure=true;operatorEnabled=false;
    Serial.println("[MEMORY AI] total budget exceeded; idle AI disabled until USB opt-in");
   }
   if(http)esp_http_client_cleanup(http);
   free(payload);
   finish(accepted || !summarize);
  },"kitty_memory_ai",12288,nullptr,1,&worker,0)!=pdPASS){
   // A failed task allocation must not silently reattempt or consume GPU later.
   operatorEnabled=false;running=false;requestStartedAt=0;worker=nullptr;
   Serial.println("[MEMORY AI] worker allocation failed; USB opt-in cleared");
 }
}
} // namespace BrainMemoryAI
