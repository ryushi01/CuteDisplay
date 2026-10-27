#pragma once
// Local 2-second INMP441 -> MAX98357A loopback test.
// Trigger ONLY with USB Serial Monitor command: audio test
// Requires ESP32 Arduino core 3.3.12 (ESP-IDF I2S STD driver).
#include <Arduino.h>
#include <driver/i2s_std.h>
#include <esp_heap_caps.h>
#include <Preferences.h>
#include "BrainPinPlan.h"
namespace BrainAudioTest {
static volatile bool running=false;
static uint16_t micGain=150; // percent, 0-300
static uint8_t speakerVolume=65; // percent, 0-100
inline void loadLevels(){
 Preferences prefs;
 if(prefs.begin("brain-audio",true)){
  micGain=constrain((int)prefs.getUShort("mic",150),0,300);
  speakerVolume=constrain((int)prefs.getUChar("speaker",65),0,100);
  prefs.end();
 }
 Serial.printf("[AUDIO] Settings mic_gain=%u%% speaker_volume=%u%%\n",micGain,speakerVolume);
}
inline bool setLevel(const String &cmd){
 bool mic=cmd.startsWith("A:MIC:");
 bool spk=cmd.startsWith("A:SPK:");
 if(!mic&&!spk)return false;
 String value=cmd.substring(mic?6:6);
 if(value.isEmpty()||value.length()>3){Serial.println("[AUDIO] Bad audio setting");return true;}
 for(size_t i=0;i<value.length();i++)if(!isDigit(value[i])){
  Serial.println("[AUDIO] Bad audio setting");return true;
 }
 int level=value.toInt();
 if(level>(mic?300:100)){Serial.println("[AUDIO] Audio setting outside range");return true;}
 if(mic)micGain=(uint16_t)level;
 else speakerVolume=(uint8_t)level;
 Preferences prefs;
 if(prefs.begin("brain-audio",false)){
  if(mic)prefs.putUShort("mic",micGain);else prefs.putUChar("speaker",speakerVolume);
  prefs.end();
 }
 Serial.printf("[AUDIO] Settings mic_gain=%u%% speaker_volume=%u%%\n",micGain,speakerVolume);
 return true;
}

static constexpr uint32_t RATE=16000, SECONDS=2;
static constexpr size_t FRAMES=RATE*SECONDS;
static constexpr size_t BLOCK=128;
static void task(void *) {
  i2s_chan_handle_t tx=nullptr,rx=nullptr;
  int32_t *recorded=nullptr;
  const char *failure=nullptr;
  uint32_t speechPeak=0;
  const uint64_t targetPeak=0x48000000ULL;
  uint32_t autoGainQ10=1024;
  recorded=(int32_t*)heap_caps_malloc(FRAMES*sizeof(int32_t),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
  if(!recorded){failure="PSRAM allocation failed";goto done;}
  {
    i2s_chan_config_t ch=I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0,I2S_ROLE_MASTER);
    esp_err_t err=i2s_new_channel(&ch,&tx,&rx);
    if(err!=ESP_OK){failure="i2s_new_channel failed";goto done;}
    i2s_std_config_t cfg={
      .clk_cfg=I2S_STD_CLK_DEFAULT_CONFIG(RATE),
      .slot_cfg=I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT,I2S_SLOT_MODE_STEREO),
      .gpio_cfg={
        .mclk=I2S_GPIO_UNUSED,
        .bclk=(gpio_num_t)BrainPinPlan::I2S_BCLK,
        .ws=(gpio_num_t)BrainPinPlan::I2S_WS,
        .dout=(gpio_num_t)BrainPinPlan::I2S_DOUT,
        .din=(gpio_num_t)BrainPinPlan::I2S_DIN,
        .invert_flags={.mclk_inv=false,.bclk_inv=false,.ws_inv=false}
      }
    };
    if(i2s_channel_init_std_mode(tx,&cfg)!=ESP_OK ||
       i2s_channel_init_std_mode(rx,&cfg)!=ESP_OK){
      failure="I2S STD initialization failed";goto done;
    }
    if(i2s_channel_enable(tx)!=ESP_OK || i2s_channel_enable(rx)!=ESP_OK){
      failure="I2S enable failed";goto done;
    }
  }
  Serial.println("[AUDIO] Recording 2 seconds at 16 kHz. Speak now.");
  {
    int32_t block[BLOCK*2];
    uint32_t maxAbs[2]={0,0};
    uint32_t saturated[2]={0,0}, allOnes[2]={0,0};
    uint32_t nonzero[2]={0,0};
    uint64_t sumAbs[2]={0,0};
    for(size_t start=0;start<FRAMES;start+=BLOCK){
      size_t got=0;
      if(i2s_channel_read(rx,block,sizeof(block),&got,1500)!=ESP_OK || got!=sizeof(block)){
        failure="microphone read timeout/error";goto done;
      }
      for(size_t i=0;i<BLOCK;i++){
        for(int ch=0;ch<2;ch++){
          int32_t raw=block[i*2+ch];
          int64_t magnitude=raw<0?-(int64_t)raw:(int64_t)raw;
          if(magnitude>maxAbs[ch])maxAbs[ch]=(uint32_t)magnitude;
          sumAbs[ch]+=(uint64_t)magnitude;
          if(raw!=0)nonzero[ch]++;
          if(raw==INT32_MAX || raw==INT32_MIN)saturated[ch]++;
          if(raw==-1 || raw==INT32_MAX)allOnes[ch]++;
        }
        // INMP441 L/R grounded should put the audio in the left slot.
        recorded[start+i]=block[2*i];
      }
    }
    Serial.printf("[AUDIO] RX left: peak=%lu mean_abs=%lu nonzero=%lu saturated=%lu all_ones=%lu\n",
       (unsigned long)maxAbs[0],(unsigned long)(sumAbs[0]/FRAMES),
       (unsigned long)nonzero[0],(unsigned long)saturated[0],(unsigned long)allOnes[0]);
    Serial.printf("[AUDIO] RX right: peak=%lu mean_abs=%lu nonzero=%lu saturated=%lu all_ones=%lu\n",
       (unsigned long)maxAbs[1],(unsigned long)(sumAbs[1]/FRAMES),
       (unsigned long)nonzero[1],(unsigned long)saturated[1],(unsigned long)allOnes[1]);
    if(saturated[0]>0 || allOnes[0]>FRAMES/100 || maxAbs[0]>=0x7FFFFFFF ||
       sumAbs[0]/FRAMES>0x30000000ULL){
      Serial.println("[AUDIO] INVALID microphone signal: saturated/high-level input; playback skipped to avoid loud noise.");
      Serial.println("[AUDIO] Check INMP441 soldered SD/SCK/WS/GND/VDD/LR, mic supply 3V3, L/R=GND.");
      goto done;
    }
    if(nonzero[0]<FRAMES/100 || sumAbs[0]/FRAMES<10000ULL){
      Serial.println("[AUDIO] Input near silent: playback skipped. Check microphone DATA on GPIO1.");
      goto done;
    }
  }
  // Recordings can contain occasional high transient peaks. Calculate\n  // playback level from average energy rather than a single peak; clamp output.
  speechPeak=0;
  for(size_t i=0;i<FRAMES;i++){
    int64_t m=recorded[i]<0?-(int64_t)recorded[i]:(int64_t)recorded[i];
    if(m>speechPeak)speechPeak=(uint32_t)m;
  }
  autoGainQ10=(uint32_t)min(8192ULL,\n    (targetPeak*1024ULL)/max((uint32_t)1,speechPeak));
  // Never attenuate during normalization; speakerVolume remains attenuation.
  if(autoGainQ10<1024)autoGainQ10=1024;
  Serial.printf("[AUDIO] Playback raw_peak=%lu auto_gain=%.2fx mic_gain=%u%% speaker_volume=%u%%\n",
    (unsigned long)speechPeak,autoGainQ10/1024.0f,micGain,speakerVolume);
  {
    int32_t stereo[BLOCK*2];
    for(size_t start=0;start<FRAMES;start+=BLOCK){
      for(size_t i=0;i<BLOCK;++i){
        // Clamp suspicious transients, then apply bounded digital normalization.
        int32_t sample=recorded[start+i];
        if(sample>0x28000000)sample=0x28000000;\n        if(sample<-(int32_t)0x28000000)sample=-(int32_t)0x28000000;
        // Fixed-point gain adjustment with wide intermediate, no overflow.
        int64_t scaled=((int64_t)sample*autoGainQ10*micGain*speakerVolume)/(1024LL*10000LL);
        const int64_t ceiling=0x38000000LL;
        if(scaled>ceiling)scaled=ceiling;
        if(scaled<-ceiling)scaled=-ceiling;
        stereo[2*i]=(int32_t)scaled;stereo[2*i+1]=(int32_t)scaled;
      }
      size_t written=0;
      if(i2s_channel_write(tx,stereo,sizeof(stereo),&written,1500)!=ESP_OK ||
         written!=sizeof(stereo)){
        failure="amplifier write timeout/error";goto done;
      }
    }
  }
done:
  if(rx){i2s_channel_disable(rx);i2s_del_channel(rx);}
  if(tx){i2s_channel_disable(tx);i2s_del_channel(tx);}
  if(recorded)heap_caps_free(recorded);
  if(failure)Serial.printf("[AUDIO] ERROR: %s\n",failure);
  else Serial.println("[AUDIO] COMPLETE: local record/play test finished.");
  running=false;
  vTaskDelete(nullptr);
}

