#pragma once
// Experimental 24kHz PCM16 full-duplex I2S device for native Open WebUI calls.
// One shared S3 I2S port: INMP441 left slot in, MAX98357A mono out.
// Half-duplex at acoustic level: microphone uploads muted during Kitty speech
// and 300ms afterwards to prevent immediate speaker-to-mic feedback.
// Owned exclusively by Call Mode; legacy STT, TTS and audio tests must be idle.
// Never calls the WebSocket from this task: Core 0 does I2S, Arduino loop
// (Core 1) owns the network and transfers fixed-size frames via queues.
#include <Arduino.h>
#include <driver/i2s_std.h>
#include <esp_heap_caps.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/task.h>
#include "BrainPinPlan.h"

namespace BrainRealtimeAudio {
static constexpr uint32_t RATE=24000;
static constexpr size_t SAMPLES=480; // 20ms at 24kHz
static constexpr uint32_t TAIL_MUTE_MS=300;
struct Frame { int16_t pcm[SAMPLES]; };
static QueueHandle_t micQueue=nullptr, speakerQueue=nullptr;
static volatile bool running=false, ready=false, stopping=false, fault=false;
static volatile bool remoteReply=false, playing=false;
static volatile uint32_t lastPlaybackMs=0;
static uint16_t micGain=100;
static uint8_t speakerVolume=35;
static volatile uint32_t droppedMic=0;
static TaskHandle_t owner=nullptr;

inline bool active(){return running;}
inline bool initialized(){return running && ready && !fault;}
inline bool failed(){return fault;}
inline bool hasSpeakerAudio(){
 return playing || (speakerQueue && uxQueueMessagesWaiting(speakerQueue)>0);
}
inline void setRemoteReply(bool active){remoteReply=active;}
inline void clearSpeaker(){
 if(speakerQueue)xQueueReset(speakerQueue);
 remoteReply=false;
}
inline bool takeMic(Frame &f){
 return micQueue && xQueueReceive(micQueue,&f,0)==pdTRUE;
}
inline bool queueSpeaker(const uint8_t *pcm,size_t bytes){
 if(!ready || !speakerQueue || !pcm || !bytes || (bytes&1u))return false;
 const size_t frames=(bytes/2+SAMPLES-1)/SAMPLES;
 if(frames>uxQueueSpacesAvailable(speakerQueue))return false;
 Frame f={};
 size_t sample=0, total=bytes/2;
 for(size_t chunk=0;chunk<frames;chunk++){
  memset(&f,0,sizeof(f));
  for(size_t i=0;i<SAMPLES && sample<total;i++,sample++){
   size_t off=sample*2;
   f.pcm[i]=(int16_t)((uint16_t)pcm[off]|((uint16_t)pcm[off+1]<<8));
  }
  if(xQueueSend(speakerQueue,&f,0)!=pdTRUE)return false;
 }
 return true;
}

static void audioTask(void *){
 i2s_chan_handle_t tx=nullptr,rx=nullptr;
 bool txOn=false,rxOn=false;
 do {
  i2s_chan_config_t channel=I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0,I2S_ROLE_MASTER);
  channel.dma_desc_num=8;
  channel.dma_frame_num=SAMPLES;
  if(i2s_new_channel(&channel,&tx,&rx)!=ESP_OK)break;
  i2s_std_config_t config={
   .clk_cfg=I2S_STD_CLK_DEFAULT_CONFIG(RATE),
   .slot_cfg=I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT,I2S_SLOT_MODE_STEREO),
   .gpio_cfg={.mclk=I2S_GPIO_UNUSED,
    .bclk=(gpio_num_t)BrainPinPlan::I2S_BCLK,
    .ws=(gpio_num_t)BrainPinPlan::I2S_WS,
    .dout=(gpio_num_t)BrainPinPlan::I2S_DOUT,
    .din=(gpio_num_t)BrainPinPlan::I2S_DIN,
    .invert_flags={.mclk_inv=false,.bclk_inv=false,.ws_inv=false}}
  };
  if(i2s_channel_init_std_mode(tx,&config)!=ESP_OK ||
     i2s_channel_init_std_mode(rx,&config)!=ESP_OK)break;
  if(i2s_channel_enable(tx)!=ESP_OK)break;
  txOn=true;
  if(i2s_channel_enable(rx)!=ESP_OK)break;
  rxOn=true;
  ready=true;
  Serial.printf("[CALL] I2S 24kHz duplex active: BCLK=%d WS=%d MIC=%d SPK=%d\n",
   BrainPinPlan::I2S_BCLK,BrainPinPlan::I2S_WS,
   BrainPinPlan::I2S_DIN,BrainPinPlan::I2S_DOUT);
  // Fixed-size buffers on the audio task stack; no per-frame allocation.
  int32_t capture[SAMPLES*2];
  int32_t output[SAMPLES*2];
  Frame mic={};
  Frame speaker={};
  while(!stopping){
   size_t read=0;
   if(i2s_channel_read(rx,capture,sizeof(capture),&read,35)!=ESP_OK ||
      read!=sizeof(capture))break;
   bool hasAudio=xQueueReceive(speakerQueue,&speaker,0)==pdTRUE;
   playing=hasAudio;
   if(hasAudio)lastPlaybackMs=millis();
   // Wait until provider has stopped responding AND acoustic tail is gone.
   bool mute=remoteReply || hasAudio ||
     (uint32_t)(millis()-lastPlaybackMs)<TAIL_MUTE_MS;
   for(size_t i=0;i<SAMPLES;i++){
    int32_t value=0;
    if(!mute){
     // INMP441 L/R wired to GND => left slot; 24-bit left-aligned input.
     int32_t raw=capture[i*2]>>16;
     value=(raw*(int32_t)micGain)/100;
     if(value>32767)value=32767;
     if(value< -32768)value=-32768;
    }
    mic.pcm[i]=(int16_t)value;
    int32_t out=hasAudio?(int32_t)speaker.pcm[i]*speakerVolume/100:0;
    // Bound first hardware tests to ~38% full scale even at volume=100.
    if(out>12500)out=12500;
    if(out< -12500)out=-12500;
    output[2*i]=(int32_t)((int64_t)out*65536LL);
    output[2*i+1]=(int32_t)((int64_t)out*65536LL);
   }
   if(xQueueSend(micQueue,&mic,0)!=pdTRUE){
    // Prefer freshest audio instead of accumulating latency on a slow Wi-Fi link.
    Frame old={};
    (void)xQueueReceive(micQueue,&old,0);
    (void)xQueueSend(micQueue,&mic,0);
    droppedMic++;
   }
   size_t written=0;
   if(i2s_channel_write(tx,output,sizeof(output),&written,35)!=ESP_OK ||
      written!=sizeof(output))break;
  }
 }while(false);
 if(!stopping)fault=true;
 ready=false;
 playing=false;
 if(rx){if(rxOn)i2s_channel_disable(rx);i2s_del_channel(rx);}
 if(tx){if(txOn)i2s_channel_disable(tx);i2s_del_channel(tx);}
 running=false;
 owner=nullptr;
 vTaskDelete(nullptr);
}

