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
 Frame mic, speaker, discard;
};
static Buffers *work=nullptr;
// Core 0 drains speaker audio at hardware clock rate. A realtime provider can
// deliver several seconds of PCM in one WebSocket event, much faster than 1x
// playback. A fixed 960ms speaker queue cannot hold those bursts.
// Keep a bounded PCM16 mono ring in PSRAM, independent from the 20ms mic queue.
static QueueHandle_t micQueue=nullptr;
static StaticQueue_t micQueueControl;
static uint8_t *micQueueStorage=nullptr;
static constexpr UBaseType_t MIC_FRAMES=16;
static int16_t *speakerRing=nullptr;
static size_t speakerCapacity=0, speakerRead=0, speakerWrite=0, speakerCount=0;
static portMUX_TYPE speakerMux=portMUX_INITIALIZER_UNLOCKED;
static volatile uint32_t speakerOverrunSamples=0, speakerOverrunEvents=0;
static volatile uint32_t speakerPeakSamples=0;
static volatile uint32_t speakerUnderruns=0;
inline uint32_t bufferedMs(){
 portENTER_CRITICAL(&speakerMux);
 size_t count=speakerCount;
 portEXIT_CRITICAL(&speakerMux);
 return (uint32_t)((count*1000ULL)/RATE);
}
inline uint32_t droppedSpeakerMs(){return (uint32_t)((speakerOverrunSamples*1000ULL)/RATE);}
inline uint32_t peakSpeakerMs(){return (uint32_t)((speakerPeakSamples*1000ULL)/RATE);}
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
static volatile bool bargeRequested=false,bargeActive=false;
static uint8_t bargeFrames=0;
static int32_t noiseFloor=200;
static int32_t dcEstimate=0;
static volatile uint32_t bargeCooldownUntil=0;
static volatile uint32_t overlapMicLevel=0,overlapSpkLevel=0,overlapTriggers=0;
inline uint32_t nearMicLevel(){return overlapMicLevel;}
inline uint32_t playbackReferenceLevel(){return overlapSpkLevel;}
inline uint32_t overlapCount(){return overlapTriggers;}
inline bool takeBargeRequest(){if(!bargeRequested)return false;bargeRequested=false;return true;}
inline void resetBarge(){bargeRequested=false;bargeActive=false;bargeFrames=0;bargeCooldownUntil=millis()+600;}
static volatile uint32_t lastPlaybackMs=0;
static uint16_t micGain=100;
static uint8_t speakerVolume=35;
// Small adaptive NLMS acoustic echo canceller. The physical DAC samples are
// the reference; never lower their volume in response to near-end speech.
// Reference precedes mic capture by at least one I2S 20 ms DMA transaction.
// Filtering runs only in the pinned audio task on Core 0.
static constexpr int AEC_TAPS=192;
static constexpr int AEC_REF_SIZE=2048;
static float aecWeights[AEC_TAPS]={};
static float aecReference[AEC_REF_SIZE]={};
static uint32_t aecWrite=0;
static float aecEchoPower=0;
static volatile uint32_t aecResidualLevel=0;
inline uint32_t residualLevel(){return aecResidualLevel;}
inline void resetAEC(){
 memset(aecWeights,0,sizeof(aecWeights));
 memset(aecReference,0,sizeof(aecReference));
 aecWrite=0;aecEchoPower=0;aecResidualLevel=0;
}
static volatile uint32_t droppedMic=0;
// PCM energy for the C5 full-screen Kitty mouth, no microphone inference.
static volatile uint8_t outputLipLevel=0;
inline uint8_t lipLevel(){return outputLipLevel;}
static TaskHandle_t owner=nullptr;