static void beepTask(void *arg) {
 if((uintptr_t)arg)vTaskDelay(pdMS_TO_TICKS(2200));
 i2s_chan_handle_t tx=nullptr;
 const char *error=nullptr;
 {
  i2s_chan_config_t ch=I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_1,I2S_ROLE_MASTER);
  if(i2s_new_channel(&ch,&tx,nullptr)!=ESP_OK){error="create TX";goto doneBeep;}
  i2s_std_config_t cfg={
   .clk_cfg=I2S_STD_CLK_DEFAULT_CONFIG(RATE),
   .slot_cfg=I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT,I2S_SLOT_MODE_STEREO),
   .gpio_cfg={.mclk=I2S_GPIO_UNUSED,
    .bclk=(gpio_num_t)BrainPinPlan::I2S_BCLK,
    .ws=(gpio_num_t)BrainPinPlan::I2S_WS,
    .dout=(gpio_num_t)BrainPinPlan::I2S_DOUT,
    .din=I2S_GPIO_UNUSED,
    .invert_flags={.mclk_inv=false,.bclk_inv=false,.ws_inv=false}}
  };
  if(i2s_channel_init_std_mode(tx,&cfg)!=ESP_OK){error="init TX";goto doneBeep;}
  if(i2s_channel_enable(tx)!=ESP_OK){error="enable TX";goto doneBeep;}
 }
 Serial.println("[AUDIO] BEEP: short startup/test chirp");
 {
  int32_t samples[BLOCK*2];
  uint32_t phase=0;
  const uint32_t notes[]={880};
  for(int n=0;n<1;++n){
   uint32_t step=(uint32_t)(((uint64_t)notes[n]*4294967296ULL)/RATE);
   for(int chunk=0;chunk<14;++chunk){
    for(size_t i=0;i<BLOCK;++i){
     phase+=step;
     uint32_t p=phase>>16;
     int32_t tri=p<32768?(int32_t)p:(int32_t)(65535-p);
     // Previous chirp was ~3% full scale and extremely quiet.\n     // Raise to ~25% full scale, with 8ms attack/release to avoid pops.\n     const int32_t sampleIndex=chunk*(int32_t)BLOCK+(int32_t)i;\n     const int32_t totalSamples=14*(int32_t)BLOCK;\n     int32_t edge=min(sampleIndex,totalSamples-1-sampleIndex);\n     int32_t fade=min((int32_t)128,edge);\n     int32_t sample=(int32_t)(((int64_t)(tri-16384)*32768*fade)/128);\n     samples[2*i]=sample;samples[2*i+1]=sample;
    }
    size_t written=0;
    if(i2s_channel_write(tx,samples,sizeof(samples),&written,1500)!=ESP_OK || written!=sizeof(samples)){
     error="write TX";goto doneBeep;
    }
   }
  }
 }
