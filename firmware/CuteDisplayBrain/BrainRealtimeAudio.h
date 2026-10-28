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
#include <esp_err.h>
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
// Allocate the 2x 3.8KB DMA staging arrays and audio frames in PSRAM,
// avoiding a large internal task stack after Wi-Fi/BLE/TLS handshake.
struct Buffers {
 int32_t capture[SAMPLES*2];
 int32_t output[SAMPLES*2];
 Frame mic,speaker,discard;
};
static Buffers *work=nullptr;
static QueueHandle_t micQueue=nullptr, speakerQueue=nullptr;
// ESP-IDF's dynamically created FreeRTOS queues use internal memory.
// 16+48 audio frames = 60KB; this can exhaust SRAM after Wi-Fi/WSS TLS.
// Allocate only the queue payload storage in PSRAM, using static queues,
// while small queue control blocks stay in internal DRAM.
static StaticQueue_t micQueueControl, speakerQueueControl;
static uint8_t *micQueueStorage=nullptr, *speakerQueueStorage=nullptr;
static constexpr UBaseType_t MIC_FRAMES=16, SPEAKER_FRAMES=48;
static const char *lastError="NOT_STARTED";
inline const char *issue(){return lastError;}
inline void reportError(const char *stage,esp_err_t err=ESP_OK){
 lastError=stage;
 Serial.printf("[CALL AUDIO] %s: esp=%s(%ld) internal_free=%lu largest_internal=%lu psram_free=%lu\n",
  stage,esp_err_to_name(err),(long)err,
  (unsigned long)heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
  (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
  (unsigned long)heap_caps_get_free_size(MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
}
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
  // 8 x 480 stereo 32-bit frames would reserve ~30KB internal DMA per
  // direction (60KB duplex). After TLS that frequently exhausts DRAM.
  // 8 x 120 is ~7.5KB/direction and still gives 40ms DMA slack.
  channel.dma_desc_num=8;
  channel.dma_frame_num=120;
  esp_err_t rc=i2s_new_channel(&channel,&tx,&rx);
  if(rc!=ESP_OK){reportError("CHANNEL_ALLOC",rc);break;}
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
  rc=i2s_channel_init_std_mode(tx,&config);
  if(rc!=ESP_OK){reportError("TX_STD_INIT",rc);break;}
  rc=i2s_channel_init_std_mode(rx,&config);
  if(rc!=ESP_OK){reportError("RX_STD_INIT",rc);break;}
  rc=i2s_channel_enable(tx);
  if(rc!=ESP_OK){reportError("TX_ENABLE",rc);break;}
  txOn=true;
  rc=i2s_channel_enable(rx);
  if(rc!=ESP_OK){reportError("RX_ENABLE",rc);break;}
  rxOn=true;
  ready=true;lastError="NONE";
  Serial.printf("[CALL] I2S 24kHz duplex active: BCLK=%d WS=%d MIC=%d SPK=%d\n",
   BrainPinPlan::I2S_BCLK,BrainPinPlan::I2S_WS,
   BrainPinPlan::I2S_DIN,BrainPinPlan::I2S_DOUT);
  // Work buffers live in PSRAM, never in the audio task's internal stack.
  // The pinned task is the only writer to these buffers.
  while(!stopping){
   size_t read=0;
   esp_err_t readError=i2s_channel_read(rx,work->capture,sizeof(work->capture),&read,160);
   if(readError!=ESP_OK || read!=sizeof(work->capture)){
    reportError("MIC_READ",readError);break;
   }
   bool hasAudio=xQueueReceive(speakerQueue,&work->speaker,0)==pdTRUE;
   playing=hasAudio;
   if(hasAudio)lastPlaybackMs=millis();
   // Wait until provider has stopped responding AND acoustic tail is gone.
   bool mute=remoteReply || hasAudio ||
     (uint32_t)(millis()-lastPlaybackMs)<TAIL_MUTE_MS;
   for(size_t i=0;i<SAMPLES;i++){
    int32_t value=0;
    if(!mute){
     // INMP441 L/R wired to GND => left slot; 24-bit left-aligned input.
     int32_t raw=work->capture[i*2]>>16;
     value=(raw*(int32_t)micGain)/100;
     if(value>32767)value=32767;
     if(value< -32768)value=-32768;
    }
    work->mic.pcm[i]=(int16_t)value;
    int32_t out=hasAudio?(int32_t)work->speaker.pcm[i]*speakerVolume/100:0;
    // Bound first hardware tests to ~38% full scale even at volume=100.
    if(out>12500)out=12500;
    if(out< -12500)out=-12500;
    work->output[2*i]=(int32_t)((int64_t)out*65536LL);
    work->output[2*i+1]=(int32_t)((int64_t)out*65536LL);
   }
   if(xQueueSend(micQueue,&work->mic,0)!=pdTRUE){
    // Prefer freshest audio instead of accumulating latency on a slow Wi-Fi link.
    (void)xQueueReceive(micQueue,&work->discard,0);
    (void)xQueueSend(micQueue,&work->mic,0);
    droppedMic++;
   }
   size_t written=0;
   esp_err_t writeError=i2s_channel_write(tx,work->output,sizeof(work->output),&written,160);
   if(writeError!=ESP_OK || written!=sizeof(work->output)){
    reportError("SPEAKER_WRITE",writeError);break;
   }
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
 // Allocate 60KB of queue payloads in PSRAM, not scarce internal SRAM.
 if(!psramFound()){
  reportError("NO_PSRAM_ENABLE_OPI");return false;
 }
 if(!work)
  work=(Buffers*)heap_caps_calloc(1,sizeof(Buffers),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 if(!work){reportError("PSRAM_AUDIO_BUFFERS");return false;}
 if(!micQueueStorage)
  micQueueStorage=(uint8_t*)heap_caps_malloc(MIC_FRAMES*sizeof(Frame),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 if(!speakerQueueStorage)
  speakerQueueStorage=(uint8_t*)heap_caps_malloc(SPEAKER_FRAMES*sizeof(Frame),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 if(!micQueueStorage||!speakerQueueStorage){
  reportError("PSRAM_QUEUE_STORAGE");return false;
 }
 if(!micQueue)
  micQueue=xQueueCreateStatic(MIC_FRAMES,sizeof(Frame),micQueueStorage,&micQueueControl);
 if(!speakerQueue)
  speakerQueue=xQueueCreateStatic(SPEAKER_FRAMES,sizeof(Frame),speakerQueueStorage,&speakerQueueControl);
 if(!micQueue||!speakerQueue){
  reportError("STATIC_QUEUE_CREATE");return false;
 }
 Serial.printf("[CALL AUDIO] PSRAM queues ready: uplink=%u downlink=%u frames; internal free=%lu\n",
   (unsigned)MIC_FRAMES,(unsigned)SPEAKER_FRAMES,
   (unsigned long)heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT));
 xQueueReset(micQueue);xQueueReset(speakerQueue);
 micGain=constrain((int)gain,0,300);
 speakerVolume=constrain((int)volume,0,100);
 lastPlaybackMs=millis()-TAIL_MUTE_MS;
 droppedMic=0;fault=false;ready=false;stopping=false;lastError="STARTING";
 playing=false;remoteReply=false;running=true;
 // Less than half the previous internal stack; fixed PCM buffers now live
 // in external PSRAM, so the stack only handles driver calls and scalars.
 if(xTaskCreatePinnedToCore(audioTask,"call_i2s",8192,nullptr,3,&owner,0)!=pdPASS){
  running=false;owner=nullptr;fault=true;reportError("AUDIO_TASK_ALLOC");return false;
 }
 return true;
}
inline void stop(){
 stopping=true;
 // Bounded I2S timeouts are 160ms; let the task finish and release
 // its channel before allowing manual PTT or another call to start.
 uint32_t since=millis();
 while(running && (uint32_t)(millis()-since)<450) vTaskDelay(pdMS_TO_TICKS(2));
 remoteReply=false;ready=false;
 if(micQueue)xQueueReset(micQueue);
 if(speakerQueue)xQueueReset(speakerQueue);
 if(running)Serial.println("[CALL] I2S teardown still finishing; legacy audio stays blocked");
}
} // namespace BrainRealtimeAudio