inline bool active(){return running;}
inline bool initialized(){return running && ready && !fault;}
inline bool failed(){return fault;}
inline bool hasSpeakerAudio(){
 portENTER_CRITICAL(&speakerMux);
 bool buffered=speakerCount>0;
 portEXIT_CRITICAL(&speakerMux);
 return playing || buffered;
}
inline void setRemoteReply(bool active){remoteReply=active;}
inline void clearSpeaker(){
 portENTER_CRITICAL(&speakerMux);
 speakerRead=0;speakerWrite=0;speakerCount=0;
 portEXIT_CRITICAL(&speakerMux);
 remoteReply=false;
}
inline bool takeMic(Frame &f){
 return micQueue && xQueueReceive(micQueue,&f,0)==pdTRUE;
}
// No network callback waits on the 24kHz DAC clock. Provider data are accepted
// immediately into PSRAM, including large deltas delivered in a single burst.
// A pathological >ring-size response discards the oldest pending audio rather
// than failing the WebSocket call. Count overruns for diagnostics.
inline bool queueSpeaker(const uint8_t *pcm,size_t bytes){
 if(!ready || !speakerRing || !pcm || !bytes || (bytes&1u))return false;
 size_t total=bytes/2;
 size_t at=0;
 while(at<total){
  const size_t n=min((size_t)SAMPLES,total-at);
  int16_t block[SAMPLES];
  for(size_t i=0;i<n;i++){
   const size_t off=(at+i)*2;
   block[i]=(int16_t)((uint16_t)pcm[off]|((uint16_t)pcm[off+1]<<8));
  }
  portENTER_CRITICAL(&speakerMux);
  if(n>speakerCapacity-speakerCount){
   const size_t discard=n-(speakerCapacity-speakerCount);
   speakerRead=(speakerRead+discard)%speakerCapacity;
   speakerCount-=discard;
   speakerOverrunSamples+=(uint32_t)discard;
   speakerOverrunEvents++;
  }
  const size_t beforeWrap=min(n,speakerCapacity-speakerWrite);
  memcpy(speakerRing+speakerWrite,block,beforeWrap*sizeof(int16_t));
  if(n>beforeWrap)memcpy(speakerRing,block+beforeWrap,(n-beforeWrap)*sizeof(int16_t));
  speakerWrite=(speakerWrite+n)%speakerCapacity;
  speakerCount+=n;
  if(speakerCount>speakerPeakSamples)speakerPeakSamples=(uint32_t)speakerCount;
  portEXIT_CRITICAL(&speakerMux);
  at+=n;
 }
 return true;
}
inline bool nextSpeaker(Frame &frame){
 bool haveAudio=false;
 memset(&frame,0,sizeof(frame));
 portENTER_CRITICAL(&speakerMux);
 const size_t n=min((size_t)SAMPLES,speakerCount);
 if(n){
  haveAudio=true;
  const size_t beforeWrap=min(n,speakerCapacity-speakerRead);
  memcpy(frame.pcm,speakerRing+speakerRead,beforeWrap*sizeof(int16_t));
  if(n>beforeWrap)memcpy(frame.pcm+beforeWrap,speakerRing,(n-beforeWrap)*sizeof(int16_t));
  speakerRead=(speakerRead+n)%speakerCapacity;
  speakerCount-=n;
 }else if(remoteReply){
  speakerUnderruns++;
 }
 portEXIT_CRITICAL(&speakerMux);
 return haveAudio;
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
   bool hasAudio=nextSpeaker(work->speaker);
   playing=hasAudio;
   if(hasAudio){
    uint32_t sum=0;
    for(size_t i=0;i<SAMPLES;i+=4){
     int v=work->speaker.pcm[i];
     sum+=(uint32_t)(v<0?-v:v);
    }
    // Average source PCM magnitude, quantized to 0..9. The Arduino loop
    // sends this tiny value at <=8Hz; I2S never touches the UART/LCD.
    uint32_t avg=sum/(SAMPLES/4);
    outputLipLevel=(uint8_t)min((uint32_t)9,(avg+360)/1250);
   }else outputLipLevel=0;
   if(hasAudio)lastPlaybackMs=millis();
   // Calibrated-reference adaptive AEC: consume the microphone sample
   // while predicting the speaker's acoustic contribution from a delayed
   // stream of samples ACTUALLY written to the MAX98357A.
   // Filter adaptation freezes during likely double-talk, protecting speech.
   uint64_t nearEnergy=0,spkEnergy=0;
   uint32_t postEnergy=0;
   const bool outputActive=hasAudio || remoteReply;
   const float inv32768=1.0f/32768.0f;
   const uint32_t playbackDelay=480; // previous 20ms I2S write frame
   for(size_t i=0;i<SAMPLES;i++){
    int32_t raw=work->capture[i*2]>>16;
    dcEstimate+=(raw-dcEstimate)/512;
    raw-=dcEstimate;
    int32_t played=hasAudio?(int32_t)work->speaker.pcm[i]*speakerVolume/100:0;
    played=constrain(played,-12500,12500);
    work->output[i*2]=(int32_t)((int64_t)played*65536LL);
    work->output[i*2+1]=work->output[i*2];
    // Use previous output frames; current outgoing frame has not yet reached DAC.
    uint32_t base=(aecWrite+AEC_REF_SIZE-playbackDelay)%AEC_REF_SIZE;
    float echo=0,norm=0;
    for(int k=0;k<AEC_TAPS;k++){
     const float ref=aecReference[(base+AEC_REF_SIZE-k)%AEC_REF_SIZE];
     echo+=aecWeights[k]*ref;
     norm+=ref*ref;
    }
    const float mic=(float)raw*inv32768;
    const float clean=mic-echo;
    // Conservative LMS: keep adapting only when speaker is present and
    // microphone is broadly dominated by the predicted echo.
    if(outputActive && norm>0.0003f && fabsf(mic)<fabsf(echo)*2.5f+0.022f){
     const float step=0.13f*clean/(0.02f+norm);
     for(int k=0;k<AEC_TAPS;k++)
      aecWeights[k]+=step*aecReference[(base+AEC_REF_SIZE-k)%AEC_REF_SIZE];
    }
    float filtered=outputActive?clean:mic;
    int32_t value=(int32_t)(filtered*32768.0f);
    value=(value*(int32_t)micGain)/100;
    value=constrain(value,-32768,32767);
    work->mic.pcm[i]=(int16_t)value;
    aecReference[aecWrite]=(float)played*inv32768;
    aecWrite=(aecWrite+1)%AEC_REF_SIZE;
    if((i&3)==0){
     int32_t v=value;
     nearEnergy+=(uint32_t)(v<0?-v:v);
     spkEnergy+=(uint32_t)(played<0?-played:played);
    }
   }
   const uint32_t micLevel=(uint32_t)(nearEnergy/(SAMPLES/4));
   const uint32_t outputLevel=(uint32_t)(spkEnergy/(SAMPLES/4));
   overlapMicLevel=micLevel;overlapSpkLevel=outputLevel;
   aecResidualLevel=micLevel;
   if(!hasAudio && !remoteReply && !bargeActive &&
      micLevel<(uint32_t)(noiseFloor*3+300))
    noiseFloor=(noiseFloor*31+(int32_t)micLevel)/32;
   // The post-AEC near-end energy, not raw microphone energy, controls
   // overlap detection. Capture and transmit audio throughout playback.
   const uint32_t threshold=max((uint32_t)420,(uint32_t)(noiseFloor*3+220));
   if(outputActive && (int32_t)(millis()-bargeCooldownUntil)>=0){
    if(micLevel>threshold && micLevel>outputLevel/6+190){
     if(bargeFrames<20)bargeFrames++;
    }else if(bargeFrames>0)bargeFrames--;
    if(bargeFrames>=5 && !bargeActive){
     bargeActive=true;bargeRequested=true;overlapTriggers++;
    }
   }else if(!outputActive)bargeFrames=0;
   // Never duck, mute, or cancel Kitty just because the user is talking.
   if(!outputActive && bargeActive)bargeActive=false;
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
 playing=false;outputLipLevel=0;
 if(rx){if(rxOn)i2s_channel_disable(rx);i2s_del_channel(rx);}
 if(tx){if(txOn)i2s_channel_disable(tx);i2s_del_channel(tx);}
 running=false;
 owner=nullptr;
 vTaskDelete(nullptr);
}