doneBeep:
 if(tx){i2s_channel_disable(tx);i2s_del_channel(tx);}
 if(error)Serial.printf("[AUDIO] BEEP ERROR: %s\n",error);
 else Serial.println("[AUDIO] BEEP COMPLETE: check audible output");
 running=false;vTaskDelete(nullptr);
}
inline void beep(bool onBoot=false){
 if(running){Serial.println("[AUDIO] Busy");return;}
 running=true;
 if(xTaskCreatePinnedToCore(beepTask,"audio_beep",8192,(void*)(uintptr_t)(onBoot?1:0),2,nullptr,0)!=pdPASS){
  running=false;Serial.println("[AUDIO] BEEP ERROR: task start failed");
 }
}

static void diagnoseTask(void *) {
 i2s_chan_handle_t tx=nullptr;
 const char *error=nullptr;
 {
  i2s_chan_config_t ch=I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_1,I2S_ROLE_MASTER);
  esp_err_t rc=i2s_new_channel(&ch,&tx,nullptr);
  if(rc!=ESP_OK){Serial.printf("[AUDIO] DIAG channel error=%d\n",(int)rc);error="create";goto diagnosticEnd;}
  i2s_std_config_t cfg={
   .clk_cfg=I2S_STD_CLK_DEFAULT_CONFIG(16000),
   .slot_cfg=I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT,I2S_SLOT_MODE_STEREO),
   .gpio_cfg={
    .mclk=I2S_GPIO_UNUSED,
    .bclk=(gpio_num_t)BrainPinPlan::I2S_BCLK,
    .ws=(gpio_num_t)BrainPinPlan::I2S_WS,
    .dout=(gpio_num_t)BrainPinPlan::I2S_DOUT,
    .din=I2S_GPIO_UNUSED,
    .invert_flags={.mclk_inv=false,.bclk_inv=false,.ws_inv=false}
   }
  };
  rc=i2s_channel_init_std_mode(tx,&cfg);
  if(rc!=ESP_OK){Serial.printf("[AUDIO] DIAG init error=%d\n",(int)rc);error="init";goto diagnosticEnd;}
  rc=i2s_channel_enable(tx);
  if(rc!=ESP_OK){Serial.printf("[AUDIO] DIAG enable error=%d\n",(int)rc);error="enable";goto diagnosticEnd;}
 }
 Serial.printf("[AUDIO] DIAG TX16 rate=16000 BCLK=GPIO%d WS=GPIO%d DIN=GPIO%d\n",
      BrainPinPlan::I2S_BCLK,BrainPinPlan::I2S_WS,BrainPinPlan::I2S_DOUT);
 {
  int16_t frame[BLOCK*2];
  uint32_t phase=0;
  uint32_t step=(uint32_t)((1000ULL*4294967296ULL)/16000ULL);
  for(int k=0;k<250;k++){ // 250*128/16000=2 seconds
   for(size_t i=0;i<BLOCK;i++){
    phase+=step;
    uint32_t p=phase>>16;
    int32_t tri=p<32768?(int32_t)p:(int32_t)(65535-p);
    int16_t sample=(int16_t)((tri-16384)/3); // lower volume, ~17% full-scale
    frame[2*i]=sample;frame[2*i+1]=sample;
   }
   size_t written=0;
   esp_err_t rc=i2s_channel_write(tx,frame,sizeof(frame),&written,1500);
   if(rc!=ESP_OK||written!=sizeof(frame)){
    Serial.printf("[AUDIO] DIAG write error=%d bytes=%u\n",(int)rc,(unsigned)written);
    error="write";break;
   }
  }
 }
diagnosticEnd:
 if(tx){i2s_channel_disable(tx);i2s_del_channel(tx);}
 if(error)Serial.printf("[AUDIO] DIAG FAILED: %s\n",error);
 else Serial.println("[AUDIO] DIAG COMPLETE: 16-bit tone written; report whether audible");
 running=false;
 vTaskDelete(nullptr);
}
inline void diagnose(){
 if(running){Serial.println("[AUDIO] Busy; retry later");return;}
 running=true;
 if(xTaskCreatePinnedToCore(diagnoseTask,"audio_diag",8192,nullptr,2,nullptr,0)!=pdPASS){
  running=false;Serial.println("[AUDIO] DIAG FAILED: could not start task");
 }
}
inline void start() {
  if(running){Serial.println("[AUDIO] Already running");return;}
  running=true;
  if(xTaskCreatePinnedToCore(task,"audio_test",8192,nullptr,2,nullptr,0)!=pdPASS){
    running=false;
    Serial.println("[AUDIO] ERROR: could not start test task");
  }
}
} // namespace BrainAudioTest
