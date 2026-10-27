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
inline void start() {
  if(running){Serial.println("[AUDIO] Already running");return;}
  running=true;
  if(xTaskCreatePinnedToCore(task,"audio_test",8192,nullptr,2,nullptr,0)!=pdPASS){
    running=false;
    Serial.println("[AUDIO] ERROR: could not start test task");
  }
}
} // namespace BrainAudioTest
