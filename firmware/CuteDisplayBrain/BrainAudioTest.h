#pragma once
// Local 2-second INMP441 -> MAX98357A loopback test.
// Trigger ONLY with USB Serial Monitor command: audio test
// Requires ESP32 Arduino core 3.3.12 (ESP-IDF I2S STD driver).
#include <Arduino.h>
#include <driver/i2s_std.h>
#include <esp_heap_caps.h>
#include "BrainPinPlan.h"
namespace BrainAudioTest {
static volatile bool running=false;
static constexpr uint32_t RATE=16000, SECONDS=2;
static constexpr size_t FRAMES=RATE*SECONDS;
static constexpr size_t BLOCK=128;
static void task(void *) {
  i2s_chan_handle_t tx=nullptr,rx=nullptr;
  int32_t *recorded=nullptr;
  const char *failure=nullptr;
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
    int64_t peak=0;
    for(size_t start=0;start<FRAMES;start+=BLOCK){
      size_t got=0;
      if(i2s_channel_read(rx,block,sizeof(block),&got,1500)!=ESP_OK || got!=sizeof(block)){
        failure="microphone read timeout/error";goto done;
      }
      for(size_t i=0;i<BLOCK;++i){
        // INMP441 L/R wired to GND => left slot.
        int32_t sample=block[i*2];
        recorded[start+i]=sample;
        int64_t level=sample<0?-(int64_t)sample:(int64_t)sample;
        if(level>peak)peak=level;
      }
    }
    Serial.printf("[AUDIO] Recorded 2 seconds, microphone peak=%lld\n",(long long)peak);
    if(peak<100000){Serial.println("[AUDIO] WARNING: input almost silent; check INMP441 SD, L/R=GND and clocks.");}
  }
  Serial.println("[AUDIO] Playing recording through MAX98357A at reduced level.");
  {
    int32_t stereo[BLOCK*2];
    for(size_t start=0;start<FRAMES;start+=BLOCK){
      for(size_t i=0;i<BLOCK;++i){
        int32_t quiet=recorded[start+i]>>3; // -18 dB approximate volume
        stereo[2*i]=quiet;
        stereo[2*i+1]=quiet;
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
 if((uintptr_t)arg)vTaskDelay(pdMS_TO_TICKS(4500));
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
 Serial.println("[AUDIO] BEEP: testing speaker with two tones");
 {
  int32_t samples[BLOCK*2];
  uint32_t phase=0;
  const uint32_t notes[]={660,880};
  for(int n=0;n<2;++n){
   uint32_t step=(uint32_t)(((uint64_t)notes[n]*4294967296ULL)/RATE);
   for(int chunk=0;chunk<40;++chunk){
    for(size_t i=0;i<BLOCK;++i){
     phase+=step;
     uint32_t p=phase>>16;
     int32_t tri=p<32768?(int32_t)p:(int32_t)(65535-p);
     int32_t sample=(tri-16384)*4096;
     samples[2*i]=sample;samples[2*i+1]=sample;
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
