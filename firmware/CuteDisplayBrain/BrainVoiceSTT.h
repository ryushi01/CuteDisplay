#pragma once
// Phase 1 push-to-talk: record 3 seconds of mono PCM and use Open WebUI's
// configured /api/v1/audio/transcriptions provider. No audio goes to C5.
#include <Arduino.h>
#include <WiFi.h>
#include <Preferences.h>
#include <driver/i2s_std.h>
#include <esp_heap_caps.h>
#include <esp_http_client.h>
#include <esp_crt_bundle.h>
#include <cJSON.h>
#include "BrainPinPlan.h"

namespace BrainVoiceSTT {
static volatile bool running=false;
static QueueHandle_t results=nullptr;
struct Result { bool ok; char text[1025]; char error[40]; };
static constexpr uint32_t RATE=16000;
static constexpr uint32_t SECONDS=3;
static constexpr size_t SAMPLES=RATE*SECONDS;
static uint8_t *responseBuffer=nullptr;
static size_t responseLength=0;
static esp_err_t onHTTP(esp_http_client_event_t *e){
 if(e->event_id==HTTP_EVENT_ON_DATA && e->data && e->data_len>0 && responseBuffer){
  if(responseLength+(size_t)e->data_len>4095)return ESP_FAIL;
  memcpy(responseBuffer+responseLength,e->data,e->data_len);
  responseLength+=(size_t)e->data_len;
  responseBuffer[responseLength]=0;
 }
 return ESP_OK;
}
static void u16(uint8_t *p,uint16_t v){p[0]=v&255;p[1]=(v>>8)&255;}
static void u32(uint8_t *p,uint32_t v){for(int i=0;i<4;i++)p[i]=(v>>(i*8))&255;}
static void task(void*){
 Result result={};
 strcpy(result.error,"STT_FAILED");
 i2s_chan_handle_t rx=nullptr;
 uint8_t *wav=nullptr,*body=nullptr;
 size_t bodySize=0;
 const size_t wavBytes=44+SAMPLES*2;
 do {
  if(WiFi.status()!=WL_CONNECTED){strcpy(result.error,"WIFI_OFFLINE");break;}
  Preferences p;
  String url,key;
  if(p.begin("brain-ai",true)){url=p.getString("url","");key=p.getString("key","");p.end();}
  if(!url.startsWith("https://")||url.indexOf('@')>=0||url.indexOf('#')>=0||key.isEmpty()){
   strcpy(result.error,"AI_CONFIG");break;
  }
  wav=(uint8_t*)heap_caps_malloc(wavBytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
  if(!wav){strcpy(result.error,"NO_PSRAM");break;}
  memcpy(wav,"RIFF",4);u32(wav+4,(uint32_t)wavBytes-8);
  memcpy(wav+8,"WAVEfmt ",8);u32(wav+16,16);u16(wav+20,1);
  u16(wav+22,1);u32(wav+24,RATE);u32(wav+28,RATE*2);
  u16(wav+32,2);u16(wav+34,16);memcpy(wav+36,"data",4);
  u32(wav+40,SAMPLES*2);
  i2s_chan_config_t ch=I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0,I2S_ROLE_MASTER);
  if(i2s_new_channel(&ch,nullptr,&rx)!=ESP_OK){strcpy(result.error,"MIC_CHANNEL");break;}
  i2s_std_config_t cfg={
   .clk_cfg=I2S_STD_CLK_DEFAULT_CONFIG(RATE),
   .slot_cfg=I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT,I2S_SLOT_MODE_STEREO),
   .gpio_cfg={.mclk=I2S_GPIO_UNUSED,
    .bclk=(gpio_num_t)BrainPinPlan::I2S_BCLK,
    .ws=(gpio_num_t)BrainPinPlan::I2S_WS,
    .dout=I2S_GPIO_UNUSED,
    .din=(gpio_num_t)BrainPinPlan::I2S_DIN,
    .invert_flags={.mclk_inv=false,.bclk_inv=false,.ws_inv=false}}
  };
  if(i2s_channel_init_std_mode(rx,&cfg)!=ESP_OK || i2s_channel_enable(rx)!=ESP_OK){
   strcpy(result.error,"MIC_INIT");break;
  }
  Serial.println("[VOICE] Recording 3 seconds at 16 kHz");
  uint64_t energy=0;
  bool captureOK=true;
  for(size_t off=0;off<SAMPLES;off+=128){
   int32_t stereo[256];size_t bytes=0;
   if(i2s_channel_read(rx,stereo,sizeof(stereo),&bytes,1500)!=ESP_OK||bytes!=sizeof(stereo)){
    captureOK=false;break;
   }
   for(size_t j=0;j<128;j++){
    int32_t sample=stereo[j*2]>>16;
    sample=constrain(sample,-32768,32767);
    int16_t v=(int16_t)sample;
    u16(wav+44+(off+j)*2,(uint16_t)v);
    energy+=(uint32_t)abs((int)v);
   }
  }
  i2s_channel_disable(rx);i2s_del_channel(rx);rx=nullptr;
  if(!captureOK){strcpy(result.error,"MIC_TIMEOUT");break;}
  if(energy/SAMPLES<4){strcpy(result.error,"MIC_SILENT");break;}
  const char *boundary="CuteDisplayAudioBoundary";
  String prefix=String("--")+boundary+"\r\nContent-Disposition: form-data; name=\"file\"; filename=\"kitty.wav\"\r\nContent-Type: audio/wav\r\n\r\n";
  String suffix=String("\r\n--")+boundary+"--\r\n";
  bodySize=prefix.length()+wavBytes+suffix.length();
  body=(uint8_t*)heap_caps_malloc(bodySize,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
  responseBuffer=(uint8_t*)heap_caps_malloc(4096,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
  responseLength=0;
  if(!body||!responseBuffer){strcpy(result.error,"NO_PSRAM");break;}
  memcpy(body,prefix.c_str(),prefix.length());
  memcpy(body+prefix.length(),wav,wavBytes);
  memcpy(body+prefix.length()+wavBytes,suffix.c_str(),suffix.length());
  if(url.endsWith("/"))url.remove(url.length()-1);
  url+="/api/v1/audio/transcriptions";
  esp_http_client_config_t hc={};
  hc.url=url.c_str();hc.crt_bundle_attach=esp_crt_bundle_attach;
  hc.event_handler=onHTTP;hc.timeout_ms=90000;hc.buffer_size=2048;
  esp_http_client_handle_t client=esp_http_client_init(&hc);
  if(!client){strcpy(result.error,"HTTP_INIT");break;}
  String auth="Bearer "+key;
  String type=String("multipart/form-data; boundary=")+boundary;
  esp_http_client_set_method(client,HTTP_METHOD_POST);
  esp_http_client_set_header(client,"Authorization",auth.c_str());
  esp_http_client_set_header(client,"Content-Type",type.c_str());
  esp_http_client_set_post_field(client,(const char*)body,bodySize);
  esp_err_t rc=esp_http_client_perform(client);
  int code=esp_http_client_get_status_code(client);
  esp_http_client_cleanup(client);
  if(rc!=ESP_OK||code!=200){snprintf(result.error,sizeof(result.error),"STT_HTTP_%d",code);break;}
  cJSON *json=cJSON_Parse((const char*)responseBuffer);
  if(!json){strcpy(result.error,"BAD_STT_JSON");break;}
  cJSON *field=cJSON_GetObjectItem(json,"text");
  if(cJSON_IsString(field)&&field->valuestring && strlen(field->valuestring)<sizeof(result.text)){
   strlcpy(result.text,field->valuestring,sizeof(result.text));
   result.ok=result.text[0]!=0;
  }else strcpy(result.error,"NO_TRANSCRIPT");
  cJSON_Delete(json);
 }while(false);
 if(rx){i2s_channel_disable(rx);i2s_del_channel(rx);}
 if(wav)heap_caps_free(wav);
 if(body)heap_caps_free(body);
 if(responseBuffer)heap_caps_free(responseBuffer);
 responseBuffer=nullptr;responseLength=0;
 if(results)xQueueSend(results,&result,pdMS_TO_TICKS(100));
 Serial.printf("[VOICE] %s\n",result.ok?"TRANSCRIBED":result.error);
 running=false;
 vTaskDelete(nullptr);
}
inline bool start(){
 if(running||!results)return false;
 running=true;
 if(xTaskCreatePinnedToCore(task,"voice_stt",16384,nullptr,1,nullptr,0)!=pdPASS){
  running=false;return false;
 }
 return true;
}
inline void init(){if(!results)results=xQueueCreate(2,sizeof(Result));}
inline bool take(Result &r){return results&&xQueueReceive(results,&r,0)==pdTRUE;}
}