inline bool start(uint16_t gain,uint8_t volume){
 if(running || owner)return false;
 // The 8MB-PSRAM S3 needs to absorb bursts from upstream TTS.
 // Prefer 24 seconds (1.15MB), fall back to 12 or 6 seconds when memory
 // is fragmented. Even 6s dwarfs the old 960ms fixed queue.
 if(!psramFound()){
  reportError("NO_PSRAM_ENABLE_OPI");return false;
 }
 if(!work)
  work=(Buffers*)heap_caps_calloc(1,sizeof(Buffers),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 if(!work){reportError("PSRAM_AUDIO_BUFFERS");return false;}
 if(!speakerRing){
  for(uint32_t seconds: {24u,12u,6u}){
   size_t candidate=(size_t)RATE*seconds;
   speakerRing=(int16_t*)heap_caps_malloc(candidate*sizeof(int16_t),
                                          MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
   if(speakerRing){speakerCapacity=candidate;break;}
  }
 }
 if(!speakerRing || speakerCapacity<SAMPLES){
  reportError("PSRAM_SPEAKER_RING");return false;
 }
 if(!micQueueStorage)
  micQueueStorage=(uint8_t*)heap_caps_malloc(MIC_FRAMES*sizeof(Frame),
                                             MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 if(!micQueueStorage){reportError("PSRAM_MIC_STORAGE");return false;}
 if(!micQueue)
  micQueue=xQueueCreateStatic(MIC_FRAMES,sizeof(Frame),micQueueStorage,&micQueueControl);
 if(!micQueue){reportError("STATIC_MIC_QUEUE");return false;}
 Serial.printf("[CALL AUDIO] PSRAM buffers ready: speaker_capacity=%lu ms mic_frames=%u internal_free=%lu\\n",
  (unsigned long)(speakerCapacity*1000ULL/RATE),(unsigned)MIC_FRAMES,
  (unsigned long)heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT));
 xQueueReset(micQueue);
 clearSpeaker();resetBarge();overlapMicLevel=0;overlapSpkLevel=0;overlapTriggers=0;
 speakerOverrunSamples=0;speakerOverrunEvents=0;speakerPeakSamples=0;speakerUnderruns=0;
 micGain=constrain((int)gain,0,300);
 speakerVolume=constrain((int)volume,0,100);
 lastPlaybackMs=millis()-TAIL_MUTE_MS;
 droppedMic=0;outputLipLevel=0;fault=false;ready=false;stopping=false;lastError="STARTING";
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
 remoteReply=false;ready=false;outputLipLevel=0;
 if(micQueue)xQueueReset(micQueue);
 clearSpeaker();
 if(running)Serial.println("[CALL] I2S teardown still finishing; legacy audio stays blocked");
}
} // namespace BrainRealtimeAudio