inline bool start(uint16_t gain,uint8_t volume){
 if(running || owner)return false;
 if(!micQueue)micQueue=xQueueCreate(16,sizeof(Frame)); // 320ms uplink
 if(!speakerQueue)speakerQueue=xQueueCreate(48,sizeof(Frame)); // 960ms downlink
 if(!micQueue||!speakerQueue)return false;
 xQueueReset(micQueue);xQueueReset(speakerQueue);
 micGain=constrain((int)gain,0,300);
 speakerVolume=constrain((int)volume,0,100);
 lastPlaybackMs=millis()-TAIL_MUTE_MS;
 droppedMic=0;fault=false;ready=false;stopping=false;
 playing=false;remoteReply=false;running=true;
 if(xTaskCreatePinnedToCore(audioTask,"call_i2s",16384,nullptr,3,&owner,0)!=pdPASS){
  running=false;owner=nullptr;fault=true;return false;
 }
 return true;
}
inline void stop(){
 stopping=true;
 // Audio task read/write timeouts are <=35ms. Never let a stale I2S owner
 // overlap with manual PTT or TTS immediately after a short button tap.
 uint32_t since=millis();
 while(running && (uint32_t)(millis()-since)<250) vTaskDelay(pdMS_TO_TICKS(2));
 remoteReply=false;ready=false;
 if(micQueue)xQueueReset(micQueue);
 if(speakerQueue)xQueueReset(speakerQueue);
 if(running)Serial.println("[CALL] I2S teardown still finishing; legacy audio stays blocked");
}
} // namespace BrainRealtimeAudio
