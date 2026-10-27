// CuteDisplay audio wiring bring-up (ESP32-S3, Arduino-ESP32 3.3.12).
// TEST ONLY: temporarily replaces S3 Brain firmware. Restore combined S3 firmware afterward.
// Do not run while a C5 OTA transfer is underway.
#include <Arduino.h>
#include <ESP_I2S.h>
#include <esp_heap_caps.h>

constexpr int PIN_BCLK = 41; // INMP441 SCK + MAX98357A BCLK
constexpr int PIN_WS   = 42; // INMP441 WS + MAX98357A LRC
constexpr int PIN_MIC  = 1;  // INMP441 SD
constexpr int PIN_AMP  = 2;  // MAX98357A DIN
constexpr uint32_t RATE = 16000;
constexpr size_t SAMPLES = RATE * 2; // 2 seconds
static I2SClass audio;
static int16_t *recorded = nullptr;
static int32_t raw[256];

void fail(const char* msg) {
  Serial.printf("[AUDIO] ERROR: %s (I2S error=%d)\n", msg, audio.lastError());
  while (true) delay(1000);
}

void setup() {
  Serial.begin(115200);
  delay(1500);
  Serial.println("\n[AUDIO] CuteDisplay S3 2-second microphone -> speaker test");
  Serial.println("[AUDIO] GPIO41 BCLK, GPIO42 WS, GPIO1 mic SD, GPIO2 amp DIN");
  Serial.println("[AUDIO] Quiet environment initially; keep speaker volume low.");
  recorded = (int16_t*)heap_caps_malloc(SAMPLES * sizeof(int16_t), MALLOC_CAP_8BIT);
  if (!recorded) fail("cannot allocate 64KB recording buffer");
  audio.setPins(PIN_BCLK, PIN_WS, -1, PIN_MIC);
  // INMP441 outputs 24 meaningful bits in a 32-bit slot.
  // L/R connected to GND selects left channel.
  if (!audio.begin(I2S_MODE_STD, RATE, I2S_DATA_BIT_WIDTH_32BIT,
                   I2S_SLOT_MODE_MONO, I2S_STD_SLOT_LEFT)) fail("mic RX init");
  Serial.println("[AUDIO] Recording now. Speak for 2 seconds.");
  size_t done = 0;
  int32_t peak = 0;
  while (done < SAMPLES) {
    const size_t count = min((size_t)256, SAMPLES - done);
    const size_t need = count * sizeof(int32_t);
    const size_t got = audio.readBytes((char*)raw, need);
    if (got != need) fail("short microphone read");
    for (size_t j = 0; j < count; ++j) {
      // Scale 24-bit microphone samples down to 16-bit, with conservative gain.
      int32_t sample = raw[j] >> 14;
      sample = constrain(sample, -32768, 32767);
      recorded[done++] = (int16_t)sample;
      int32_t magnitude = abs(sample);
      if (magnitude > peak) peak = magnitude;
    }
  }
  Serial.printf("[AUDIO] Recorded %u samples; peak=%ld/32767\n",
                (unsigned)done, (long)peak);
  audio.end();
  delay(150);
  audio.setPins(PIN_BCLK, PIN_WS, PIN_AMP, -1);
  if (!audio.begin(I2S_MODE_STD, RATE, I2S_DATA_BIT_WIDTH_16BIT,
                   I2S_SLOT_MODE_MONO, I2S_STD_SLOT_BOTH)) fail("amp TX init");
  Serial.println("[AUDIO] Playing your recording now.");
  const size_t expected = SAMPLES * sizeof(int16_t);
  const size_t sent = audio.write((const uint8_t*)recorded, expected);
  Serial.printf("[AUDIO] Sent %u/%u bytes to amplifier\n",
                (unsigned)sent, (unsigned)expected);
  delay(100);
  audio.end();
  free(recorded); recorded=nullptr;
  Serial.println("[AUDIO] Test complete. To repeat, press S3 Reset.");
}
void loop() { delay(1000); }
