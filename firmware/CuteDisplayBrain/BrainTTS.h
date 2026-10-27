#pragma once
// Experimental Open WebUI TTS: request WAV, play PCM through MAX98357A.
// Text streaming is independent and continues even if speech is unavailable.
#include <Arduino.h>
#include <WiFi.h>
#include <Preferences.h>
#include <driver/i2s_std.h>
#include <esp_http_client.h>
#include <esp_crt_bundle.h>
#include <esp_heap_caps.h>
#include <cJSON.h>
#include "BrainPinPlan.h"
#define MINIMP3_IMPLEMENTATION
#define MINIMP3_ONLY_MP3
#include "minimp3.h"
namespace BrainTTS {
static volatile bool running=false;
static volatile bool cancelRequested=false;
static QueueHandle_t requests=nullptr;
struct Text { char value[769]; };
static uint8_t *audio=nullptr;
static size_t audioUsed=0;
static constexpr size_t AUDIO_CAP=1536*1024;
static esp_err_t onData(esp_http_client_event_t*event){
 if(cancelRequested)return ESP_FAIL;
 if(event->event_id==HTTP_EVENT_ON_DATA && event->data && event->data_len>0){
  if(!audio || audioUsed+(size_t)event->data_len>AUDIO_CAP)return ESP_FAIL;
  memcpy(audio+audioUsed,event->data,event->data_len);
  audioUsed+=(size_t)event->data_len;
 }
 return ESP_OK;
}
static uint16_t read16(const uint8_t *p){return (uint16_t)p[0]|((uint16_t)p[1]<<8);}
static uint32_t read32(const uint8_t *p){return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);}
static bool playback(){
 if(!audio || audioUsed<44 || memcmp(audio,"RIFF",4)!=0 || memcmp(audio+8,"WAVE",4)!=0)return false;
 uint16_t fmt=0,channels=0,bits=0;
 uint32_t rate=0;
 size_t offset=12,dataStart=0,dataSize=0;
 while(offset+8<=audioUsed){
  uint32_t chunk=read32(audio+offset+4);
  size_t start=offset+8;
  if(chunk>audioUsed-start)return false;
  if(memcmp(audio+offset,"fmt ",4)==0 && chunk>=16){
   fmt=read16(audio+start);channels=read16(audio+start+2);
   rate=read32(audio+start+4);bits=read16(audio+start+14);
  }else if(memcmp(audio+offset,"data",4)==0){dataStart=start;dataSize=chunk;break;}
  offset=start+chunk+(chunk&1u);
 }
 if(fmt!=1 || (channels!=1&&channels!=2) || bits!=16 ||
    (rate!=16000&&rate!=22050&&rate!=24000&&rate!=32000&&rate!=44100&&rate!=48000) ||
    !dataStart || !dataSize || dataSize%((size_t)channels*2))return false;
 i2s_chan_handle_t tx=nullptr;
 bool good=false;
 do{
  i2s_chan_config_t config=I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_1,I2S_ROLE_MASTER);
  if(i2s_new_channel(&config,&tx,nullptr)!=ESP_OK)break;
  i2s_std_config_t cfg={
   .clk_cfg=I2S_STD_CLK_DEFAULT_CONFIG(rate),
   .slot_cfg=I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT,I2S_SLOT_MODE_STEREO),
   .gpio_cfg={.mclk=I2S_GPIO_UNUSED,.bclk=(gpio_num_t)BrainPinPlan::I2S_BCLK,
    .ws=(gpio_num_t)BrainPinPlan::I2S_WS,.dout=(gpio_num_t)BrainPinPlan::I2S_DOUT,
    .din=I2S_GPIO_UNUSED,.invert_flags={.mclk_inv=false,.bclk_inv=false,.ws_inv=false}}
  };
  if(i2s_channel_init_std_mode(tx,&cfg)!=ESP_OK || i2s_channel_enable(tx)!=ESP_OK)break;
  const size_t frameBytes=(size_t)channels*2;
  size_t frames=dataSize/frameBytes;
  int16_t output[256];
  good=true;
  for(size_t pos=0;pos<frames && !cancelRequested;pos+=128){
   size_t count=min((size_t)128,frames-pos);
   for(size_t i=0;i<count;i++){
    const uint8_t *frame=audio+dataStart+(pos+i)*frameBytes;
    int16_t left=(int16_t)read16(frame),right=channels==2?(int16_t)read16(frame+2):left;
    // conservative first-test output volume, ~35%
    output[i*2]=(int16_t)((int32_t)left*35/100);
    output[i*2+1]=(int16_t)((int32_t)right*35/100);
   }
   size_t written=0;
   if(i2s_channel_write(tx,output,count*4,&written,2000)!=ESP_OK || written!=count*4){good=false;break;}
  }
 }while(false);
 if(tx){i2s_channel_disable(tx);i2s_del_channel(tx);}
 return good;
}
// Decode MP3 using the CC0 minimp3 decoder; no second libopus is linked.
static bool playbackMP3(){
 if(!audio||audioUsed<4)return false;
 mp3dec_t *decoder=(mp3dec_t*)heap_caps_malloc(sizeof(mp3dec_t),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 mp3d_sample_t *pcm=(mp3d_sample_t*)heap_caps_malloc(MINIMP3_MAX_SAMPLES_PER_FRAME*sizeof(mp3d_sample_t),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 if(!decoder||!pcm){
  if(decoder)heap_caps_free(decoder);
  if(pcm)heap_caps_free(pcm);
  return false;
 }
 mp3dec_init(decoder);
 i2s_chan_handle_t tx=nullptr;
 bool good=true,started=false;
 int rate=0,channels=0;
 size_t offset=0,decodedFrames=0;
 // Skip ID3v2 metadata (synchsafe 28-bit size).
 if(audioUsed>=10 && memcmp(audio,"ID3",3)==0){
  size_t tag=((size_t)(audio[6]&127)<<21)|((size_t)(audio[7]&127)<<14)|
             ((size_t)(audio[8]&127)<<7)|(audio[9]&127);
  offset=10+tag+((audio[5]&0x10)?10:0);
 }
 while(offset<audioUsed && !cancelRequested){
  mp3dec_frame_info_t info={};
  int samples=mp3dec_decode_frame(decoder,audio+offset,(int)min((size_t)INT_MAX,audioUsed-offset),pcm,&info);
  if(info.frame_bytes<=0){good=false;break;}
  offset+=info.frame_bytes;
  if(samples<=0)continue;
  if(info.channels<1 || info.channels>2 || info.hz<8000 || info.hz>48000){good=false;break;}
  if(!started){
   rate=info.hz;channels=info.channels;
   i2s_chan_config_t ch=I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_1,I2S_ROLE_MASTER);
   if(i2s_new_channel(&ch,&tx,nullptr)!=ESP_OK){good=false;break;}
   i2s_std_config_t cfg={
    .clk_cfg=I2S_STD_CLK_DEFAULT_CONFIG(rate),
    .slot_cfg=I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT,I2S_SLOT_MODE_STEREO),
    .gpio_cfg={.mclk=I2S_GPIO_UNUSED,.bclk=(gpio_num_t)BrainPinPlan::I2S_BCLK,
     .ws=(gpio_num_t)BrainPinPlan::I2S_WS,.dout=(gpio_num_t)BrainPinPlan::I2S_DOUT,
     .din=I2S_GPIO_UNUSED,.invert_flags={.mclk_inv=false,.bclk_inv=false,.ws_inv=false}}
   };
   if(i2s_channel_init_std_mode(tx,&cfg)!=ESP_OK || i2s_channel_enable(tx)!=ESP_OK){good=false;break;}
   started=true;
   Serial.printf("[TTS] MP3 playback started rate=%d channels=%d\n",rate,channels);
  }
  if(info.hz!=rate || info.channels!=channels){good=false;break;}
  int16_t out[256];
  for(int n=0;n<samples && !cancelRequested;n+=128){
   int count=min(128,samples-n);
   for(int j=0;j<count;j++){
    int16_t left=pcm[(n+j)*channels];
    int16_t right=channels==2?pcm[(n+j)*channels+1]:left;
    out[2*j]=(int16_t)((int32_t)left*35/100);
    out[2*j+1]=(int16_t)((int32_t)right*35/100);
   }
   size_t written=0;
   if(i2s_channel_write(tx,out,(size_t)count*4,&written,2000)!=ESP_OK||written!=(size_t)count*4){
    good=false;break;
   }
  }
  if(!good)break;
  decodedFrames++;
  vTaskDelay(1);
 }
 if(tx){i2s_channel_disable(tx);i2s_del_channel(tx);}
 heap_caps_free(decoder);heap_caps_free(pcm);
 return good && started && decodedFrames>0 && !cancelRequested;
}
static bool appearsMP3(){
 if(audioUsed<4)return false;
 if(memcmp(audio,"ID3",3)==0)return true;
 // MPEG audio sync bits, not a guarantee of a valid playable stream.
 return audio[0]==0xFF && (audio[1]&0xE0)==0xE0;
}
static void task(void *){
 Text text={};
 if(!requests || xQueueReceive(requests,&text,0)!=pdTRUE){running=false;vTaskDelete(nullptr);return;}
 const char *failure="UNKNOWN";
 do{
  if(cancelRequested){failure="CANCELLED";break;}
  if(WiFi.status()!=WL_CONNECTED){failure="WIFI_OFFLINE";break;}
  Preferences p;String url,key;
  if(p.begin("brain-ai",true)){url=p.getString("url","");key=p.getString("key","");p.end();}
  if(!url.startsWith("https://") || key.isEmpty()){failure="CONFIG";break;}
  if(url.endsWith("/"))url.remove(url.length()-1);
  url+="/api/v1/audio/speech";
  cJSON *request=cJSON_CreateObject();
  if(!request){failure="JSON_ALLOC";break;}
  cJSON_AddStringToObject(request,"input",text.value);
  cJSON_AddStringToObject(request,"response_format","wav");
  // Open WebUI uses configured TTS model and voice.
  char *body=cJSON_PrintUnformatted(request);
  cJSON_Delete(request);
  if(!body){failure="JSON_BODY";break;}
  audio=(uint8_t*)heap_caps_malloc(AUDIO_CAP,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
  audioUsed=0;
  if(!audio){free(body);failure="NO_PSRAM";break;}
  esp_http_client_config_t cfg={};
  cfg.url=url.c_str();cfg.crt_bundle_attach=esp_crt_bundle_attach;
  cfg.event_handler=onData;cfg.timeout_ms=60000;
  cfg.buffer_size=4096;cfg.buffer_size_tx=8192;
  esp_http_client_handle_t http=esp_http_client_init(&cfg);
  if(!http){free(body);failure="HTTP_INIT";break;}
  String authorization="Bearer "+key;
  esp_http_client_set_method(http,HTTP_METHOD_POST);
  esp_http_client_set_header(http,"Authorization",authorization.c_str());
  esp_http_client_set_header(http,"Content-Type","application/json");
  esp_http_client_set_post_field(http,body,strlen(body));
  esp_err_t err=esp_http_client_perform(http);
  int code=esp_http_client_get_status_code(http);
  esp_http_client_cleanup(http);free(body);
  Serial.printf("[TTS] HTTP=%d transport=%d bytes=%lu\n",code,(int)err,(unsigned long)audioUsed);
  if(cancelRequested){failure="CANCELLED";break;}
  if(err!=ESP_OK||code!=200){failure="HTTP_ERROR";break;}
  if(audioUsed>=12 && memcmp(audio,"RIFF",4)==0 && memcmp(audio+8,"WAVE",4)==0){
   Serial.println("[TTS] Format: WAV");
   if(!playback()){failure="INVALID_WAV_OR_PLAYBACK";break;}
  }else if(appearsMP3()){
   Serial.println("[TTS] Format: MP3");
   if(!playbackMP3()){failure="MP3_DECODER_OR_PLAYBACK";break;}
  }else{failure="UNSUPPORTED_AUDIO_FORMAT";break;}
  failure=nullptr;
 }while(false);
 if(failure)Serial.printf("[TTS] SKIPPED: %s (text remains visible)\n",failure);
 else Serial.println("[TTS] PLAYBACK_COMPLETE");
 if(audio){heap_caps_free(audio);audio=nullptr;}audioUsed=0;
 running=false;cancelRequested=false;vTaskDelete(nullptr);
}
inline void interrupt(){
 cancelRequested=true;
 if(requests)xQueueReset(requests);
}
inline bool active(){return running;}
inline void init(){if(!requests)requests=xQueueCreate(2,sizeof(Text));}
inline bool enqueue(const String &answer){
 if(!requests || answer.isEmpty())return false;
 Text row={};answer.substring(0,768).toCharArray(row.value,sizeof(row.value));
 return xQueueSend(requests,&row,0)==pdTRUE;
}
inline void tick(bool audioBusy){
 if(running||audioBusy||!requests||uxQueueMessagesWaiting(requests)==0)return;
 cancelRequested=false;running=true;
 if(xTaskCreatePinnedToCore(task,"brain_tts",16384,nullptr,1,nullptr,0)!=pdPASS)running=false;
}
}
