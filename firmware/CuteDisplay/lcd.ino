/*
 CuteDisplay 4.2 voice hardware loopback / no RSS - T-Display C5 / ESP32-C5
 Message display with animated mascot,
 brightness, live AXP2602 battery level (BLE 180F / 2A19).

 Commands on FFF0/FFF1:
  Text               = message mode
  B:75               = brightness
  C:0 / C:1 / C:2   = bunny / kitty / chiikawa

 Preserve board_config.h, and install LILYGO's axp2602.h library.
*/
#include <Arduino.h>
#include <Preferences.h>
#include <WiFi.h>
#include <WiFiServer.h>
#include "esp_wifi.h"
#include "esp_err.h"
#include "esp_heap_caps.h"
#include <lwip/sockets.h>
#include <lwip/inet.h>
#include <lwip/ip4_addr.h>
#include <IPAddress.h>
#include <Wire.h>
#include <cstring>
#include "board_config.h"
#include "axp2602.h"
#include "driver/spi_master.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_vendor.h"
#include "esp_lcd_st7789.h"
#include "esp_heap_caps.h"
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLESecurity.h>
#include <BLEUtils.h>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "esp_system.h"
#include "esp_idf_version.h"
#include "driver/i2s_std.h"

// Declare custom types before Arduino IDE auto-generated function prototypes.
struct Drink;
bool parseEntry(String entry, Drink &result);

#define PIN_CS 26
#define PIN_DC 8
#define PIN_RST 23
#define PIN_MOSI 9
#define PIN_SCLK 7
#define PIN_BL 25
#define BAT_SDA 2
#define BAT_SCL 3
#define PIN_USER_BUTTON 0 // LILYGO T-Display-C5 user button (GPIO0, active LOW)
#define PIN_VOICE_BUTTON 28 // BOOT/right button: short battery, hold voice loopback
#define LCD_W 320
#define LCD_H 170
#define MAX_CMD 96
#define MAX_GLYPHS 128
#define BLACK 0x0000
#define WHITE 0xFFFF
#define PINK 0xF81F
#define SOFTPINK 0xFBB2
#define YELLOW 0xFFE0
#define PANEL 0x18C5
#define DARK 0x1083

esp_lcd_panel_handle_t panel = nullptr;
esp_lcd_panel_io_handle_t panelIO = nullptr;
// Prefer QIO PSRAM for the indexed framebuffer to reserve internal RAM for Wi-Fi.
// Use compact one-byte-per-pixel indexed framebuffer (54,400 bytes).
// Palette entries preserve the original RGB565 theme/mascot colors.
uint8_t *pixels = nullptr;
bool frameInPSRAM=false;
uint16_t colorPalette[256] = {};
uint16_t paletteCount = 0;
uint16_t paletteHashKey[512] = {};
uint8_t paletteHashValue[512] = {};
uint8_t paletteHashValid[512] = {};
static uint8_t colorIndex(uint16_t color) {
  uint16_t bucket=(uint16_t)((uint32_t)color*2654435761UL>>23)&511;
  for(int probe=0;probe<512;probe++) {
    uint16_t slot=(bucket+probe)&511;
    if(!paletteHashValid[slot])break;
    if(paletteHashKey[slot]==color)return paletteHashValue[slot];
  }
  uint8_t index=0;
  if(paletteCount<256) {index=(uint8_t)paletteCount;colorPalette[paletteCount++]=color;}
  else {
    // Palette full: use the nearest already-recorded RGB565 shade.
    int best=INT32_MAX;
    const int r=(color>>11)&31,g=(color>>5)&63,b=color&31;
    for(int i=0;i<256;i++) {
      uint16_t p=colorPalette[i];
      int dr=r-((p>>11)&31),dg=g-((p>>5)&63),db=b-(p&31);
      int d=dr*dr*2+dg*dg+db*db*2;
      if(d<best){best=d;index=i;if(d==0)break;}
    }
  }
  for(int probe=0;probe<512;probe++) {
    uint16_t slot=(bucket+probe)&511;
    if(!paletteHashValid[slot]) {paletteHashValid[slot]=1;paletteHashKey[slot]=color;paletteHashValue[slot]=index;break;}
  }
  return index;
}
static inline uint16_t frameColor(size_t i) {return colorPalette[pixels[i]];}
static inline void frameSet(size_t i,uint16_t c) {pixels[i]=colorIndex(c);}
// Internal-memory DMA strip for SPI transmissions; no PSRAM needed.
static uint16_t *lcdDmaStrip = nullptr;
// A PSRAM copy of the last transmitted indexed frame. The palette must also
// match: identical indexes with different palette entries are NOT the same LCD image.
static uint8_t *lastSentFrame = nullptr;
static uint16_t lastSentPalette[256] = {};
static uint16_t lastSentPaletteCount = 0;
static bool lastSentValid = false;
// Last frame is indexed. Compare RGB565 colors, not raw indexes, so palette
// index remapping between frames doesn't force unnecessary LCD writes.
// Compute a tight horizontal transfer bounding box for each eight-row strip.
// The previous frame is indexed in PSRAM; compare actual RGB565 colors because
// palette indexes can be remapped between frames.
static bool dirtyStripSpan(int y, int rows, int &left, int &right) {
 if(!lastSentValid || !lastSentFrame) { left=0;right=LCD_W;return true; }
 left=LCD_W;right=0;
 for(int r=0;r<rows;r++) {
  const size_t base=(size_t)(y+r)*LCD_W;
  for(int x=0;x<LCD_W;x++) {
   const size_t i=base+x;
   const uint8_t oldIdx=lastSentFrame[i];
   if(oldIdx>=lastSentPaletteCount || colorPalette[pixels[i]]!=lastSentPalette[oldIdx]) {
    if(x<left)left=x;
    if(x>=right)right=x+1;
   }
  }
 }
 return right>left;
}

static constexpr int LCD_STRIP_ROWS = 8; // Same 320x170 frames, half the internal DMA allocation
SemaphoreHandle_t lcdSemaphore = nullptr;
QueueHandle_t commandQueue = nullptr;
AXP2602 axp;
Preferences displayPrefs;
BLECharacteristic *batteryCharacteristic = nullptr;
BLECharacteristic *powerCharacteristic = nullptr;
bool lcdReady = false;
bool pwmReady = false;
bool batteryReady = false;
volatile bool bleConnected = false;
String wifiSSID="", wifiPassword="";
bool wifiEnabled=false, wifiLastConnected=false;
// Wi-Fi shutdown is direct; the RSS/HTTPS worker has been removed.
static volatile bool wifiShutdownPending=false;
static bool wifiPowerCheckPending=false;
static unsigned long wifiPowerCheckAt=0;
bool wifiUseDHCP=true;
String staticIP="",staticMask="",staticGateway="",staticDNS="";
BLECharacteristic *networkCharacteristic=nullptr;
unsigned long nextNetworkTelemetry=0;
bool wifiOnline();
// Opt-in local-only authenticated TCP transport. Wi-Fi is never enabled by
// this feature; the iPhone must already share the ESP32's reachable network.
static constexpr uint16_t LAN_PORT=8848;
static WiFiServer lanServer(LAN_PORT);
static WiFiClient lanClient;
static bool lanListening=false, lanAuthed=false;
static char lanBuffer[176]={0};
static size_t lanBuffered=0;
static uint32_t lanLastActivity=0;
static String lanSecret;
static float lanVolts=0.0f,lanAmps=0.0f;
static int lanTemp=0,lanHealth=0;
static void updateLAN();
static void stopLAN();
void processCommand(String cmd);
static void loadLANSecret(){
 Preferences p;
 if(!p.begin("cute-lan",false))return;
 lanSecret=p.getString("token","");
 if(lanSecret.length()!=32){
  char key[33];
  for(int i=0;i<4;i++)sprintf(key+i*8,"%08lx",(unsigned long)esp_random());
  key[32]=0;lanSecret=key;
  p.putString("token",lanSecret);
 }
 p.end();
}
// Short notifications fit even BLE connections with a 23-byte MTU.
void networkReport(const String &entry){
 if(!networkCharacteristic || !bleConnected)return;
 networkCharacteristic->setValue(entry.c_str());
 if(bleConnected)networkCharacteristic->notify();
 delay(12); // Let the BLE controller transmit before replacing the value.
}
void sendNetworkField(String field){
 bool online=wifiOnline();
 field.toUpperCase();
 if(field=="LINK")networkReport(String("N:LINK:")+(online?"1":"0"));
 else if(field=="MODE")networkReport(String("N:MODE:")+(wifiUseDHCP?"DHCP":"STATIC"));
 else if(field=="IP")networkReport("N:IP:"+(online?WiFi.localIP().toString():String("-")));
 else if(field=="MASK")networkReport("N:MASK:"+(online?WiFi.subnetMask().toString():String("-")));
 else if(field=="GW")networkReport("N:GW:"+(online?WiFi.gatewayIP().toString():String("-")));
 else if(field=="DNS")networkReport("N:DNS:"+(online?WiFi.dnsIP().toString():String("-")));
 else if(field=="RSSI")networkReport("N:RSSI:"+(online?String(WiFi.RSSI()):String("0")));
 else if(field=="SSID"){
  String name=online?WiFi.SSID():wifiSSID;
  // SSID is UTF-8: encode bytes in independently addressed hex chunks.
  for(int i=0;i<(int)name.length() && i<32;i+=6){
   String hex="";
   for(int j=i;j<i+6 && j<(int)name.length();j++){
    char buf[3];sprintf(buf,"%02X",(unsigned char)name[j]);hex+=buf;
   }
   networkReport("N:S"+String(i/6)+":"+hex);
  }
  networkReport("N:END");
 }
}
void sendNetworkTelemetry(){
 if(!bleConnected)return; // No need to build BLE packets while no phone listens.
 // Only link changes are periodic. All other fields are explicitly requested
 // by the iPhone one at a time to avoid overflowing the BLE notify queue.
 sendNetworkField("LINK");
}
static uint16_t icmpChecksum(const uint8_t *buf,int len){
 uint32_t sum=0; int i=0;
 while(i+1<len){sum+=(uint16_t)((buf[i]<<8)|buf[i+1]);i+=2;}
 if(i<len)sum+=(uint16_t)(buf[i]<<8);
 while(sum>>16)sum=(sum&0xffff)+(sum>>16);
 return (uint16_t)~sum;
}
// On-device ICMP gateway health check. Do not notify the phone or
// print repetitive diagnostics; retain a stable status for the top-right icon.
bool gatewayReachable=false;
bool gatewayProbeKnown=false;
uint32_t gatewayLatencyMs=0; // Last successful ICMP RTT; meaningful only when gatewayReachable is true
unsigned long nextGatewayProbe=0;
static constexpr unsigned long GATEWAY_PROBE_PERIOD_MS=20000UL;
bool pingDefaultGateway(){
 if(!wifiOnline())return false;
 IPAddress ip=WiFi.gatewayIP();
 if(ip==IPAddress(0,0,0,0))return false;
 int fd=socket(AF_INET,SOCK_RAW,IPPROTO_ICMP);
 if(fd<0)return false;
 timeval tv={0,350000};
 setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&tv,sizeof(tv));
 sockaddr_in dst={};dst.sin_family=AF_INET;dst.sin_addr.s_addr=(uint32_t)ip;
 uint8_t pkt[16]={8,0,0,0,0x43,0x44,0,0,'C','u','t','e','G','a','t','e'};
 uint16_t chk=icmpChecksum(pkt,sizeof(pkt));pkt[2]=chk>>8;pkt[3]=chk&0xff;
 bool ok=false;
 uint32_t startUs=micros();
 if(sendto(fd,pkt,sizeof(pkt),0,(sockaddr*)&dst,sizeof(dst))>=0){
  uint8_t rx[128];
  int n=recv(fd,rx,sizeof(rx),0);
  if(n>0){
   int off=(rx[0]&0x0f)*4;
   if(n>=off+8 && rx[off]==0 && rx[off+4]==0x43 && rx[off+5]==0x44){
    ok=true;
    gatewayLatencyMs=(micros()-startUs+500UL)/1000UL;
   }
  }
 }
 close(fd);
 return ok;
}

unsigned long nextWiFiAttempt=0, lastStatusRedraw=0;
bool lastDisplayedBle=false;
// Give BLE and the LCD time to initialize before Wi-Fi uses the radio.
unsigned long wifiBootReadyAt=0;
bool wifiAttemptActive=false;
bool wifiInitFailed=false;
unsigned long wifiAttemptStarted=0;
const unsigned long WIFI_RETRY_MS=120000UL;
const unsigned long WIFI_CONNECT_TIMEOUT_MS=12000UL;
bool wifiOnline(){return wifiEnabled && WiFi.getMode()!=WIFI_OFF && WiFi.status()==WL_CONNECTED;}
void updateWiFi(unsigned long now){
 if(!wifiEnabled || wifiShutdownPending || wifiSSID.isEmpty() || wifiInitFailed)return;
 if((int32_t)(now-wifiBootReadyAt)<0)return;
 if(wifiOnline()){wifiAttemptActive=false;return;}
 if(wifiAttemptActive){
  if(now-wifiAttemptStarted>=WIFI_CONNECT_TIMEOUT_MS){
   WiFi.disconnect(false,false);
   wifiAttemptActive=false;
   nextWiFiAttempt=now+WIFI_RETRY_MS;
   Serial.println("[WIFI] Timed out; radio retry postponed");
  }
  return;
 }
 if((int32_t)(now-nextWiFiAttempt)<0)return;
 if(WiFi.getMode()!=WIFI_STA && !WiFi.mode(WIFI_STA)){
  wifiInitFailed=true;wifiEnabled=false;wifiAttemptActive=false;
  Serial.printf("[WIFI] Radio init failed (memory); internal free=%u largest=%u, PSRAM=%u. Auto-retry disabled.\n",
   (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
   (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL),
   (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
  return;
 }
 if(!wifiUseDHCP){
  IPAddress ip,mask,gw,dns;
  if(ip.fromString(staticIP)&&mask.fromString(staticMask)&&gw.fromString(staticGateway)&&dns.fromString(staticDNS))
   WiFi.config(ip,gw,mask,dns);
  else {Serial.println("[WIFI] Invalid saved static address; using DHCP");WiFi.config(IPAddress(0,0,0,0),IPAddress(0,0,0,0),IPAddress(0,0,0,0));}
 }else WiFi.config(IPAddress(0,0,0,0),IPAddress(0,0,0,0),IPAddress(0,0,0,0));
 // Modem sleep lets the Wi-Fi radio doze between access-point beacons.
 // The CPU, BLE, gateway probe and LCD keep running as before.
 WiFi.setAutoReconnect(false); // App owns reconnect timing; no autonomous retry after OFF.
 WiFi.setSleep(true);
 WiFi.begin(wifiSSID.c_str(),wifiPassword.c_str());
 wifiAttemptActive=true;
 wifiAttemptStarted=now;
 nextWiFiAttempt=now+WIFI_RETRY_MS;
 Serial.println("[WIFI] Connection attempt started");
}

int batteryLevel = -1;
unsigned long lastBatteryRead = 0;
// On-device battery notifications, drawn temporarily over the normal mode.
const unsigned long BATTERY_CARD_MS = 6000UL;
const unsigned long CHARGE_NOTICE_MS = 3000UL;
const unsigned long BATTERY_SAMPLE_MS = 2000UL;
unsigned long batteryOverlayUntil = 0;
unsigned long chargeNoticeUntil = 0;
unsigned long fullNoticeUntil = 0;
unsigned long lowNoticeUntil = 0;
bool fullBatteryNotified = false;
int deviceLowBatteryThreshold = 20;
bool lowBatteryWarningSent = false;
float observedDischargeMinutesPerPercent = 0.0f;
float dischargeDurationMinutes = 0.0f;
int lastDischargeSOC = -1;
unsigned long lastDischargeObservation = 0;
unsigned long lastBatteryOverlayFrame = 0;

// Lightweight adaptive battery estimates. The AXP2602 remains the primary
// source of SOC/current/voltage; only timing statistics are learned.
// NVS checkpoints are intentionally rare to reduce writes and flash wear.
static float batteryLearnDischarge = 0.0f; // minutes / 1% SOC
static float batteryLearnCharge = 0.0f;
static uint16_t batteryLearnDischargeN = 0;
static uint16_t batteryLearnChargeN = 0;
static int batteryLearnPrevSOC = -1;
static uint32_t batteryLearnPrevMs = 0;
static uint32_t batteryLearnElapsedMs = 0;
static int batteryLearnMode = 0; // -1 discharge, +1 charge, 0 unknown
static uint32_t batteryLearnLastSaveMs = 0;
static uint8_t batteryLearnUnsaved = 0;
static float batterySmoothedCurrent = 0.0f;
static bool batteryCurrentReady = false;
static float batteryDisplaySOC = -1.0f;
static bool batteryEstimateReady = false;
static uint16_t batteryStableEmpty = 0xFFFF;
static uint16_t batteryStableFull = 0xFFFF;
static uint32_t batteryLastEstimateMs = 0;
static void loadBatteryLearning(){
 Preferences p;
 if(!p.begin("cute-batt",true))return;
 batteryLearnDischarge=p.getFloat("disRate",0.0f);
 batteryLearnCharge=p.getFloat("chgRate",0.0f);
 batteryLearnDischargeN=p.getUShort("disN",0);
 batteryLearnChargeN=p.getUShort("chgN",0);
 p.end();
 if(!isfinite(batteryLearnDischarge)||batteryLearnDischarge<0.5f||batteryLearnDischarge>180.0f){batteryLearnDischarge=0; batteryLearnDischargeN=0;}
 if(!isfinite(batteryLearnCharge)||batteryLearnCharge<0.5f||batteryLearnCharge>180.0f){batteryLearnCharge=0; batteryLearnChargeN=0;}
}
static void saveBatteryLearning(uint32_t now){
 if(batteryLearnUnsaved<3 || (uint32_t)(now-batteryLearnLastSaveMs)<1800000UL)return;
 Preferences p;
 if(!p.begin("cute-batt",false))return;
 p.putFloat("disRate",batteryLearnDischarge);
 p.putFloat("chgRate",batteryLearnCharge);
 p.putUShort("disN",batteryLearnDischargeN);
 p.putUShort("chgN",batteryLearnChargeN);
 p.end();
 batteryLearnLastSaveMs=now; batteryLearnUnsaved=0;
}
static void updateBatteryEstimate(int rawSOC,float amps,bool charging,uint16_t gaugeEmpty,uint16_t gaugeFull,uint32_t now){
 // Suppress noise; this is NOT an absolute battery-capacity calibration.
 if(!batteryCurrentReady){ batterySmoothedCurrent=amps; batteryCurrentReady=true; }
 else batterySmoothedCurrent=0.85f*batterySmoothedCurrent+0.15f*amps;
 if(batteryDisplaySOC<0)batteryDisplaySOC=(float)rawSOC;
 else {
  // Limit display jitter but catch large real gauge adjustments promptly.
  float diff=(float)rawSOC-batteryDisplaySOC;
  if(fabsf(diff)>=5.0f)batteryDisplaySOC=(float)rawSOC;
  else batteryDisplaySOC+=constrain(diff,-0.34f,0.34f);
 }
 const int mode=(charging && amps>0.035f)?1:(!charging && amps<-0.025f)?-1:0;
 if(mode!=batteryLearnMode){
  batteryLearnMode=mode; batteryLearnPrevSOC=rawSOC;
  batteryLearnElapsedMs=0; batteryLearnPrevMs=now;
  batteryEstimateReady=false;
 }else if(mode!=0 && batteryLearnPrevMs){
  uint32_t dt=now-batteryLearnPrevMs;
  batteryLearnPrevMs=now;
  // Ignore large gaps (e.g. long blocking network operation or wraparound).
  if(dt<15000UL)batteryLearnElapsedMs+=dt;
  const int delta=mode==1?rawSOC-batteryLearnPrevSOC:batteryLearnPrevSOC-rawSOC;
  if(delta>=1 && delta<=3){
   float minPerPercent=(batteryLearnElapsedMs/60000.0f)/delta;
   // Reject gauge jitter, short transitions and implausible learning samples.
   if(batteryLearnElapsedMs>=45000UL && minPerPercent>=0.5f && minPerPercent<=180.0f){
    float &rate=mode==1?batteryLearnCharge:batteryLearnDischarge;
    uint16_t &count=mode==1?batteryLearnChargeN:batteryLearnDischargeN;
    rate=(count==0)?minPerPercent:(0.85f*rate+0.15f*minPerPercent);
    if(count<65000)count++;
    if(batteryLearnUnsaved<255)batteryLearnUnsaved++;
    saveBatteryLearning(now);
   }
   batteryLearnPrevSOC=rawSOC; batteryLearnElapsedMs=0;
  }else if(delta<0 || delta>3 || batteryLearnElapsedMs>21600000UL){
   batteryLearnPrevSOC=rawSOC; batteryLearnElapsedMs=0;
  }
 }
 // Estimation from learned elapsed time per SOC percent. Gauge time-to-X is
 // used when the observed history is insufficient. Never invent a valid ETA.
 uint16_t predicted=0xFFFF;
 if(mode==-1 && batteryLearnDischargeN>=2 && rawSOC>0){
  float minLeft=(rawSOC * batteryLearnDischarge);
  if(minLeft>=1.0f && minLeft<65535.0f)predicted=(uint16_t)(minLeft+0.5f);
 }else if(mode==1 && batteryLearnChargeN>=2 && rawSOC<100){
  float minLeft=((100-rawSOC)*batteryLearnCharge);
  if(minLeft>=1.0f && minLeft<65535.0f)predicted=(uint16_t)(minLeft+0.5f);
 }
 uint16_t raw=(mode==-1)?gaugeEmpty:(mode==1)?gaugeFull:0xFFFF;
 if(raw==0 || raw==0xFFFF || raw>28800)raw=0xFFFF;
 uint16_t target=predicted!=0xFFFF?predicted:raw;
 uint16_t &out=(mode==1)?batteryStableFull:batteryStableEmpty;
 if(mode==0){batteryStableEmpty=0xFFFF; batteryStableFull=0xFFFF; return;}
 if(mode==1)batteryStableEmpty=0xFFFF;else batteryStableFull=0xFFFF;
 if(target==0xFFFF){out=0xFFFF; batteryEstimateReady=false;return;}
 // Smooth minutes gently; avoid large jumps after connecting the charger.
 if(!batteryEstimateReady || out==0xFFFF){out=target;batteryEstimateReady=true;}
 else {
  int diff=(int)target-(int)out;
  int step=constrain(diff,-3,3);
  if(diff!=0 && step==0)step=diff>0?1:-1;
  out=(uint16_t)constrain((int)out+step,0,65534);
 }
 batteryLastEstimateMs=now;
}
bool batteryCharging = false;
bool batteryStatusInitialized = false;
uint8_t chargingPositiveSamples = 0;
uint8_t chargingNegativeSamples = 0;
uint16_t remainingMinutes = 0xFFFF;
uint16_t fullMinutes = 0xFFFF;
bool userButtonLastRaw = HIGH;
bool userButtonStable = HIGH;
unsigned long userButtonChangedAt = 0;
unsigned long userButtonPressedAt = 0;
bool userButtonLongHandled = false;
const unsigned long WIFI_HOLD_MS = 1400UL;
unsigned long wifiToastUntil = 0;
bool wifiToastEnabled = false;

unsigned long lastScroll = 0;
int mascot = 1;
int theme = 0;
int brightness = 75;
String message = "こんにちわ";
bool bubbleEnabled = false; // Normal scrolling remains the default.
bool bubbleTypewriter = true;
size_t revealedCharacters = 0;
unsigned long lastBubbleReveal = 0;
const unsigned long BUBBLE_LETTER_MS = 135;
// Right button: short press is intentionally inert; hold 1.4s for audio loopback.
static bool voiceButtonRaw=HIGH;
static bool voiceButtonStable=HIGH;
static unsigned long voiceButtonChangedAt=0;
static unsigned long voiceButtonPressedAt=0;
static bool voiceButtonLongHandled=false;
static volatile bool voiceBusy=false;
static constexpr uint32_t VOICE_HOLD_MS=1400;
static constexpr uint32_t VOICE_SAMPLE_RATE=16000;
static constexpr uint32_t VOICE_RECORD_MS=2000;
// Four exposed pins reserved for the shared-clock full-duplex I2S bus.
// Current LILYGO T-Display-C5 breadboard audio wiring (ELEGOO 830 points):
// INMP441: VDD=3V3, GND=GND, SCK/BCLK=GPIO1, WS=GPIO4,
//          SD/DOUT=GPIO5, L/R=GND (left channel).
// MAX98357A: VIN=5V only after checking available USB/VBUS current,
//            GND=GND, BCLK=GPIO1, LRC=GPIO4, DIN=GPIO6.
// Speaker: connect only to amplifier SPK+ and SPK- (never to GND).
// GPIO1/GPIO4 clocks are shared; GPIO5 mic input and GPIO6 amp output
// must NOT be connected together. USB power rail and 3V3 must not be bridged.
// This is Phase 1 sequential local loopback, not AI streaming.
// For the top/bottom header positions and rail safety, see:
// docs/hardware/lilygo-c5-audio-breadboard.md
static constexpr gpio_num_t VOICE_BCLK=GPIO_NUM_1;
static constexpr gpio_num_t VOICE_WS=GPIO_NUM_4;
static constexpr gpio_num_t VOICE_MIC_DIN=GPIO_NUM_5;
static constexpr gpio_num_t VOICE_AMP_DOUT=GPIO_NUM_6;

bool scrolling = false;
int scrollX = 0;
// User-controlled appearance. Defaults restored on every board reboot.
bool mascotVisible = true;
int mascotPercent = 100; // 40, 60, 80, 100
int messageSize = 3;    // 1..5; Japanese scale 1..4
int mood = 1;          // 0 neutral, 1 happy, 2 sad, 3 angry, 4 hungry, 5 sleepy, 6 excited, 7 shy
// Random, optional short surprise performances. Preserves the selected mood.
bool surprisesEnabled = true;
uint8_t surpriseAction = 0; // 0 idle; 1..12 animated right-panel performances
unsigned long surpriseStart = 0;
unsigned long nextSurpriseAt = 0;
const unsigned long SURPRISE_DURATION_MS = 4100;
int accessoryStyle=0, objectMode=0, manualObject=0, animationFrequency=1, animationIntensity=1;
bool personalityEnabled=true;
const uint8_t moodActions[8][6]={
 {1,2,3,4,5,10},{2,5,6,7,9,11},{1,4,8,10,11,8},
 {3,4,10,1,3,4},{2,4,5,10,6,4},{8,8,4,1,8,4},
 {3,5,6,9,11,7},{7,12,12,6,4,12}
};
int choosePerformance(bool personality){
 if(personalityEnabled && personality){
  const uint8_t signature[6][3]={{2,9,7},{7,6,12},{1,12,4},
                                  {2,8,11},{8,2,4},{4,10,5}};
  return signature[constrain(mascot,0,5)][esp_random()%3];
 }
 return moodActions[constrain(mood,0,7)][esp_random()%6];
}
void scheduleNextSurprise(unsigned long now) {
 unsigned long wait=animationFrequency==0?70000UL:animationFrequency==2?15000UL:40000UL;
 unsigned long spread=animationFrequency==0?60000UL:animationFrequency==2?22000UL:50000UL;
 nextSurpriseAt=now+wait+(esp_random()%spread);
}
// Gently changing movement signatures. Never allow full-screen roaming.
int personalityPose=0;
unsigned long poseUntil=0;
unsigned long nextPoseAt=0;
bool stateDirty=false;
unsigned long stateDirtyAt=0;
void noteStateChanged(){stateDirty=true;stateDirtyAt=millis();}
void updatePersonalityPose(unsigned long now){
 if(!personalityEnabled || !mascotVisible){personalityPose=0;return;}
 if(personalityPose && (int32_t)(now-poseUntil)>=0){personalityPose=0;}
 if(!personalityPose && (int32_t)(now-nextPoseAt)>=0){
  // Mood-aware: sleepy/sad move much less often than excited/happy.
  uint32_t roll=esp_random()%100;
  if(mood==5 || mood==2)personalityPose=roll<75?1:2;
  else if(mood==3)personalityPose=roll<60?3:2;
  else if(mood==7)personalityPose=roll<65?1:4;
  else personalityPose=1+(esp_random()%4);
  poseUntil=now+(mood==5?2700UL:1400UL)+(esp_random()%1700UL);
  nextPoseAt=poseUntil+(mood==5?18000UL:mood==2?12000UL:mood==6?2500UL:6000UL)+(esp_random()%9000UL);
 }
}
uint8_t animPhase = 0;
unsigned long lastMascotAnimation = 0;
const unsigned long MASCOT_ANIMATION_MS = 220;
// Expressive eyes: independent, occasional glances with one-pixel smoothing.
int gazeX=0, gazeY=0, targetGazeX=0, targetGazeY=0;
unsigned long nextGazeAt=0;
void updateExpressiveEyes(unsigned long now) {
 if(!nextGazeAt || (int32_t)(now-nextGazeAt)>=0) {
  const int8_t positions[9][2]={{0,0},{-3,0},{3,0},{-2,-2},{2,-2},
                                 {0,-3},{-3,1},{3,1},{0,1}};
  int choice=esp_random()%9;
  targetGazeX=positions[choice][0];
  targetGazeY=positions[choice][1];
  nextGazeAt=now+1800UL+(esp_random()%3600UL);
 }
 if(gazeX<targetGazeX)++gazeX;
 else if(gazeX>targetGazeX)--gazeX;
 if(gazeY<targetGazeY)++gazeY;
 else if(gazeY>targetGazeY)--gazeY;
}
uint16_t *mascotBackup = nullptr; // 33,320 bytes moved from internal BSS to PSRAM
int mascotPanelWidth() { return mascotVisible ? max(40, 98 * mascotPercent / 100) : 0; }
int contentRight() { return LCD_W - mascotPanelWidth() - (mascotVisible ? 3 : 0); }
int jpMessageScale() { return max(1, min(4, messageSize)); }
int asciiMessageScale() { return max(1, min(6, messageSize + 1)); }
void drawBatteryOverlay();
void textAt(const String &s,int x,int y,int scale,uint16_t color);
void drawConnectivityHUD(){
 // Fixed tiny status HUD. Draw over the existing upper-right mascot area,
 // with no changes to character geometry or text-area margins.
 const int x=261,y=2;
 rect(x-2,0,61,16,BLACK);
 const uint16_t bt=bleConnected?0x07FF:0x7BEF;
 line(x+5,y,x+5,y+10,bt);
 line(x+5,y,x+10,y+3,bt);line(x+10,y+3,x+2,y+8,bt);
 line(x+5,y,x+10,y+8,bt);line(x+10,y+8,x+2,y+3,bt);
 const int wx=x+14;
 const uint16_t wc=!wifiOnline()?0x7BEF:(!gatewayProbeKnown||gatewayReachable?0x07E0:0xFFE0);
 line(wx,y+3,wx+5,y,wc);line(wx+5,y,wx+10,y+3,wc);
 line(wx+2,y+6,wx+5,y+4,wc);line(wx+5,y+4,wx+8,y+6,wc);
 oval(wx+5,y+9,1,1,wc);
 if(!wifiOnline())line(wx+1,y+10,wx+10,y+1,0xF800);
 // Always show SOC, charging or discharging. Green indicates charging.
 String soc=batteryLevel>=0 ? String(constrain(batteryLevel,0,100))+"%" : "--%";
 textAt(soc,wx+13,y+2,1,batteryCharging?0x07E0:WHITE);
}

void drawMessage();
void redrawCurrent() { drawMessage(); }

// 25 accent themes. Outside the bubble stays pure black; the bubble is light.
// RGB565 values matched to the iPhone themeColors array (same 0..24 index).
uint16_t themeColor() {
 static const uint16_t palette[25] = {
  0xFAD7, 0x07FF, 0x07E0, 0xFFE0, 0x8010,
  0xFBD3, 0x001F, 0xFD8F, 0x07E0, 0xF800,
  0xBF9F, 0xFC00, 0xCC1F, 0xFE49, 0x5DFF,
  0xFB6C, 0x3F39, 0x2F31, 0x92FF, 0xFA1D,
  0xFD66, 0x84BF, 0xEF5F, 0xE98A, 0x97E8
 };
 return palette[constrain(theme,0,24)];
}
// Only the accent color changes with the chosen theme.
uint16_t themeBackground() { return BLACK; }
uint16_t themeMascotBackground() { return BLACK; }
// Make a softly tinted, bright speech-bubble fill from the active accent.
// Keep the outside black and use dark lettering inside the light bubble.
uint16_t themeBubbleFill() {
 uint16_t c = themeColor();
 int r = (c >> 11) & 31;
 int g = (c >> 5) & 63;
 int b = c & 31;
 r = (r + 31 * 3) / 4;
 g = (g + 63 * 3) / 4;
 b = (b + 31 * 3) / 4;
 return (uint16_t)((r << 11) | (g << 5) | b);
}
struct CJKGlyph { uint32_t code; uint8_t bits[32]; };
CJKGlyph *glyphCache = nullptr; // cached glyph bitmap data in PSRAM
int glyphCount = 0;
// Smooth 24x24 glyphs: 2-bit coverage per pixel (144 bytes each).
// Old monochrome G: packets continue to work as a fallback.
#define MAX_SMOOTH_GLYPHS 48
struct SmoothGlyph { uint32_t code; uint8_t coverage[144]; };
SmoothGlyph *smoothGlyphs = nullptr; // antialiased glyphs in PSRAM
uint8_t smoothCount=0;
uint8_t smoothStaging[144]={0};
uint32_t smoothStagingCode=0;
uint8_t smoothStagingMask=0;
int findSmoothGlyph(uint32_t cp){
 for(int i=0;i<smoothCount;i++)if(smoothGlyphs[i].code==cp)return i;
 return -1;
}


uint32_t decodeUTF8(const String &s, int &offset) {
 if (offset >= (int)s.length()) return 0;
 uint8_t a = (uint8_t)s[offset++];
 if (a < 0x80) return a;
 int extra = (a >= 0xF0 && a <= 0xF4) ? 3 :
             (a >= 0xE0 && a <= 0xEF) ? 2 :
             (a >= 0xC2 && a <= 0xDF) ? 1 : 0;
 if (extra == 0) return '?';
 uint32_t value = a & (extra == 1 ? 0x1F : extra == 2 ? 0x0F : 0x07);
 while(extra--) {
  if(offset >= (int)s.length()) return '?';
  uint8_t b = (uint8_t)s[offset++];
  if((b & 0xC0) != 0x80) return '?';
  value = (value << 6) | (b & 0x3F);
 }
 return value;
}
int utfWidth(uint32_t cp, int asciiScale, int jpScale) {
 return cp < 128 ? 6*asciiScale : 16*jpScale;
}
int richWidth(const String &s, int asciiScale, int jpScale) {
 int maxWidth=0, current=0;
 for(int i=0;i<(int)s.length();){
  uint32_t cp=decodeUTF8(s,i);
  if(cp=='\r')continue;
  if(cp=='\n'){maxWidth=max(maxWidth,current);current=0;continue;}
  if(cp=='\t')current+=24*asciiScale;
  else current+=utfWidth(cp,asciiScale,jpScale);
 }
 return max(maxWidth,current);
}
int richLineCount(const String &s) {
 int count=1;
 for(int i=0;i<(int)s.length();i++)if(s[i]=='\n')count++;
 return count;
}
void setGlyph(uint32_t cp, const uint8_t *bits) {
 for(int i=0; i<glyphCount; i++) {
  if(glyphCache[i].code == cp) { memcpy(glyphCache[i].bits,bits,32); return; }
 }
 if(glyphCount >= MAX_GLYPHS) { Serial.println("[GLYPH] Cache full"); return; }
 glyphCache[glyphCount].code = cp;
 memcpy(glyphCache[glyphCount].bits,bits,32);
 glyphCount++;
}
void saveDisplayState(){
 // The news bubble temporarily swaps the active message/mode. Never persist
 // this transient preview in place of the user's own display settings.
 const String &persistentMessage = message;
 const bool persistentBubble = bubbleEnabled;
 displayPrefs.begin("cute-display",false);
 displayPrefs.putUChar("v",1);
 displayPrefs.putUChar("theme",theme);
 displayPrefs.putUChar("mascot",mascot);
 displayPrefs.putUChar("mood",mood);
 displayPrefs.putUChar("bright",brightness);
 displayPrefs.putBool("visible",mascotVisible);
 displayPrefs.putUChar("scale",mascotPercent);
 displayPrefs.putUChar("font",messageSize);
 displayPrefs.putBool("bubble",persistentBubble);
 displayPrefs.putBool("typing",bubbleTypewriter);
 displayPrefs.putBool("surprise",surprisesEnabled);
 displayPrefs.putUChar("acc",accessoryStyle);
 displayPrefs.putUChar("objmode",objectMode);
 displayPrefs.putUChar("object",manualObject);
 displayPrefs.putUChar("freq",animationFrequency);
 displayPrefs.putUChar("intense",animationIntensity);
 displayPrefs.putBool("person",personalityEnabled);
 displayPrefs.putUChar("low",deviceLowBatteryThreshold);
 displayPrefs.putString("message",persistentMessage.substring(0,96));
 // Preserve dynamic 16x16 Japanese glyphs. Previously the text survived a
 // restart but its bitmap glyphs disappeared, leaving an empty message.
 displayPrefs.putUChar("smoothnum",smoothCount);
 if(smoothCount>0)displayPrefs.putBytes("smooth",smoothGlyphs,(size_t)smoothCount*sizeof(SmoothGlyph));
 displayPrefs.putUChar("glyphnum",(uint8_t)glyphCount);
 if(glyphCount>0)
  displayPrefs.putBytes("glyphs",glyphCache,(size_t)glyphCount*sizeof(CJKGlyph));
 displayPrefs.end();stateDirty=false;
 Serial.println("[STATE] Saved to NVS");
}
void loadDisplayState(){
 displayPrefs.begin("cute-display",true);
 if(displayPrefs.getUChar("v",0)!=1){displayPrefs.end();return;}
 theme=constrain((int)displayPrefs.getUChar("theme",0),0,24);
 mascot=constrain((int)displayPrefs.getUChar("mascot",1),0,5);
 mood=constrain((int)displayPrefs.getUChar("mood",1),0,7);
 brightness=constrain((int)displayPrefs.getUChar("bright",75),0,100);
 mascotVisible=displayPrefs.getBool("visible",true);
 mascotPercent=displayPrefs.getUChar("scale",100);
 if(mascotPercent!=40&&mascotPercent!=60&&mascotPercent!=80&&mascotPercent!=100)mascotPercent=100;
 messageSize=constrain((int)displayPrefs.getUChar("font",3),1,5);
 bubbleEnabled=displayPrefs.getBool("bubble",false);
 bubbleTypewriter=displayPrefs.getBool("typing",true);
 surprisesEnabled=displayPrefs.getBool("surprise",true);
 accessoryStyle=constrain((int)displayPrefs.getUChar("acc",0),0,7);
 objectMode=constrain((int)displayPrefs.getUChar("objmode",0),0,1);
 manualObject=constrain((int)displayPrefs.getUChar("object",0),0,7);
 animationFrequency=constrain((int)displayPrefs.getUChar("freq",1),0,2);
 animationIntensity=constrain((int)displayPrefs.getUChar("intense",1),0,2);
 personalityEnabled=displayPrefs.getBool("person",true);
 deviceLowBatteryThreshold=displayPrefs.getUChar("low",20);
 message=displayPrefs.getString("message","こんにちわ");
 // An empty/corrupt NVS string must not leave the display without text.
 if(message.isEmpty())message="こんにちわ";
 Serial.printf("[STATE] Restored message: %u bytes, bubble=%d\n",
               (unsigned)message.length(),bubbleEnabled?1:0);
 displayPrefs.end();
 Serial.println("[STATE] Restored from NVS");
}

void loadPersistedGlyphs(){
 displayPrefs.begin("cute-display",true);
 int saved=displayPrefs.getUChar("glyphnum",0);
 size_t size=displayPrefs.getBytesLength("glyphs");
 if(saved>0 && saved<=MAX_GLYPHS && size==(size_t)saved*sizeof(CJKGlyph)){
  // Read into a local temporary heap allocation to avoid corrupting startup
  // glyphs if a partially written NVS record is encountered.
  CJKGlyph *savedGlyphs=(CJKGlyph*)malloc(size);
  if(savedGlyphs && displayPrefs.getBytes("glyphs",savedGlyphs,size)==size){
   for(int i=0;i<saved;i++){
    if(savedGlyphs[i].code>=128 && savedGlyphs[i].code<=0x10FFFF)
     setGlyph(savedGlyphs[i].code,savedGlyphs[i].bits);
   }
   Serial.printf("[GLYPH] Restored %d bitmap glyphs\n",saved);
  }
  free(savedGlyphs);
 }
 displayPrefs.end();
}
void loadSmoothGlyphs(){
 displayPrefs.begin("cute-display",true);
 int saved=displayPrefs.getUChar("smoothnum",0);
 size_t bytes=displayPrefs.getBytesLength("smooth");
 if(saved>0 && saved<=MAX_SMOOTH_GLYPHS && bytes==(size_t)saved*sizeof(SmoothGlyph)){
  if(displayPrefs.getBytes("smooth",smoothGlyphs,bytes)==bytes){
   smoothCount=saved;
   Serial.printf("[FONT] Restored %d smooth glyphs\n",smoothCount);
  }
 }
 displayPrefs.end();
}
void installStartupGlyphs();


const uint8_t fontLetters[26][5] = {
 {126,17,17,17,126},{127,73,73,73,54},{62,65,65,65,34},
 {127,65,65,34,28},{127,73,73,73,65},{127,9,9,9,1},
 {62,65,73,73,122},{127,8,8,8,127},{0,65,127,65,0},
 {32,64,65,63,1},{127,8,20,34,65},{127,64,64,64,64},
 {127,2,12,2,127},{127,4,8,16,127},{62,65,65,65,62},
 {127,9,9,9,6},{62,65,81,33,94},{127,9,25,41,70},
 {70,73,73,73,49},{1,1,127,1,1},{63,64,64,64,63},
 {31,32,64,32,31},{127,32,24,32,127},{99,20,8,20,99},
 {3,4,120,4,3},{97,81,73,69,67}
};
const uint8_t fontDigits[10][5] = {
 {62,81,73,69,62},{0,66,127,64,0},{66,97,81,73,70},
 {33,65,69,75,49},{24,20,18,127,16},{39,69,69,69,57},
 {60,74,73,73,48},{1,113,9,5,3},{54,73,73,73,54},
 {6,73,73,41,30}
};

void pixel(int x,int y,uint16_t c) {
 if (!pixels || x<0 || x>=LCD_W || y<0 || y>=LCD_H) return;
 frameSet(y*LCD_W+x,c);
}
void rect(int x,int y,int w,int h,uint16_t c) {
 if (!pixels) return;
 for (int yy=max(0,y); yy<min(LCD_H,y+h); ++yy)
  for (int xx=max(0,x); xx<min(LCD_W,x+w); ++xx)
   frameSet(yy*LCD_W+xx,c);
}
void oval(int x,int y,int rx,int ry,uint16_t c) {
 if(rx<=0||ry<=0) return;
 for(int yy=-ry;yy<=ry;yy++) for(int xx=-rx;xx<=rx;xx++) {
  long a=(long)xx*xx*ry*ry;
  long b=(long)yy*yy*rx*rx;
  long r=(long)rx*rx*ry*ry;
  if(a+b<=r) pixel(x+xx,y+yy,c);
 }
}
void line(int x0,int y0,int x1,int y1,uint16_t c) {
 int dx=abs(x1-x0),sx=x0<x1?1:-1;
 int dy=-abs(y1-y0),sy=y0<y1?1:-1;
 int err=dx+dy;
 while(true){
  pixel(x0,y0,c); if(x0==x1&&y0==y1) break;
  int e=err*2;
  if(e>=dy){err+=dy;x0+=sx;}
  if(e<=dx){err+=dx;y0+=sy;}
 }
}
void glyph(int x,int y,char ch,int scale,uint16_t color) {
 uint8_t data[5]={0};
 if(ch>='a'&&ch<='z')ch-=32;
 if(ch>='A'&&ch<='Z')memcpy(data,fontLetters[ch-'A'],5);
 else if(ch>='0'&&ch<='9')memcpy(data,fontDigits[ch-'0'],5);
 else if(ch=='!')data[2]=0x5F;
 else if(ch=='.')data[2]=0x40;
 else if(ch==':')data[2]=0x36;
 else if(ch=='-')for(int k=0;k<5;k++)data[k]=8;
 else if(ch=='%'){data[0]=0x63;data[1]=0x13;data[2]=0x08;data[3]=0x64;data[4]=0x63;}
 else if(ch=='?'){data[0]=0x02;data[1]=0x01;data[2]=0x51;data[3]=0x09;data[4]=0x06;}
 else if(ch=='/'){data[0]=0x60;data[1]=0x10;data[2]=0x08;data[3]=0x04;data[4]=0x03;}
 else if(ch==','){data[1]=0x80;data[2]=0x60;}
 else if(ch=='\''){data[2]=0x07;}
 else if(ch=='"'){data[1]=0x07;data[3]=0x07;}
 else if(ch=='('){data[1]=0x1C;data[2]=0x22;data[3]=0x41;}
 else if(ch==')'){data[1]=0x41;data[2]=0x22;data[3]=0x1C;}
 else if(ch=='+'){data[0]=0x08;data[1]=0x08;data[2]=0x3E;data[3]=0x08;data[4]=0x08;}
 else if(ch=='='){data[0]=0x14;data[1]=0x14;data[2]=0x14;data[3]=0x14;data[4]=0x14;}
 else if(ch=='_'){for(int k=0;k<5;k++)data[k]=0x40;}
 else if(ch=='#'){data[0]=0x14;data[1]=0x7F;data[2]=0x14;data[3]=0x7F;data[4]=0x14;}
 else if(ch==';'){data[1]=0x80;data[2]=0x36;}
 else if(ch=='&'){data[0]=0x36;data[1]=0x49;data[2]=0x55;data[3]=0x22;data[4]=0x50;}
 else if(ch=='@'){data[0]=0x3E;data[1]=0x41;data[2]=0x5D;data[3]=0x55;data[4]=0x1E;}
 else if(ch=='*'){data[0]=0x14;data[1]=0x08;data[2]=0x3E;data[3]=0x08;data[4]=0x14;}
 else if(ch=='<'){data[1]=0x08;data[2]=0x14;data[3]=0x22;data[4]=0x41;}
 else if(ch=='>'){data[0]=0x41;data[1]=0x22;data[2]=0x14;data[3]=0x08;}
 else if(ch=='['){data[1]=0x7F;data[2]=0x41;}
 else if(ch==']'){data[2]=0x41;data[3]=0x7F;}
 else if(ch==' '||ch=='\n'||ch=='\r'||ch=='\t')return;
 else{data[0]=0x02;data[1]=0x01;data[2]=0x51;data[3]=0x09;data[4]=0x06;}
 for(int cx=0;cx<5;cx++)for(int cy=0;cy<7;cy++)
  if(data[cx]&(1<<cy))rect(x+cx*scale,y+cy*scale,scale,scale,color);
}
void textAt(const String &s,int x,int y,int scale,uint16_t color) {
 int left=x, xx=x, yy=y;
 for(int i=0;i<(int)s.length();i++) {
  char ch=s[i];
  if(ch=='\r')continue;
  if(ch=='\n'){xx=left;yy+=9*scale;continue;}
  if(ch=='\t'){xx+=24*scale;continue;}
  if(xx<LCD_W && xx+5*scale>=0)glyph(xx,yy,ch,scale,color);
  xx+=6*scale;
 }
}
// Overlay is composited into the active framebuffer; no mode switch,
// Do not reset scroll or typewriter progress.
void drawBatteryOverlay(){
 unsigned long now=millis();
 if(wifiToastUntil && (int32_t)(wifiToastUntil-now)>0){
  // Centered short notification; no mode change or mascot resizing.
  rect(48,58,224,58,themeColor());
  rect(51,61,218,52,BLACK);
  textAt(wifiToastEnabled?"WIFI ENABLED":"WIFI DISABLED",63,79,2,
         wifiToastEnabled?0x07E0:0xFFE0);
  return;
 }
 bool batteryCard=batteryOverlayUntil && (int32_t)(batteryOverlayUntil-now)>0;
 bool fullCard=!batteryCard && fullNoticeUntil && (int32_t)(fullNoticeUntil-now)>0;
 bool lowCard=!batteryCard && !fullCard && lowNoticeUntil && (int32_t)(lowNoticeUntil-now)>0;
 bool chargeCard=!batteryCard && !fullCard && !lowCard && chargeNoticeUntil && (int32_t)(chargeNoticeUntil-now)>0;
 if(!batteryCard && !chargeCard && !fullCard && !lowCard)return;
 const int x=38,y=20,w=244,h=148;
 rect(x+3,y+4,w,h,0x18C3);
 rect(x,y,w,h,themeColor());
 rect(x+3,y+3,w-6,h-6,BLACK);
 int pct=constrain(batteryLevel,0,100);
 // On the short-press status card, avoid the large battery widget entirely.
 // It overlaps the dense network diagnostics, so use one compact 1x line.
 if(!batteryCard){
  rect(55,50,51,23,WHITE);rect(58,53,45,17,BLACK);
  rect(106,56,5,11,WHITE);
  rect(60,55,41*pct/100,13,batteryCharging?0x07E0:themeColor());
 }
 if(chargeCard || fullCard || lowCard){
  String heading=fullCard?"CHARGED":lowCard?"LOW BATTERY":"CHARGING";
  textAt(heading,114,51,heading.length()>9?1:2,WHITE);
  textAt(String(pct)+"%",119,82,3,themeColor());
  if(chargeCard){
   // Moving white highlight across the fill conveys charging.
   int progress=(millis()/140)%43;
   int maxFill=41*pct/100;
   if(progress<maxFill)rect(60+progress,56,2,11,WHITE);
  }
 }else{
  // All short-press battery information is 1x (5x7 pixels).
  // A single line frees the rest of the 320x170 display for IP details.
  textAt(String("BATTERY: ")+(batteryReady?String(pct)+"%":"--%")+
         (batteryCharging?" CHARGING":""),42,43,1,themeColor());
  uint16_t duration=batteryCharging?fullMinutes:remainingMinutes;
  if(!batteryCharging && observedDischargeMinutesPerPercent>0 && pct>0){
   float learned=observedDischargeMinutesPerPercent*pct;
   if(learned>=1 && learned<=10080)duration=(uint16_t)learned;
  }
  String label=batteryCharging?"TO FULL ":"TIME LEFT ";
  String estimate;
  if(!batteryReady || duration==0 || duration==0xFFFF || duration>10080)
   estimate="--";
  else
   estimate=String(duration/60)+" hours "+String(duration%60)+" min";
  // Compact diagnostic view: visible for six seconds after GPIO0 press.
  // Keep all lines inside the LCD (320x170) without changing mascot sizes.
  textAt(label+estimate,42,67,1,WHITE);
  // Network information shown only on physical button press.
  // One-pixel font fits inside 320x170 without resizing the mascot.
  textAt(String("BT:")+(bleConnected?"ON":"OFF")+" WIFI:"+(wifiOnline()?"ON":"OFF")+
         " "+(wifiUseDHCP?"DHCP":"STATIC"),42,90,1,WHITE);
  if(wifiOnline()){
   textAt("IP: "+WiFi.localIP().toString(),42,101,1,themeColor());
   textAt("MASK: "+WiFi.subnetMask().toString(),42,112,1,WHITE);
   // RTT is measured by the periodic on-device ICMP gateway probe.
   String gatewayLine="GW: "+WiFi.gatewayIP().toString();
   if(gatewayProbeKnown){
    gatewayLine += gatewayReachable?
      (" "+String(gatewayLatencyMs)+"ms"):" TIMEOUT";
   }else gatewayLine+=" --ms";
   textAt(gatewayLine,42,123,1,gatewayProbeKnown&&!gatewayReachable?0xFFE0:WHITE);
   textAt("DNS: "+WiFi.dnsIP().toString(),42,134,1,WHITE);
   textAt("RSSI:"+String(WiFi.RSSI())+"dBm "+
       (gatewayProbeKnown?(gatewayReachable?"GW OK":"GW FAIL"):"GW CHECKING"),42,145,1,
       gatewayProbeKnown&&!gatewayReachable?0xFFE0:WHITE);
   // SSID is UTF-8 and can be wider than the small overlay; keep byte prefix.
   textAt("SSID: "+WiFi.SSID().substring(0,25),42,156,1,WHITE);
  }else{
   textAt("IP: DISCONNECTED",42,108,1,themeColor());
   textAt("LAST SSID: "+wifiSSID.substring(0,25),42,120,1,WHITE);
  }
 }
}
String cleanText(String s,int limit) {
 s.trim();s.toUpperCase();String out="";
 for(int i=0;i<(int)s.length()&&(int)out.length()<limit;i++){
  unsigned char c=s[i];
  if((c>='A'&&c<='Z')||(c>='0'&&c<='9')||c==' '||c=='-'||c=='!'||c=='.')out+=(char)c;
  else out+='?';
 }
 return out;
}
void drawSmoothGlyph(const SmoothGlyph &g,int x,int y,int w,int h,uint16_t ink,int clipRight);
void richText(const String &str, int x, int y, int ascScale, int jpScale,
              uint16_t color, int clipRight) {
 int startX=x;
 int lineH=max(7*ascScale,16*jpScale)+4;
 for(int p=0;p<(int)str.length();) {
  uint32_t cp=decodeUTF8(str,p);
  if(cp=='\r')continue;
  if(cp=='\n'){x=startX;y+=lineH;continue;}
  if(cp=='\t'){x+=24*ascScale;continue;}
  int width=utfWidth(cp,ascScale,jpScale);
  if(x + width > 0 && x < clipRight) {
   int smooth=findSmoothGlyph(cp);
   if(smooth>=0){
    int h=cp<128?7*ascScale:16*jpScale;
    drawSmoothGlyph(smoothGlyphs[smooth],x,y,width,h,color,clipRight);
   }else if(cp < 128) {
    if(x + width <= clipRight) glyph(x,y,(char)cp,ascScale,color);
   }else {
    for(int k=0; k<glyphCount; k++) if(glyphCache[k].code == cp) {
     for(int row=0; row<16; row++) {
      uint16_t bits = ((uint16_t)glyphCache[k].bits[row*2]<<8) | glyphCache[k].bits[row*2+1];
      for(int col=0; col<16; col++) if(bits & (0x8000>>col)) {
       int xx=x+col*jpScale;
       if(xx+jpScale <= clipRight) rect(xx,y+row*jpScale,jpScale,jpScale,color);
      }
     }
     break;
    }
   }
  }
  x+=width;
 }
}

// G2:HEXUNICODE:0..3:72HEX. Four 36-byte BLE fragments = one
// 24x24 two-bit antialiased glyph. Each command is below 96 bytes.
void acceptSmoothGlyph(String data){
 int a=data.indexOf(':');if(a<=0)return;
 int b=data.indexOf(':',a+1);if(b<=a)return;
 String cpHex=data.substring(0,a),partText=data.substring(a+1,b);
 String hex=data.substring(b+1);
 if(partText.length()!=1||partText[0]<'0'||partText[0]>'3'||hex.length()!=72)return;
 uint32_t cp=strtoul(cpHex.c_str(),nullptr,16);
 if(cp<33||cp>0x10FFFF)return;
 int part=partText[0]-'0';
 if(part==0){smoothStagingCode=cp;smoothStagingMask=0;}
 if(smoothStagingCode!=cp)return;
 for(int k=0;k<36;k++){
  char hi=hex[k*2],lo=hex[k*2+1];
  if(!isxdigit((unsigned char)hi)||!isxdigit((unsigned char)lo))return;
  smoothStaging[part*36+k]=(uint8_t)strtoul(hex.substring(k*2,k*2+2).c_str(),nullptr,16);
 }
 smoothStagingMask|=(uint8_t)(1<<part);
 if(smoothStagingMask!=15)return;
 int slot=findSmoothGlyph(cp);
 if(slot<0){
  if(smoothCount>=MAX_SMOOTH_GLYPHS){
   // Replace oldest cached character if the cache is full.
   memmove(smoothGlyphs,smoothGlyphs+1,(MAX_SMOOTH_GLYPHS-1)*sizeof(SmoothGlyph));
   slot=MAX_SMOOTH_GLYPHS-1;
  }else slot=smoothCount++;
 }
 smoothGlyphs[slot].code=cp;
 memcpy(smoothGlyphs[slot].coverage,smoothStaging,144);
 smoothStagingMask=0;
 noteStateChanged();
}
uint16_t blendGlyphPixel(uint16_t back,uint16_t fore,int alpha){
 int r=(((back>>11)&31)*(3-alpha)+((fore>>11)&31)*alpha+1)/3;
 int g=(((back>>5)&63)*(3-alpha)+((fore>>5)&63)*alpha+1)/3;
 int b=((back&31)*(3-alpha)+(fore&31)*alpha+1)/3;
 return (uint16_t)((r<<11)|(g<<5)|b);
}
void drawSmoothGlyph(const SmoothGlyph &g,int x,int y,int w,int h,uint16_t ink,int clipRight){
 if(w<=0||h<=0)return;
 for(int yy=0;yy<h;yy++){
  int py=y+yy;
  if(py<0||py>=LCD_H)continue;
  int fy=(yy*24)/h;
  for(int xx=0;xx<w;xx++){
   int px=x+xx;
   if(px<0||px>=clipRight||px>=LCD_W)continue;
   int fx=(xx*24)/w;
   int offset=fy*24+fx;
   int shift=6-2*(offset%4);
   int alpha=(g.coverage[offset/4]>>shift)&3;
   if(alpha){int index=py*LCD_W+px;frameSet(index,blendGlyphPixel(frameColor(index),ink,alpha));}
  }
 }
}

// G:HEXUNICODE:64 hexadecimal digits representing a 16x16 monochrome glyph.
void acceptGlyph(String payload) {
 int colon=payload.indexOf(':');
 if(colon<1) return;
 String cpText=payload.substring(0,colon);
 String bitsText=payload.substring(colon+1);
 if(bitsText.length()!=64) return;
 uint32_t cp=strtoul(cpText.c_str(),nullptr,16);
 if(cp<128 || cp>0x10FFFF) return;
 uint8_t bytes[32];
 for(int i=0;i<32;i++) {
  String part=bitsText.substring(i*2,i*2+2);
  for(int j=0;j<2;j++) if(!isxdigit((unsigned char)part[j])) return;
  bytes[i]=(uint8_t)strtoul(part.c_str(),nullptr,16);
 }
 setGlyph(cp,bytes);
 noteStateChanged();
}

void installStartupGlyphs() {
 const uint8_t b3053[32] = {0,0,0,0,15,248,15,248,0,0,0,0,0,0,0,0,8,0,24,0,24,0,28,0,15,252,7,248,0,0,0,0};
 setGlyph(0x3053,b3053);
 const uint8_t b3093[32] = {0,0,1,128,1,128,3,128,3,0,7,0,6,0,15,192,15,192,28,198,24,198,24,238,56,252,48,120,0,0,0,0};
 setGlyph(0x3093,b3093);
 const uint8_t b306B[32] = {0,0,24,0,24,0,24,252,24,252,24,0,24,0,16,0,16,0,61,128,29,128,25,128,25,254,24,252,0,0,0,0};
 setGlyph(0x306B,b306B);
 const uint8_t b3061[32] = {0,0,3,0,7,24,63,248,31,192,6,0,6,224,15,248,15,28,12,12,0,12,0,28,7,248,3,240,0,0,0,0};
 setGlyph(0x3061,b3061);
 const uint8_t b308F[32] = {0,0,6,0,6,0,6,0,62,248,63,252,7,14,14,6,30,6,30,6,62,14,54,28,6,120,6,96,0,0,0,0};
 setGlyph(0x308F,b308F);
}
// CuteDisplay 3.4 deluxe vector sprites are drawn in a fixed native
// 98x170 canvas. All details are clipped/scaled by drawMascot().
// Black panel remains independent of the currently selected theme.
// Expressions and animation share a single face coordinate system.
const uint16_t OUTLINE = 0x39C7;
const uint16_t SHADOW = 0xD69A;
const uint16_t CREAM = 0xFF9C;
const uint16_t BLUSH = 0xFAD6;
const uint16_t LIGHTBLUE = 0x8EDF;

void outlinedOval(int x,int y,int rx,int ry,uint16_t fill,uint16_t edge=OUTLINE) {
 oval(x,y,rx+2,ry+2,edge); oval(x,y,rx,ry,fill);
}
void sparkle(int x,int y,int r,uint16_t c){
 line(x-r,y,x+r,y,c);line(x,y-r,x,y+r,c);
 pixel(x-1,y-1,WHITE);pixel(x+1,y+1,WHITE);
}
void paws(int y,bool animated){
 int lift = animated ? 5 : 0;
 outlinedOval(247,y-lift,12,9,WHITE);
 outlinedOval(297,y+(animated?1:0),12,9,WHITE);
 oval(246,y-lift+3,5,2,BLUSH);oval(298,y+3,5,2,BLUSH);
}
void bunny(){
 // Lively asymmetrical ears: one flicks every few frames.
 int flick = (animPhase>=11 && animPhase<=15)?7:0;
 outlinedOval(250-flick,49,11,38,WHITE);
 outlinedOval(292,54,12,35,WHITE);
 oval(250-flick,48,5,28,themeColor());
 oval(292,53,5,25,themeColor());
 outlinedOval(271,141,28,23,WHITE);
 oval(277,145,18,14,0xEF7D);
 outlinedOval(272,103,40,34,WHITE);
 oval(241,113,9,6,BLUSH);oval(301,113,9,6,BLUSH);
 oval(271,111,5,3,themeColor());
 paws(152,animPhase%8==2);
}
// Character-specific Hello Kitty-style vector sprite. Kept within x=222..319.
// Unlike the shared face, this has no mouth; the oval eyes and yellow nose
// are deliberately placed on its wide head and don't change with mood.
// Character-specific sprites share the same native 98x170 right-side canvas.
// Theme accents change clothing/bows; faces stay recognizably white and black.
void kitty(){
 const uint16_t ink=BLACK, accent=themeColor();
 // Small shoes and symmetrical dress; the head is the dominant silhouette.
 outlinedOval(251,155,13,10,WHITE,ink);
 outlinedOval(290,155,13,10,WHITE,ink);
 outlinedOval(271,140,30,23,accent,ink);
 oval(271,131,11,6,0xF7BE); // dress collar
 // Approved one-piece outline: low triangular ears with softly rounded tips,
 // gently curved upper slopes and smooth joins into the original round cheeks.
 // There is NO separate oval face drawn over the bases of the ears.
 static const int16_t outline[][2]={
  {225,95},
  {225,92},
  {225,90},
  {225,87},
  {226,85},
  {226,83},
  {227,81},
  {228,79},
  {229,76},
  {229,75},
  {228,74},
  {228,72},
  {228,71},
  {228,70},
  {228,68},
  {227,66},
  {227,65},
  {227,62},
  {227,59},
  {227,57},
  {227,54},
  {228,52},
  {228,51},
  {229,49},
  {230,48},
  {232,47},
  {233,47},
  {235,47},
  {236,47},
  {238,47},
  {240,48},
  {242,49},
  {244,49},
  {246,50},
  {248,51},
  {250,52},
  {252,53},
  {254,55},
  {256,56},
  {258,57},
  {259,58},
  {262,58},
  {265,57},
  {268,57},
  {271,57},
  {274,57},
  {277,57},
  {280,58},
  {283,58},
  {284,57},
  {286,56},
  {288,55},
  {290,53},
  {292,52},
  {294,51},
  {296,50},
  {298,49},
  {300,49},
  {302,48},
  {304,47},
  {306,47},
  {307,47},
  {309,47},
  {310,47},
  {312,48},
  {313,49},
  {314,51},
  {314,52},
  {315,54},
  {315,57},
  {315,59},
  {315,62},
  {315,65},
  {315,66},
  {314,68},
  {314,70},
  {314,71},
  {314,72},
  {314,74},
  {313,75},
  {313,76},
  {314,79},
  {315,81},
  {316,83},
  {316,85},
  {317,87},
  {317,90},
  {317,92},
  {317,95},
  {317,104},
  {314,112},
  {310,119},
  {305,125},
  {298,130},
  {290,133},
  {281,135},
  {271,136},
  {261,135},
  {252,133},
  {244,130},
  {237,125},
  {232,119},
  {228,112},
  {225,104}
 };
 const int count=sizeof(outline)/sizeof(outline[0]);
 // Scanline fill, then draw the visible contour for smooth, consistent edges.
 for(int y=45;y<=143;y++){
  int intersections[40],n=0;
  for(int i=0;i<count;i++){
   int j=(i+1)%count;
   int y1=outline[i][1], y2=outline[j][1];
   if((y1<=y && y2>y)||(y2<=y && y1>y)){
    if(n<40) intersections[n++]=outline[i][0]+(long)(y-y1)*(outline[j][0]-outline[i][0])/(y2-y1);
   }
  }
  for(int i=0;i<n;i++)for(int j=i+1;j<n;j++)if(intersections[j]<intersections[i]){
   int t=intersections[i];intersections[i]=intersections[j];intersections[j]=t;
  }
  for(int i=0;i+1<n;i+=2)rect(intersections[i],y,intersections[i+1]-intersections[i]+1,1,WHITE);
 }
 for(int i=0;i<count;i++){
  int j=(i+1)%count;
  line(outline[i][0],outline[i][1],outline[j][0],outline[j][1],ink);
 }
 // Whiskers, three on both sides; no mouth, regardless of mood.
 for(int i=0;i<3;i++){
  int y=107+i*8;
  line(242,y,227,y-3+i*3,ink);
  line(301,y,316,y-3+i*3,ink);
 }
 // Arms are in front of dress, below the broad face.
 outlinedOval(242,142+(animPhase%12==3?-2:0),10,12,WHITE,ink);
 outlinedOval(300,142+(animPhase%12==7?-2:0),10,12,WHITE,ink);
 oval(253+gazeX,106+gazeY,4,7,ink);
 oval(286+gazeX,106+gazeY,4,7,ink);
 oval(271,116,5,4,0xFD00); // signature yellow nose
 // One elegant bow, never two. Ribbon accessory changes this same bow.
 // Loop shapes sit against the upper right ear; eyes and nose stay clear.
 if(accessoryStyle==0 || accessoryStyle==2){
  int sway=(animationIntensity==0?0:((animPhase/6)%3-1));
  int y=77+sway;
  uint16_t bowLight=accent;
  uint16_t bowShadow=0x880F; // dark rose rim: visible with any theme
  // Asymmetrical, gently tapered loops with bright soft folds.
  outlinedOval(288,y-1,12,10,bowLight,bowShadow);
  outlinedOval(307,y+2,11,10,bowLight,bowShadow);
  oval(286,y-4,8,4,bowLight);
  oval(307,y-1,7,4,bowLight);
  // Knotted middle, shaded underneath for three-dimensional depth.
  oval(299,y+1,8,8,bowShadow);
  oval(299,y+1,6,7,bowLight);
  oval(297,y-2,2,3,WHITE);
  line(280,y-5,289,y-2,0xFE9F);
  line(308,y-3,313,y+1,0xFE9F);
  line(282,y+5,291,y+5,bowShadow);
  line(306,y+7,313,y+6,bowShadow);
 }

}
void chiikawa(){
 const uint16_t ink=BLACK;
 // Very short body and feet, much smaller than the rounded face.
 outlinedOval(271,143,22,18,WHITE,ink);
 outlinedOval(255,158,7,7,WHITE,ink);
 outlinedOval(286,158,7,7,WHITE,ink);
 // Round small ears touch the large head.
 outlinedOval(246,78,14,15,WHITE,ink);
 outlinedOval(297,78,14,15,WHITE,ink);
 oval(246,77,7,8,0xF49B);oval(297,77,7,8,0xF49B);
 outlinedOval(271,109,42,39,WHITE,ink);
 // Tufts on cheeks and soft pink blush in the face.
 line(235,114,228,111,ink);line(235,122,229,125,ink);
 line(307,114,314,111,ink);line(307,122,313,125,ink);
 // Permanent rosy cheeks, regardless of the currently chosen mood.
 oval(243,120,9,6,0xFB12);oval(301,120,9,6,0xFB12);
 oval(241,118,3,2,0xFBB2);oval(299,118,3,2,0xFBB2);
 // Eyes are slightly tilted; tiny nose, tiny smiling mouth.
 // Larger glossy eyes with light reflections and a softer outline.
 oval(253+gazeX,105+gazeY,7,9,ink);
 oval(287+gazeX,105+gazeY,7,9,ink);
 oval(250+gazeX,101+gazeY,2,3,WHITE);
 oval(284+gazeX,101+gazeY,2,3,WHITE);
 pixel(256+gazeX,109+gazeY,WHITE);
 pixel(290+gazeX,109+gazeY,WHITE);
 oval(271,116,5,4,0xA6BE); // blue nose
 line(265,126,269,129,ink);line(269,129,272,126,ink);
 line(272,126,276,129,ink);line(276,129,280,126,ink);
 // Forepaws near its chin create Chiikawa's distinctive little pose.
 int lift=animPhase%12==5?3:0;
 outlinedOval(255,139-lift,9,8,WHITE,ink);
 outlinedOval(288,139-lift,9,8,WHITE,ink);
}
void bear(){
 outlinedOval(242,82,19,19,WHITE);
 outlinedOval(301,82,19,19,WHITE);
 oval(242,82,10,10,themeColor());oval(301,82,10,10,themeColor());
 outlinedOval(271,140,29,25,WHITE);
 oval(270,146,18,13,0xEF7D);
 outlinedOval(272,108,43,37,WHITE);
 outlinedOval(272,119,13,10,CREAM,SHADOW);
 oval(272,115,5,4,OUTLINE);
 oval(243,119,9,5,BLUSH);oval(302,119,9,5,BLUSH);
 paws(155,animPhase%11==6);
}
void panda(){
 outlinedOval(243,78,17,19,BLACK,OUTLINE);
 outlinedOval(300,78,17,19,BLACK,OUTLINE);
 outlinedOval(272,143,29,23,WHITE);
 oval(247,144,13,15,BLACK);oval(298,144,13,15,BLACK);
 outlinedOval(272,106,43,39,WHITE);
 oval(253,104,13,15,BLACK);oval(290,104,13,15,BLACK);
 oval(245,123,8,5,BLUSH);oval(299,123,8,5,BLUSH);
 oval(272,118,6,4,BLACK);
 paws(157,animPhase%9==3);
}
void fox(){
 // Pointed furry ears, ruff, little wagging side tail.
 int wag=(animPhase/3)%3-1;
 for(int y=42;y<=91;y++) {
  int w=5+(y-42)*24/49;
  rect(247-w/2,y,w,1,OUTLINE);
  rect(296-w/2,y,w,1,OUTLINE);
 }
 for(int y=48;y<=92;y++) {
  int w=3+(y-48)*19/44;
  rect(247-w/2,y,w,1,WHITE);
  rect(296-w/2,y,w,1,WHITE);
 }
 oval(247,74,7,14,themeColor());oval(296,74,7,14,themeColor());
 outlinedOval(271,141,27,24,WHITE);
 outlinedOval(300+wag*3,147,13,9,WHITE);
 outlinedOval(271,106,43,35,WHITE);
 oval(249,125,18,9,CREAM);oval(293,125,18,9,CREAM);
 oval(243,118,8,5,BLUSH);oval(300,118,8,5,BLUSH);
 oval(271,119,5,4,BLACK);
 paws(154,animPhase%8==4);
}

// Draw expression *after* the body. Eye shapes and shading depend on mood,
// with a deterministic frame sequence: blinking, swaying, sparkles, tears,
// sleeping Zs, excited pupils and hungry chewing.
// Additional hand-drawn details appear briefly over the existing character.
// All coordinates are on the native 98x170 canvas (x = 222..319).
void drawSurpriseEffects(){
 if(!surpriseAction)return;
 uint16_t accent=themeColor();
 int tick=(millis()-surpriseStart)/220;
 switch(surpriseAction){
  case 1: // Sneeze: closed eyes, tiny puff and whisker vibration.
   line(249,104,261,107,BLACK);line(280,107,293,104,BLACK);
   oval(271,127,5+(tick%2)*2,6,BLACK);
   oval(239-(tick%3)*3,114-(tick%2)*3,5,4,WHITE);
   oval(230-(tick%3)*2,106-(tick%2)*5,3,3,CREAM);
   if(tick%3==0)sparkle(238,88,4,accent);
   break;
  case 2: // Stretch: lifted paws, upward accent lines.
   outlinedOval(241,76-(tick%3)*2,9,13,WHITE);
   outlinedOval(301,76-(tick%3)*2,9,13,WHITE);
   line(235,61,231,53,accent);line(305,61,310,53,accent);
   oval(271,125,5,7,BLACK);
   break;
  case 3: // Startled: wide eyes and spring-like motion marks.
   oval(255,104,7,9,BLACK);oval(287,104,7,9,BLACK);
   oval(253,102,2,3,WHITE);oval(285,102,2,3,WHITE);
   oval(271,128,8,10,BLACK);
   line(233,70,227,62,accent);line(309,70,315,62,accent);
   sparkle(231,48+(tick%3)*3,5,accent);
   break;
  case 4: // Look around: shifting pupils and floating question dot.
   {int dx=(tick%8<4)?-4:4;
    rect(249,94,45,20,WHITE);
    if(mascot==4){oval(253,104,11,14,BLACK);oval(288,104,11,14,BLACK);}
    oval(255+dx,104,4,6,BLACK);oval(287+dx,104,4,6,BLACK);
    pixel(254+dx,102,WHITE);pixel(286+dx,102,WHITE);
    textAt("?",302,44-(tick%3)*3,2,accent);
   }
   break;
  case 5: // Butterfly fluttering just beside the mascot.
   {int x=232+(tick*5)%36,y=43+((tick%6)<3?tick%3:5-tick%6)*4;
    oval(x-5,y-3,6,5,accent);oval(x+5,y-3,6,5,accent);
    oval(x-4,y+4,4,3,BLUSH);oval(x+4,y+4,4,3,BLUSH);
    line(x,y-6,x,y+8,BLACK);
    sparkle(231,95+(tick%3)*5,3,accent);
   }
   break;
  case 6: // Blow a kiss: heart emerges and floats upward.
   {int h=constrain(tick*4,0,46);
    int x=272+(tick%5)*2,y=125-h;
    oval(x-4,y-2,4,4,accent);oval(x+4,y-2,4,4,accent);
    line(x-7,y,x,y+8,accent);line(x+7,y,x,y+8,accent);
    sparkle(296,68+(tick%3)*4,3,BLUSH);
   }
   break;
  case 7: // Playful wink and blush pulses.
   line(247,103,260,105,BLACK);
   oval(287,103,5,7,BLACK);
   oval(244,118,8+(tick%3),4,BLUSH);
   oval(301,118,8+(tick%3),4,BLUSH);
   if(tick%4<2)sparkle(307,84,4,accent);
   break;
  case 8: // Dreamy: three rising dream bubbles and closed eyes.
   line(248,103,260,103,BLACK);line(281,103,293,103,BLACK);
   for(int n=0;n<3;n++){
    int y=90-((tick*4+n*17)%62);
    int x=305-n*7;
    oval(x,y,3+n,3+n,WHITE);
   }
   break;
  case 9: // Cheer: rhythmic raised paws and confetti.
   {int lift=(tick%6<3)?10:4;
    outlinedOval(239,82-lift,9,12,WHITE);
    outlinedOval(302,82-lift,9,12,WHITE);
    for(int n=0;n<6;n++){
     int x=229+(n*17)%85,y=24+(n*31+tick*7)%55;
     pixel(x,y,(n%2)?accent:BLUSH);
     pixel(x+1,y+2,WHITE);
    }
   }
   break;
  case 10: // Curious head tilt: side glance and question marks.
   {int dx=(tick%10<5)?-3:3;
    oval(255+dx,104,4,6,BLACK);oval(287+dx,104,4,6,BLACK);
    textAt("?",300,46-(tick%4)*2,2,accent);
    sparkle(230,70,3,accent);
   }
   break;
  case 11: // Happy tears: laughing eyes and drifting sparkles.
   line(248,104,254,100,BLACK);line(254,100,260,104,BLACK);
   line(281,104,287,100,BLACK);line(287,100,293,104,BLACK);
   if(tick%5<3){
    oval(244,115+(tick%4)*2,2,4,LIGHTBLUE);
    oval(300,115+(tick%4)*2,2,4,LIGHTBLUE);
   }
   sparkle(234,54+(tick%6)*3,4,accent);
   break;
  case 12: // Shy: floating mini-hearts and bashful cheeks.
   oval(244,118,10,5,BLUSH);oval(300,118,10,5,BLUSH);
   for(int n=0;n<2;n++){
    int x=234+n*69,y=76-((tick*3+n*12)%32);
    oval(x-2,y,3,3,accent);oval(x+2,y,3,3,accent);
    line(x-4,y+2,x,y+6,accent);line(x+4,y+2,x,y+6,accent);
   }
   break;

 }
}

// Accessories and handheld objects remain fully in the 98x170 right sprite.
void drawMascotFashion(){
 uint16_t c=themeColor(), dark=BLACK;
 int bob=animationIntensity==0?0:((animPhase/4)%3-1)*(animationIntensity==2?2:1);
 // Accessories are anchored to the character's head / neck, not fixed
 // at an arbitrary height. Keep the eyes, nose and cheeks unobstructed.
 int headTop=mascot==1?55:mascot==2?69:mascot==0?27:mascot==5?49:mascot==4?62:mascot==3?66:65;
 int neckY=mascot==1?132:mascot==2?137:136;
 int hatX=271;
 switch(accessoryStyle){
 case 1: // Delicate glasses: transparent inside; only thin rims around eyes.
  {int cy=mascot==2?105:104;
   int lx=mascot==1?253:mascot==2?253:255;
   int rx=mascot==1?286:mascot==2?287:287;
   // Draw just a narrow outline of each lens. Never paint over the eyes.
   for(int lens=0;lens<2;lens++){
    int x=lens==0?lx:rx;
    for(int t=0;t<360;t+=6){
     float ang=t*0.01745329252f;
     pixel(x+(int)(cosf(ang)*13),cy+(int)(sinf(ang)*12),dark);
    }
   }
   line(lx+13,cy-2,rx-13,cy-2,dark);
   line(lx-13,cy-1,lx-16,cy-3,dark);
   line(rx+13,cy-1,rx+16,cy-3,dark);
  }break;
 case 2: // Ribbon variation; replace Kitty's bow, don't overlay it.
  if(mascot!=1){
   int y=headTop+6;
   outlinedOval(274,y+bob,11,8,c,dark);
   outlinedOval(295,y-bob,11,8,c,dark);
   oval(285,y,5,5,YELLOW);
  }
  break;
 case 3: // Solid GOLD crown resting on the head, never theme colored.
  {const uint16_t gold=0xFEA0,shine=0xFFE0;
   int base=headTop+5;
   // Lower band overlaps the top of the head by a few pixels: no gap.
   rect(hatX-22,base-8,44,10,gold);
   for(int y=base-29;y<base-8;y++){
    int t=y-(base-29);
    if(t>=3){rect(hatX-18,y,36,1,gold);}
   }
   // Distinctive crown points and central peak.
   for(int i=-1;i<=1;i++){
    int x=hatX+i*15;
    line(x-8,base-12,x,base-(i==0?38:30),shine);
    line(x,base-(i==0?38:30),x+8,base-12,shine);
    oval(x,base-(i==0?38:30),2,2,shine);
   }
   rect(hatX-20,base-6,40,3,shine);
   oval(hatX,base-3,4,3,0xFA1F);
  }break;
 case 4: // Scarf: wrapped collar plus TWO tapered hanging ends and fringe.
  {const int y=neckY;
   // Only below the chin. Large wrap curves around the upper body.
   outlinedOval(271,y,27,8,c,dark);
   oval(271,y-2,23,4,c);
   // Knotted front section, on the chest, not across the face.
   outlinedOval(279,y+4,7,6,c,dark);
   for(int yy=y+8;yy<=min(166,y+25);yy++){
    int w=max(5,13-(yy-(y+8))/4);
    rect(281-w/2,yy,w,1,c);
   }
   // Second shorter end goes diagonally toward the shoulder.
   for(int i=0;i<14;i++)rect(264-i/2,y+7+i,8,1,c);
   line(277,y+23,277,y+27,dark);
   line(281,y+22,281,y+26,dark);
   line(285,y+21,285,y+25,dark);
  }break;
 case 5: // Party hat with a band planted on top of the head.
  {int base=headTop+4;
   for(int y=base-35;y<=base;y++){
    int w=max(1,(y-(base-35))*34/35);
    rect(hatX-w/2,y,w,1,c);
   }
   rect(hatX-18,base-2,36,4,YELLOW);
   oval(hatX,base-37+bob,4,4,YELLOW);
   for(int j=0;j<3;j++)oval(hatX-7+j*6,base-8-j*5,2,2,WHITE);
  }break;
 case 6: // Flower beside the ear; never placed over a cheek/eye.
  {int x=mascot==1?306:mascot==2?299:301,y=headTop+8;
   oval(x-7,y,5,5,0xFB12);oval(x+7,y,5,5,0xFB12);
   oval(x,y-7,5,5,0xFB12);oval(x,y+7,5,5,0xFB12);
   oval(x,y,5,5,YELLOW);
  }break;
 case 7: // Festive headband, following the upper head contour.
  {int base=headTop+5;
   line(245,base,297,base,c);
   line(245,base+2,297,base+2,c);
   sparkle(272,base-10+bob,6,YELLOW);
   sparkle(301,base-5,3,c);
  }break;
 }
 int item=objectMode==1?manualObject:(
    mood==1?2:mood==2?6:mood==3?7:mood==4?3:
    mood==5?4:mood==6?5:mood==7?1:0);
 int x=271,y=145-(animationIntensity==0?0:(animPhase%8<4?2:0));
 switch(item){
 case 1: // Heart
  oval(x-5,y-3,7,7,c);oval(x+5,y-3,7,7,c);
  line(x-11,y,x,y+13,c);line(x+11,y,x,y+13,c);break;
 case 2: // Bouquet
  for(int n=0;n<4;n++)oval(x+(n%2?6:-6),y-4+(n/2?7:-7),5,5,BLUSH);
  oval(x,y-5,5,5,YELLOW);line(x,y,x,y+13,0x07E0);break;
 case 3: // Cupcake
  rect(x-12,y-4,24,14,c);oval(x,y-7,13,8,WHITE);
  oval(x+2,y-14,3,3,BLUSH);break;
 case 4: // Pillow
  rect(x-18,y-9,36,20,LIGHTBLUE);rect(x-14,y-6,28,14,WHITE);break;
 case 5: // Wand
  line(x-7,y+12,x+9,y-15,YELLOW);sparkle(x+10,y-16,8,c);break;
 case 6: // Tissue
  rect(x-13,y-3,26,13,LIGHTBLUE);
  for(int n=0;n<8;n++)rect(x-10+n*3,y-13+(n%2)*3,2,12,WHITE);break;
 case 7: // Cloud
  oval(x-7,y-5,10,7,OUTLINE);oval(x+7,y-5,10,7,OUTLINE);
  line(x,y+4,x-3,y+12,YELLOW);line(x-3,y+12,x+5,y+9,YELLOW);break;
 }
}
// A temporary speaking expression for ANY typewriter sequence.
// No saved mood or mascot setting is changed: it is a render-only override.
size_t bubbleCharacterCount(const String &s);
static bool mascotIsSpeaking() {
  // Keep eyes continuously open during the entire news bubble,
  // including page-transition pauses; never fall back to sleepy blink mid-speech.
  return bubbleEnabled && bubbleTypewriter
      && revealedCharacters < bubbleCharacterCount(message);
}

static void drawSpeakingMouth() {
  // This executes only during actual text revelation, so facial features
  // automatically return to their ordinary design when writing finishes.
  // Follow the typewriter rhythm, but cap motion so the mouth is readable.
  const bool open = ((millis() / 105UL) % 3UL) != 0UL;
  if (mascot == 1) { // Hello Kitty: temporary speaking mouth, original mouthless face restored later.
    // Preserve her signature yellow nose at y=116 and both whiskers.
    if (open) oval(271, 127, 4, 3, BLACK);
    else line(267, 127, 275, 127, BLACK);
  } else if (mascot == 2) { // Chiikawa: tiny mouth, big open eyes unchanged.
    rect(265, 124, 13, 11, WHITE);
    if (open) { oval(271,129,4,5,BLACK); oval(271,131,2,1,BLUSH); }
    else line(268,129,274,129,BLACK);
  } else {
    // All other mascots: cover only the existing mouth, never the eyes.
    rect(259, 116, 25, 23, WHITE);
    if (open) { oval(271, 126, 6, 8, BLACK); oval(271, 130, 3, 2, BLUSH); }
    else { line(265,126,277,126,BLACK); pixel(271,127,BLACK); }
  }
}

void mascotExpression(){
 // Never clear/paint a rectangular generic face over these unique designs.
 if(mascot==1 || mascot==2){
  int cx=271;
  int eyeY=(mascot==1?106:105);
  int left=(mascot==1?253:254),right=(mascot==1?286:286);
  const bool speaking = mascotIsSpeaking();
  bool blink=!speaking && (animPhase==13||animPhase==14||animPhase==28);
  bool sleepy=mood==5 && !speaking, sad=mood==2 && !speaking, angry=mood==3 && !speaking, shy=mood==7 && !speaking;
  // Erase only the eye area, not the permanent pink cheeks or nose.
  // Character-specific eye proportions are restored every frame.
  int erx=mascot==2?9:8, ery=mascot==2?12:10;
  oval(left,eyeY,erx,ery,WHITE);oval(right,eyeY,erx,ery,WHITE);
  if(blink||sleepy||sad){
   line(left-6,eyeY,left+6,eyeY,BLACK);
   line(right-6,eyeY,right+6,eyeY,BLACK);
  }else{
   int gx=speaking ? 0 : constrain(gazeX,-3,3),gy=speaking ? 0 : constrain(gazeY,-3,2);
   int rx=mascot==2?7:4,ry=mascot==2?9:6;
   oval(left+gx,eyeY+gy,rx,ry,BLACK);
   oval(right+gx,eyeY+gy,rx,ry,BLACK);
   if(mascot==2){
    oval(left+gx-3,eyeY+gy-4,2,3,WHITE);
    oval(right+gx-3,eyeY+gy-4,2,3,WHITE);
    pixel(left+gx+3,eyeY+gy+4,WHITE);
    pixel(right+gx+3,eyeY+gy+4,WHITE);
   }
   if(angry && !speaking){
    line(left-8,eyeY-12,left+5,eyeY-9,BLACK);
    line(right-5,eyeY-9,right+8,eyeY-12,BLACK);
   }
  }
  if(shy){
   oval(241,121,7,3,BLUSH);oval(302,121,7,3,BLUSH);
  }
  if(mascot==2){
   // Chiikawa's mouth always stays tiny. Only a slight expression changes.
   if(sleepy){
    rect(265,124,14,11,WHITE);line(267,128,277,128,BLACK);
   }else if(!speaking && (mood==6||mood==4)){
    rect(265,124,14,11,WHITE);
    oval(cx,129,4,4,BLACK);
   }
  }
  if(sad && animPhase%8<5)oval(right+8,eyeY+12+(animPhase%4),2,4,LIGHTBLUE);
  if(mood==6)sparkle(231,43+animPhase%3,4,themeColor());
  if(sleepy){textAt("Z",300,42-(animPhase%5)*2,1,themeColor());}
  // Kitty deliberately has no mouth, whatever the mood.
  return;
 }
 int cx=271, eyeY=104;
 if(mascot==0) eyeY=102;
 if(mascot==5) eyeY=105;
 uint16_t accent=themeColor();
 const bool speaking = mascotIsSpeaking();
 bool blink=!speaking && (animPhase==13 || animPhase==14 || animPhase==28);
 bool sleepy=(mood==5) && !speaking;
 bool sad=(mood==2) && !speaking;
 bool shy=(mood==7) && !speaking;
 bool angry=(mood==3) && !speaking;
 bool hungry=(mood==4) && !speaking;
 bool excited=(mood==6) && !speaking;
 // Existing facial moods, eyelid animation and surprise actions are preserved.
 int gx=speaking ? 0 : gazeX, gy=speaking ? 0 : gazeY;
 // Clear only the face's features region (not ears, whiskers or bow).
 // Panda patches are restored after the face's white rectangle.
 rect(cx-23,eyeY-10,48,22,WHITE);
 if(mascot==4){
  oval(cx-18,eyeY,12,15,BLACK);
  oval(cx+18,eyeY,12,15,BLACK);
 }
 if(blink || sleepy || sad){
  line(cx-21,eyeY+2,cx-11,eyeY+2,BLACK);
  line(cx+11,eyeY+2,cx+21,eyeY+2,BLACK);
  if(sleepy){pixel(cx-20,eyeY+5,BLACK);pixel(cx+20,eyeY+5,BLACK);}
 }else if(angry){
  oval(cx-16+gx,eyeY+3+gy,4,5,BLACK);oval(cx+16+gx,eyeY+3+gy,4,5,BLACK);
  line(cx-25,eyeY-8,cx-11,eyeY-2,BLACK);
  line(cx+11,eyeY-2,cx+25,eyeY-8,BLACK);
 }else if(excited){
  oval(cx-16+gx,eyeY+gy,5,8,BLACK);oval(cx+16+gx,eyeY+gy,5,8,BLACK);
  oval(cx-17+gx,eyeY-3+gy,2,3,WHITE);oval(cx+15+gx,eyeY-3+gy,2,3,WHITE);
 }else if(shy){
  oval(cx-16+gx,eyeY+3+gy,3,3,BLACK);oval(cx+16+gx,eyeY+3+gy,3,3,BLACK);
  line(cx-22,eyeY-3,cx-10,eyeY-3,OUTLINE);
  line(cx+10,eyeY-3,cx+22,eyeY-3,OUTLINE);
 }else{
  oval(cx-16+gx,eyeY+gy,4,6,BLACK);oval(cx+16+gx,eyeY+gy,4,6,BLACK);
  pixel(cx-17+gx,eyeY-2+gy,WHITE);pixel(cx+15+gx,eyeY-2+gy,WHITE);
 }
 // Mouth is low enough to avoid the eyes while preserving a small nose.
 rect(cx-12,eyeY+13,25,21,WHITE);
 if(hungry){
  int open=(animPhase%6<3)?8:5;
  oval(cx,eyeY+21,8,open,BLACK);
  oval(cx,eyeY+24,5,3,accent);
 }else if(sad){
  line(cx-8,eyeY+27,cx,eyeY+20,BLACK);
  line(cx,eyeY+20,cx+8,eyeY+27,BLACK);
 }else if(angry){
  line(cx-7,eyeY+24,cx+7,eyeY+24,BLACK);
  line(cx-7,eyeY+25,cx-4,eyeY+27,BLACK);
 }else if(sleepy){
  line(cx-5,eyeY+22,cx+5,eyeY+22,BLACK);
 }else if(mood==0){
  line(cx-6,eyeY+23,cx+6,eyeY+23,BLACK);
 }else{
  line(cx-10,eyeY+19,cx,eyeY+27,BLACK);
  line(cx,eyeY+27,cx+10,eyeY+19,BLACK);
  if(excited)oval(cx,eyeY+23,5,4,accent);
 }
 // Mood overlays live *outside* the face to avoid wiping the cheeks.
 if(sad && animPhase%8<5){
  oval(cx+27,eyeY+10+(animPhase%4)*2,3,6,LIGHTBLUE);
 }
 if(excited){
  sparkle(232,38+(animPhase%4),5,accent);
  sparkle(307,48+(animPhase%5),4,accent);
 }
 if(sleepy){
  textAt("Z",303,63-(animPhase%6)*2,2,accent);
  textAt("Z",293,45-(animPhase%6)*2,1,accent);
 }
 if(hungry && animPhase%8<4){
  oval(233,137,7,6,accent);oval(232,137,3,3,YELLOW);
  sparkle(235,127,3,WHITE);
 }
 if(shy){
  oval(244,eyeY+18,7,3,accent);
  oval(300,eyeY+18,7,3,accent);
 }
}

void drawMascot(){
 if(!mascotVisible)return;
 // Render at native resolution first, then scale to 40/60/80/100%.
 // This ensures smaller mascots free *real* horizontal room for text.
 rect(222,0,98,170,BLACK);
 if(mood==6 && animPhase%4==0) sparkle(232,24,6,themeColor());
 switch(mascot){
  case 1:kitty();break;
  case 2:chiikawa();break;
  case 3:bear();break;
  case 4:panda();break;
  case 5:fox();break;
  default:bunny();break;
 }
 mascotExpression();
 if(mascotIsSpeaking()) drawSpeakingMouth();
 drawSurpriseEffects();
 drawMascotFashion();
 if(personalityPose==2 && mascot!=1){
  // A tiny wave without hiding face details.
  outlinedOval(301,133-(animPhase%6)*2,8,9,WHITE);
 }
 if(personalityPose==4 && mood!=5){
  sparkle(305,58+(animPhase%4)*2,4,themeColor());
 }
 if(lowBatteryWarningSent && !batteryCharging && batteryLevel>=0 &&
    batteryLevel<=deviceLowBatteryThreshold){
  if((animPhase/4)%2==0)textAt("Z",296,45,1,themeColor());
  else sparkle(305,45,3,themeColor());
 }
 for(int y=0;y<170;y++)for(int x=0;x<98;x++)
  mascotBackup[y*98+x]=frameColor(y*LCD_W+222+x);
 rect(222,0,98,170,themeBackground());
 int dstW=mascotPanelWidth();
 int dstX=LCD_W-dstW;
 int bodyH=max(30,170*mascotPercent/100);
 int breathe=(animPhase/5)%2;
 int bounce=mood==6?(animPhase%8<4?4:0):
            mood==2?(animPhase/8)%2:
            mood==3?(animPhase%4<2?3:0):
            mood==5?(animPhase/10)%2:1+breathe;
 // Coherent idle movements, kept within a few pixels of the right panel.
 int sway=(personalityPose==2?((animPhase/3)%3-1)*2:0);
 if(personalityPose==3)bounce+=animPhase%4<2?2:0;
 if(personalityPose==4)bounce+=mood==6?4:1;
 if(personalityPose==1 && mood==5)bounce=0;
 int top=(170-bodyH)/2-bounce;
 // Fixed character dimensions: no sudden shrinking or stretching.
 // Clamp the original whole sprite, including ears, to the display.
 dstX=constrain(dstX,0,LCD_W-dstW);
 top=constrain(top,0,LCD_H-bodyH);
 for(int y=0;y<bodyH;y++)for(int x=0;x<dstW;x++) {
  int sx=x*98/dstW-sway,sy=y*170/bodyH;
  if(sx>=0 && sx<98)pixel(dstX+x,top+y,mascotBackup[sy*98+sx]);
 }

}

bool lcdTransferred(esp_lcd_panel_io_handle_t io,
 esp_lcd_panel_io_event_data_t *event,void *context) {
 SemaphoreHandle_t sem=(SemaphoreHandle_t)context;
 BaseType_t woken=pdFALSE;
 if(sem)xSemaphoreGiveFromISR(sem,&woken);
 return woken==pdTRUE;
}
bool beginDrawing() {
 if(!lcdReady||!pixels||!lcdSemaphore)return false;
 if(xSemaphoreTake(lcdSemaphore,pdMS_TO_TICKS(2000))!=pdTRUE)return false;
 // Initialize the WHOLE frame to the selected theme background.
 // No white/unchanged region is left behind the character.
 uint16_t bg = themeBackground();
 memset(paletteHashValid,0,sizeof(paletteHashValid));
 paletteCount=0;
 uint8_t backgroundIndex=colorIndex(bg);
 memset(pixels,backgroundIndex,LCD_W*LCD_H);
 return true;
}
void finishDrawing() {
 // The compositor still redraws the same indexed image in PSRAM, preserving
 // every animation and overlay. Only changed RGB565 columns in each 8-row
 // stripe are transmitted to the LCD; unchanged strips use no SPI transfer.
 const size_t frameBytes=(size_t)LCD_W*LCD_H;
 bool sentAny=false;
 bool transferFailed=false;
 for(int y=0;y<LCD_H;y+=LCD_STRIP_ROWS){
  const int rows=min(LCD_STRIP_ROWS,LCD_H-y);
  int left,right;
  if(!dirtyStripSpan(y,rows,left,right))continue;
  if(sentAny && xSemaphoreTake(lcdSemaphore,pdMS_TO_TICKS(2000))!=pdTRUE){
   Serial.println("[LCD] SPI completion timeout");transferFailed=true;break;
  }
  const int width=right-left;
  // ESP LCD expects a tightly packed buffer for the specified rectangle.
  for(int r=0;r<rows;r++)for(int x=0;x<width;x++){
   uint16_t c=frameColor((size_t)(y+r)*LCD_W+left+x);
   lcdDmaStrip[r*width+x]=(uint16_t)((c<<8)|(c>>8));
  }
  const esp_err_t e=esp_lcd_panel_draw_bitmap(panel,left,y,right,y+rows,lcdDmaStrip);
  if(e!=ESP_OK){Serial.printf("[LCD] Region transfer failed: %d\n",(int)e);transferFailed=true;break;}
  sentAny=true;
 }
 if(transferFailed){
  lastSentValid=false;
  if(!sentAny)xSemaphoreGive(lcdSemaphore);
  return;
 }
 if(!sentAny)xSemaphoreGive(lcdSemaphore);
 // The final DMA completion will release the semaphore asynchronously.
 if(lastSentFrame){
  memcpy(lastSentFrame,pixels,frameBytes);
  memcpy(lastSentPalette,colorPalette,(size_t)paletteCount*sizeof(uint16_t));
  lastSentPaletteCount=paletteCount;
  lastSentValid=true;
 }
}

// Build a substring containing complete UTF-8 Unicode scalar values.
String bubblePrefix(const String &source, size_t count) {
 String result; int pos=0;
 while(pos<(int)source.length() && count-- > 0) {
  int begin=pos; decodeUTF8(source,pos);
  result += source.substring(begin,pos);
 }
 return result;
}
size_t bubbleCharacterCount(const String &source) {
 size_t n=0; int p=0;
 while(p<(int)source.length()){decodeUTF8(source,p);n++;}
 return n;
}
// Bubble is drawn exclusively in the left-side text area. The mascot's
// scaled black panel is never covered by the bubble or its tail.
void drawSpeechBubble() {
 const int right=contentRight();
 const int bx=7,by=22,bw=right-19,bh=116;
 if(bw<55)return;
 // Black surroundings; accent border with a lightly tinted bright interior.
 rect(bx+3,by+4,bw,bh,0x0000);
 rect(bx+4,by-2,bw-8,bh+4,themeColor());
 rect(bx,by+3,bw,bh-6,themeColor());
 rect(bx+3,by+1,bw-6,bh-2,themeBubbleFill());
 rect(bx+5,by+3,bw-10,bh-6,themeBubbleFill());
 // Speech tail points toward the character when visible.
 if(mascotVisible){
  int tx=bx+bw-2,ty=by+bh/2;
  for(int i=0;i<11;i++) rect(tx+i,ty+i/3,1,max(1,14-i),themeColor());
 }
 const int innerLeft=bx+10,innerRight=bx+bw-10;
 const int avail=max(10,innerRight-innerLeft);
 String shown=(bubbleTypewriter ? bubblePrefix(message,revealedCharacters):message);
 // Scale down long messages so more fits within the bubble.
 int a=min(3,asciiMessageScale()),j=min(2,jpMessageScale());
 while((a>1 || j>1) && richWidth(shown,a,j)>avail*3){if(a>1)a--;if(j>1)j--;}
 const int lineH=max(7*a,16*j)+7;
 int x=innerLeft,y=by+13;
 for(int p=0;p<(int)shown.length();) {
  int begin=p;uint32_t cp=decodeUTF8(shown,p);
  if(cp=='\r')continue;
  if(cp=='\n'){x=innerLeft;y+=lineH;continue;}
  if(cp=='\t'){x+=24*a;continue;}
  int w=utfWidth(cp,a,j);
  if(x+w>innerRight && x>innerLeft){x=innerLeft;y+=lineH;}
  if(y+max(7*a,16*j)>by+bh-8)break;
  richText(shown.substring(begin,p),x,y,a,j,BLACK,innerRight);
  x+=w;
 }
 // Blinking caret for optional typewriter animation.
 if(bubbleTypewriter && revealedCharacters<bubbleCharacterCount(message)
    && ((millis()/280)%2==0) && y<by+bh-14)
  rect(min(x,innerRight-3),y,2,max(7*a,16*j),BLACK);
}
void drawMessage() {
 if(!beginDrawing())return;
 int a=asciiMessageScale(), j=jpMessageScale();
 int height=max(7*a,16*j);
 int multilineHeight=height+(richLineCount(message)-1)*(height+4);
 if(bubbleEnabled){drawSpeechBubble();drawMascot();}
 else {drawMascot();richText(message,scrollX,max(0,(LCD_H-multilineHeight)/2),a,j,themeColor(),contentRight());}
 drawBatteryOverlay();
 drawConnectivityHUD();
 finishDrawing();
}
void showMessage(String s) {
 noteStateChanged();
 s.trim(); if(s.isEmpty())return;
 message=s;
 revealedCharacters=0;lastBubbleReveal=millis();
 int width=richWidth(s,asciiMessageScale(),jpMessageScale());
 int right=contentRight();
 scrolling=!bubbleEnabled && width>right-16;
 scrollX=scrolling?right:(right-width)/2;
 drawMessage();lastScroll=millis();
 Serial.println("[MODE] Message");
}
void setBrightness(int percent){
 brightness=constrain(percent,0,100);
 if(pwmReady)ledcWrite(PIN_BL,brightness*255/100);
}
void readBattery(){
 if(!batteryReady)return;
 int value=(int)axp.getSOC();
 if(value<0||value>100)return;
 batteryLevel=value;
 float volts=axp.getBatteryVoltage(),amps=axp.getBatteryCurrent();
 lanVolts=volts;lanAmps=amps;
 if(lanAuthed){lanTemp=(int)axp.getTemperature();lanHealth=(int)axp.getSOH();}
 uint16_t gaugeEmpty=axp.getTimeToEmpty();
 uint16_t gaugeFull=axp.getTimeToFull();
 // AXP2602 reports positive current while charging and negative when
 // discharging. Two samples and hysteresis reduce false popups on noise.
 if(amps>0.035f){
  chargingPositiveSamples=min(3,(int)chargingPositiveSamples+1);
  chargingNegativeSamples=0;
 }else if(amps<-0.025f){
  chargingNegativeSamples=min(3,(int)chargingNegativeSamples+1);
  chargingPositiveSamples=0;
 }
 bool previous=batteryCharging;
 if(chargingPositiveSamples>=2)batteryCharging=true;
 if(chargingNegativeSamples>=2)batteryCharging=false;
 if(!batteryStatusInitialized){
  // Do not show a surprise popup simply because the board booted on USB.
  batteryCharging=amps>0.035f;
  batteryStatusInitialized=true;
 }else if(!previous && batteryCharging){
  chargeNoticeUntil=millis()+CHARGE_NOTICE_MS;
  Serial.println("[POWER] Charging started");
  if(lcdReady)redrawCurrent();
 }
 updateBatteryEstimate(value,amps,batteryCharging,gaugeEmpty,gaugeFull,millis());
 remainingMinutes=batteryStableEmpty;
 fullMinutes=batteryStableFull;
 // Learn real-world minutes per 1% drop. Use only actual on-battery discharge
 // and reset observation after a charging interval. No claim of gauge accuracy.
 unsigned long sampleAt=millis();
 if(batteryCharging || amps>-0.025f){
  lastDischargeSOC=-1;
  dischargeDurationMinutes=0;
 }else if(lastDischargeSOC<0){
  lastDischargeSOC=value;
  lastDischargeObservation=sampleAt;
  dischargeDurationMinutes=0;
 }else{
  dischargeDurationMinutes+=(sampleAt-lastDischargeObservation)/60000.0f;
  lastDischargeObservation=sampleAt;
  if(value<lastDischargeSOC && dischargeDurationMinutes>0.2f){
   int delta=lastDischargeSOC-value;
   if(delta<=5){
    float rate=dischargeDurationMinutes/delta;
    if(rate>=0.5f && rate<=180.0f){
     observedDischargeMinutesPerPercent=observedDischargeMinutesPerPercent<=0?rate:
       (observedDischargeMinutesPerPercent*0.8f+rate*0.2f);
    }
   }
   lastDischargeSOC=value;
   dischargeDurationMinutes=0;
  }else if(value>lastDischargeSOC || dischargeDurationMinutes>360){
   lastDischargeSOC=value;
   dischargeDurationMinutes=0;
  }
 }
 if(batteryStatusInitialized && batteryCharging && value<97)fullBatteryNotified=false;
 // Full requires a credible end-of-charge state, rather than SOC 100 alone.
 if(batteryStatusInitialized && !fullBatteryNotified && value>=100 &&
      ((previous && !batteryCharging) || (batteryCharging && fabsf(amps)<0.035f))){
  fullBatteryNotified=true;
  fullNoticeUntil=sampleAt+3500UL;
  if(lcdReady)redrawCurrent();
 }
 if(value>deviceLowBatteryThreshold+3)lowBatteryWarningSent=false;
 if(deviceLowBatteryThreshold>0 && !batteryCharging && batteryStatusInitialized && value<=deviceLowBatteryThreshold &&
     !lowBatteryWarningSent){
  lowBatteryWarningSent=true;
  lowNoticeUntil=sampleAt+4000UL;
  if(lcdReady)redrawCurrent();
 }
 // Battery telemetry is still sent over BLE every two seconds. No serial spam.

 // Do not poll optional power-registers, format Strings, or prepare GATT
 // notifications until the iPhone is actually connected. SOC/current/voltage,
 // charging state, local overlays and battery learning remain sampled at 2 s.
 if(bleConnected){
  if(powerCharacteristic){
   const int reportedSOC=constrain((int)lroundf(batteryDisplaySOC),0,100);
   String data;
   data.reserve(90); // Minimize repeated heap reallocations/fragmentation.
   data+=String(reportedSOC); data+=",";data+=String(volts,3);data+=",";
   data+=String(amps,3);data+=",";
   data+=String(axp.getTemperature());data+=",";
   data+=String(axp.getSOH());data+=",";
   data+=String(remainingMinutes);data+=",";
   data+=String(fullMinutes);data+=",";
   data+=(wifiOnline()?"1":"0");
   powerCharacteristic->setValue(data.c_str());
   powerCharacteristic->notify();
  }
  if(batteryCharacteristic){
   uint8_t b=(uint8_t)constrain((int)lroundf(batteryDisplaySOC),0,100);
   batteryCharacteristic->setValue(&b,1);
   batteryCharacteristic->notify();
  }
 }
}
void initBattery(){
 Wire.begin(BAT_SDA,BAT_SCL);Wire.setClock(400000);
 batteryReady=axp.begin();
 Serial.println(batteryReady?"[BATTERY] Ready":"[BATTERY] Unavailable");
 if(batteryReady){loadBatteryLearning(); readBattery();}
 lastBatteryRead=millis();
}
class ServerEvents:public BLEServerCallbacks{
 void onConnect(BLEServer *s)override{bleConnected=true;Serial.println("[BLE] Connected");}
 void onDisconnect(BLEServer *s)override{
   bleConnected=false;
   // NimBLE's advertiseOnDisconnect(true) owns the advertising restart.
   // Avoid manually restarting/deinitializing the BLE stack from a callback:
   // during a weak-radio disconnect the NimBLE host may still be unwinding.
   Serial.println("[BLE] Disconnected; advertising managed by NimBLE");
 }
};
class CommandEvents:public BLECharacteristicCallbacks{
 void onWrite(BLECharacteristic *c)override{
  String s=c->getValue();if(s.isEmpty()||!commandQueue)return;
  char item[MAX_CMD+1]={0};int n=min((int)s.length(),MAX_CMD);
  memcpy(item,s.c_str(),n);
  if(xQueueSend(commandQueue,item,0)!=pdTRUE)Serial.println("[BLE] Command queue full");
 }
};
void initBLE(){
 if(!BLEDevice::init("CuteDisplay")){Serial.println("[BLE] Failed");return;}
 BLEDevice::setMTU(185);
 // Persistent BLE bonding (Just Works; no physical passkey input on this board).
 // FFF1 writes remain compatible with unencrypted iOS connections; system accessory authorization alone does not ensure link encryption.
 BLESecurity *security = new BLESecurity();
 security->setCapability(ESP_IO_CAP_NONE);
 security->setAuthenticationMode(ESP_LE_AUTH_REQ_SC_BOND);
 BLEServer *server=BLEDevice::createServer();
 server->setCallbacks(new ServerEvents());server->advertiseOnDisconnect(true);
 BLEService *control=server->createService("FFF0");
 BLECharacteristic *cmd=control->createCharacteristic("FFF1",
  BLECharacteristic::PROPERTY_READ|BLECharacteristic::PROPERTY_WRITE);
 cmd->setValue("HELLO!");cmd->setCallbacks(new CommandEvents());control->start();
 BLEService *batteryService=server->createService("180F");
 batteryCharacteristic=batteryService->createCharacteristic("2A19",
  BLECharacteristic::PROPERTY_READ|BLECharacteristic::PROPERTY_NOTIFY);
 uint8_t value=batteryLevel>=0?(uint8_t)batteryLevel:255;
 batteryCharacteristic->setValue(&value,1);batteryService->start();
 BLEService *powerService=server->createService("FFF3");
 powerCharacteristic=powerService->createCharacteristic("FFF4",BLECharacteristic::PROPERTY_READ|BLECharacteristic::PROPERTY_NOTIFY);
 powerCharacteristic->setValue("0,0,0,0,0,0,0");
 powerService->start();
 BLEService *networkService=server->createService("FFF5");
 networkCharacteristic=networkService->createCharacteristic("FFF6",BLECharacteristic::PROPERTY_READ|BLECharacteristic::PROPERTY_NOTIFY);
 networkCharacteristic->setValue("N:LINK:0");
 networkService->start();
 BLEAdvertising *ad=BLEDevice::getAdvertising();
 ad->addServiceUUID(BLEUUID((uint16_t)0xFFF0));
 ad->addServiceUUID(BLEUUID((uint16_t)0x180F));
 ad->setMinPreferred(0x06);ad->setMaxPreferred(0x12);
 BLEDevice::startAdvertising();
 Serial.println("[BLE] Ready, FFF0/FFF1 + 180F/2A19");
}
void initLCD(){
 pwmReady=ledcAttach(PIN_BL,5000,8);
 if(pwmReady)setBrightness(brightness);
 else{pinMode(PIN_BL,OUTPUT);digitalWrite(PIN_BL,HIGH);}
 lcdSemaphore=xSemaphoreCreateBinary();
 if(!lcdSemaphore){Serial.println("[LCD] Semaphore failed");return;}
 xSemaphoreGive(lcdSemaphore);
 spi_bus_config_t bus={};
 bus.mosi_io_num=PIN_MOSI;bus.miso_io_num=-1;bus.sclk_io_num=PIN_SCLK;
 bus.quadwp_io_num=-1;bus.quadhd_io_num=-1;
 bus.max_transfer_sz=LCD_W*LCD_STRIP_ROWS*2+8;
 ESP_ERROR_CHECK(spi_bus_initialize(SPI2_HOST,&bus,SPI_DMA_CH_AUTO));
 esp_lcd_panel_io_spi_config_t io={};
 io.cs_gpio_num=PIN_CS;io.dc_gpio_num=PIN_DC;
 io.spi_mode=0;io.pclk_hz=20000000;io.trans_queue_depth=10;
 io.lcd_cmd_bits=8;io.lcd_param_bits=8;
 io.on_color_trans_done=lcdTransferred;io.user_ctx=lcdSemaphore;
 ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi((esp_lcd_spi_bus_handle_t)SPI2_HOST,&io,&panelIO));
 esp_lcd_panel_dev_config_t config={};
 config.reset_gpio_num=PIN_RST;
 // RGB565 theme values use RGB channel order. Byte order is fixed at DMA send.
 config.rgb_endian=LCD_RGB_ENDIAN_RGB;config.bits_per_pixel=16;
 ESP_ERROR_CHECK(esp_lcd_new_panel_st7789(panelIO,&config,&panel));
 pinMode(PIN_RST,OUTPUT);digitalWrite(PIN_RST,HIGH);delay(25);
 digitalWrite(PIN_RST,LOW);delay(25);digitalWrite(PIN_RST,HIGH);delay(125);
 ESP_ERROR_CHECK(esp_lcd_panel_init(panel));
 ESP_ERROR_CHECK(esp_lcd_panel_swap_xy(panel,true));
 ESP_ERROR_CHECK(esp_lcd_panel_mirror(panel,false,true));
 // This particular ST7789 module requires inversion ON for
 // framebuffer BLACK=black and WHITE=white on the LCD.
 ESP_ERROR_CHECK(esp_lcd_panel_invert_color(panel,true));
 ESP_ERROR_CHECK(esp_lcd_panel_set_gap(panel,0,35));
 ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(panel,true));
 // Allocate SPI DMA strip internally; move the frame into PSRAM if present.
 // Do not place the DMA transfer buffer in PSRAM.
 lcdDmaStrip=(uint16_t*)heap_caps_malloc(LCD_W*LCD_STRIP_ROWS*2,MALLOC_CAP_DMA|MALLOC_CAP_INTERNAL);
 size_t psramFree=heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
 if(psramFree >= LCD_W*LCD_H){
  pixels=(uint8_t*)heap_caps_malloc(LCD_W*LCD_H,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
  frameInPSRAM=(pixels!=nullptr);
 }
 if(!pixels)
  pixels=(uint8_t*)heap_caps_malloc(LCD_W*LCD_H,MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT);
 // Optional cache only: display continues to work if PSRAM allocation fails.
 // This is never DMA memory and does not consume internal Wi-Fi/TLS heap.
 lastSentFrame=(uint8_t*)heap_caps_malloc((size_t)LCD_W*LCD_H,
                                         MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 lastSentValid=false;
 if(!pixels || !lcdDmaStrip){
  Serial.printf("[LCD] Internal allocation failed: frame=%u, DMA=%u; free=%u largest=%u\n",
    (unsigned)(LCD_W*LCD_H),(unsigned)(LCD_W*LCD_STRIP_ROWS*2),
    (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
    (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL));
  return;
 }
 lcdReady=true;
 // Restore the saved message without treating boot as a user edit.
 // Reveal the entire message immediately: a reset should never resume a
 // half-finished typewriter with a blank bubble.
 String savedMessage=message;
 showMessage(savedMessage);
 revealedCharacters=bubbleCharacterCount(message);
 lastSentValid=false; // force physical redraw, even with LCD frame deduplication
 drawMessage();
 Serial.println("[LCD] Ready 320x170");
}
void wifiPersist(){
 Preferences p;
 if(p.begin("cute-wifi",false)){
  p.putString("ssid",wifiSSID);p.putString("pass",wifiPassword);
  p.putBool("enabled",wifiEnabled);
  p.putBool("dhcp",wifiUseDHCP);p.putString("ip",staticIP);
  p.putString("mask",staticMask);p.putString("gw",staticGateway);p.putString("dns",staticDNS);
  p.end();
 }
}
void loadWifiConfig(){
 Preferences p;
 if(p.begin("cute-wifi",true)){
  wifiSSID=p.getString("ssid","");wifiPassword=p.getString("pass","");
  wifiEnabled=p.getBool("enabled",false);
  wifiUseDHCP=p.getBool("dhcp",true);staticIP=p.getString("ip","");
  staticMask=p.getString("mask","");staticGateway=p.getString("gw","");
  staticDNS=p.getString("dns","");p.end();
 }
 // Connection is deferred until BLE finishes initialization.
}
// Ordinary Arduino Wi-Fi stop/deinit; no news worker or network reset workaround.
static void completeWiFiShutdown(){
 if(!wifiShutdownPending)return;
 stopLAN();
 WiFi.setAutoReconnect(false);
 if(WiFi.getMode()!=WIFI_OFF)WiFi.disconnect(false,false);
 bool ok=WiFi.mode(WIFI_OFF);
 wifiShutdownPending=false;
 wifiPowerCheckPending=true;
 wifiPowerCheckAt=millis()+5000UL;
 gatewayProbeKnown=false;gatewayReachable=false;gatewayLatencyMs=0;
 if(!ok)Serial.println("[WIFI] Shutdown warning");
}
static void checkWiFiOffSettled(unsigned long now){
 if(!wifiPowerCheckPending || (int32_t)(now-wifiPowerCheckAt)<0)return;
 wifiPowerCheckPending=false;
 if(wifiEnabled)return;
 // Retry only via the Arduino API, preserving its internal state tracking.
 if(WiFi.getMode()!=WIFI_OFF){
  Serial.println("[WIFI] WARNING: still active after OFF; retrying WiFi.mode(WIFI_OFF)");
  WiFi.mode(WIFI_OFF);
 }
}
// Power switch shared by the physical button and iPhone app commands.
// Wi-Fi OFF tears down the station rather than only disconnecting the AP.
void setWiFiPower(bool enable,bool showToast){
 wifiEnabled=enable;
 wifiAttemptActive=false;
 wifiInitFailed=false;
 gatewayProbeKnown=false;
 gatewayReachable=false;
 gatewayLatencyMs=0;
 if(enable){
  wifiPowerCheckPending=false;
  wifiShutdownPending=false;
  wifiBootReadyAt=millis()+1200UL;
  nextWiFiAttempt=wifiBootReadyAt;
 }else{
  nextWiFiAttempt=0;
  wifiShutdownPending=true;
  completeWiFiShutdown();
 }
 wifiPersist();              // Preserve off/on choice across resets
 Serial.printf("[WIFI] %s by control; radio mode=%d\n",
    enable?"Enabled":"Disabled",(int)WiFi.getMode());
 sendNetworkTelemetry();
 if(showToast){
  wifiToastEnabled=enable;
  wifiToastUntil=millis()+2300UL;
  batteryOverlayUntil=0;
  chargeNoticeUntil=0;
 }
 if(lcdReady)redrawCurrent();
}
void processCommand(String cmd){
 cmd.trim();
 if(cmd=="W:INFO"){sendNetworkTelemetry();return;}
 if(cmd=="W:GET:KEY"){
  // Never expose this secret via LAN, logs or display; requested over BLE.
  if(bleConnected && !lanSecret.isEmpty())networkReport("N:KEY:"+lanSecret);
  return;
 }
 if(cmd.startsWith("W:GET:")){sendNetworkField(cmd.substring(6));return;}
 // Ping is now a device-side gateway health check, not an app command.
 if(cmd.startsWith("W:PING:"))return;
 if(cmd=="W:DHCP"){wifiUseDHCP=true;wifiPersist();sendNetworkTelemetry();return;}
 if(cmd.startsWith("W:STATIC:")){
  String value=cmd.substring(9);int a=value.indexOf('|');
  int b=a<0?-1:value.indexOf('|',a+1);
  int c=b<0?-1:value.indexOf('|',b+1);
  if(a>0&&b>a&&c>b){
   String ip=value.substring(0,a),mask=value.substring(a+1,b),gw=value.substring(b+1,c),dns=value.substring(c+1);
   IPAddress x,y,z,w;
   if(x.fromString(ip)&&y.fromString(mask)&&z.fromString(gw)&&w.fromString(dns)){
    staticIP=ip;staticMask=mask;staticGateway=gw;staticDNS=dns;wifiUseDHCP=false;
    wifiPersist();sendNetworkTelemetry();
   }else Serial.println("[WIFI] Rejected invalid static IPv4 settings");
  }return;
 }
 if(cmd.startsWith("W:S:")){
  String name=cmd.substring(4);
  if(name.length()>0 && name.length()<=32)wifiSSID=name;
  return;
 }
 if(cmd.startsWith("W:P:")){
  String pass=cmd.substring(4);
  if(pass.length()<=63)wifiPassword=pass;
  return;
 }
 if(cmd=="W:C" || cmd=="W:ON"){
  setWiFiPower(true,false);return;
 }
 if(cmd=="W:OFF"){
  setWiFiPower(false,false);return;
 }
 if(cmd=="W:FORGET"){
  setWiFiPower(false,false);
  wifiSSID="";wifiPassword="";wifiPersist();return;
 }
 if(cmd.startsWith("G2:")){acceptSmoothGlyph(cmd.substring(3));return;}
 if(cmd.startsWith("G:")){acceptGlyph(cmd.substring(2));return;}
 if(cmd=="SAVE:NOW"){saveDisplayState();return;}
 if(cmd.startsWith("T:")||cmd.startsWith("Q:")||cmd.startsWith("Y:")||
    cmd.startsWith("A:")||cmd.startsWith("H:")||cmd.startsWith("J:")||
    cmd.startsWith("K:")||cmd.startsWith("I:")||cmd.startsWith("N:")||
    cmd.startsWith("L:")||cmd.startsWith("S:")||cmd.startsWith("M:")||
    cmd.startsWith("V:")||cmd.startsWith("Z:")||cmd.startsWith("F:")||
    cmd.startsWith("B:")||cmd.startsWith("C:"))noteStateChanged();
 if(cmd.startsWith("T:")){noteStateChanged();
  int n=cmd.substring(2).toInt();
  if(n>=0&&n<=24){theme=n;drawMessage();}
  return;
 }
 if(cmd=="P:OFF"){
  if(stateDirty)saveDisplayState();
  Serial.println("[POWER] Entering deep sleep; press board RESET to wake");
  // Wait until the framebuffer's asynchronous SPI transfer is complete.
  if(lcdSemaphore) xSemaphoreTake(lcdSemaphore,pdMS_TO_TICKS(1500));
  if(panel)esp_lcd_panel_disp_on_off(panel,false);
  if(pwmReady)ledcWrite(PIN_BL,0);
  delay(100);
  esp_deep_sleep_start();
  return;
 }
 if(cmd.startsWith("Q:")) {
  int n=cmd.substring(2).toInt();
  if(n==0||n==1){bubbleEnabled=n==1;showMessage(message);}
  return;
 }
 if(cmd.startsWith("Y:")) {
  int n=cmd.substring(2).toInt();
  if(n==0||n==1){bubbleTypewriter=n==1;if(bubbleEnabled)showMessage(message);}
  return;
 }
 if(cmd.startsWith("A:")){int n=cmd.substring(2).toInt();if(n>=0&&n<=7){accessoryStyle=n;redrawCurrent();}return;}
 if(cmd.startsWith("H:")){int n=cmd.substring(2).toInt();if(n==0||n==1){objectMode=n;redrawCurrent();}return;}
 if(cmd.startsWith("J:")){int n=cmd.substring(2).toInt();if(n>=0&&n<=7){manualObject=n;redrawCurrent();}return;}
 if(cmd.startsWith("K:")){int n=cmd.substring(2).toInt();if(n>=0&&n<=2){animationFrequency=n;scheduleNextSurprise(millis());}return;}
 if(cmd.startsWith("I:")){int n=cmd.substring(2).toInt();if(n>=0&&n<=2){animationIntensity=n;redrawCurrent();}return;}
 if(cmd.startsWith("N:")){int n=cmd.substring(2).toInt();if(n==0||n==1){personalityEnabled=n==1;}return;}
 if(cmd.startsWith("R:")){
  int n=cmd.substring(2).toInt();
  if(n>=0&&n<=2){surpriseAction=n==0?(1+esp_random()%12):choosePerformance(n==2);
   surpriseStart=millis();redrawCurrent();}
  return;
 }
 if(cmd.startsWith("L:")){
  int n=cmd.substring(2).toInt();
  if(n==0||(n>=5&&n<=40)){deviceLowBatteryThreshold=n;lowBatteryWarningSent=false;}
  return;
 }
 if(cmd.startsWith("S:")) {
  int n=cmd.substring(2).toInt();
  if(n==0||n==1){
   surprisesEnabled=n==1;
   surpriseAction=0;
   scheduleNextSurprise(millis());
   redrawCurrent();
  }
  return;
 }
 if(cmd.startsWith("M:")) {
  int n=cmd.substring(2).toInt();
  if(n>=0&&n<=7){mood=n;animPhase=0;surpriseAction=0;scheduleNextSurprise(millis());redrawCurrent();}
  return;
 }
 if(cmd.startsWith("V:")) {
  int n=cmd.substring(2).toInt();
  if(n==0||n==1){mascotVisible=n==1;redrawCurrent();}
  return;
 }
 if(cmd.startsWith("Z:")) {
  int n=cmd.substring(2).toInt();
  if(n==40||n==60||n==80||n==100){mascotPercent=n;redrawCurrent();}
  return;
 }
 if(cmd.startsWith("F:")) {
  int n=cmd.substring(2).toInt();
  if(n>=1&&n<=5){messageSize=n;showMessage(message);}
  return;
 }
 if(cmd.startsWith("B:")){setBrightness(cmd.substring(2).toInt());return;}
 if(cmd.startsWith("C:")){
  int n=cmd.substring(2).toInt();
  if(n>=0&&n<=5){mascot=n;drawMessage();}
  return;
 }
 showMessage(cmd);
}

// Audio hardware loopback: 2 seconds of INMP441 mono I2S capture into PSRAM,
// followed by MAX98357A playback. No AI or cloud request in Phase 1.
// Keep the sample buffer off internal heap. The task always releases I2S resources.
static void voiceLoopbackTask(void*){
 constexpr size_t sampleCount=(VOICE_SAMPLE_RATE*VOICE_RECORD_MS)/1000;
 int32_t* audio=(int32_t*)heap_caps_malloc(sampleCount*sizeof(int32_t),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 if(!audio){Serial.println("[VOICE] PSRAM allocation failed");voiceBusy=false;vTaskDelete(nullptr);return;}
 i2s_chan_handle_t tx=nullptr,rx=nullptr;
 i2s_chan_config_t chan=I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0,I2S_ROLE_MASTER);
 chan.dma_desc_num=4;chan.dma_frame_num=128;
 esp_err_t err=i2s_new_channel(&chan,&tx,&rx);
 if(err!=ESP_OK){Serial.printf("[VOICE] I2S channel error=%d\n",(int)err);goto cleanup;}
 {
  i2s_std_config_t conf={};
  conf.clk_cfg=I2S_STD_CLK_DEFAULT_CONFIG(VOICE_SAMPLE_RATE);
  conf.slot_cfg=I2S_STD_MSB_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT,I2S_SLOT_MODE_MONO);
  conf.gpio_cfg.mclk=I2S_GPIO_UNUSED;
  conf.gpio_cfg.bclk=VOICE_BCLK;conf.gpio_cfg.ws=VOICE_WS;
  conf.gpio_cfg.dout=VOICE_AMP_DOUT;conf.gpio_cfg.din=VOICE_MIC_DIN;
  conf.gpio_cfg.invert_flags.mclk_inv=false;
  conf.gpio_cfg.invert_flags.bclk_inv=false;
  conf.gpio_cfg.invert_flags.ws_inv=false;
  err=i2s_channel_init_std_mode(rx,&conf);
  if(err==ESP_OK)err=i2s_channel_init_std_mode(tx,&conf);
  if(err!=ESP_OK){Serial.printf("[VOICE] I2S configuration error=%d\n",(int)err);goto cleanup;}
 }
 if(i2s_channel_enable(rx)!=ESP_OK){Serial.println("[VOICE] RX enable failed");goto cleanup;}
 {
  size_t pos=0;
  uint32_t started=millis();
  while(pos<sampleCount && millis()-started<VOICE_RECORD_MS+2000UL){
   size_t got=0;
   size_t n=min((size_t)128,sampleCount-pos);
   esp_err_t e=i2s_channel_read(rx,audio+pos,n*sizeof(int32_t),&got,250);
   if(e==ESP_OK)pos+=got/sizeof(int32_t);
  }
  i2s_channel_disable(rx);
  Serial.printf("[VOICE] Captured %u/%u samples\n",(unsigned)pos,(unsigned)sampleCount);
  if(pos>0 && i2s_channel_enable(tx)==ESP_OK){
   // Keep playback quiet: clamp 24-bit microphone data to a modest level.
   for(size_t i=0;i<pos;i++)audio[i]=audio[i]/2;
   size_t offset=0;
   while(offset<pos){
    size_t wrote=0;size_t n=min((size_t)128,pos-offset);
    esp_err_t e=i2s_channel_write(tx,audio+offset,n*sizeof(int32_t),&wrote,350);
    if(e!=ESP_OK)break;
    offset+=wrote/sizeof(int32_t);
   }
   i2s_channel_disable(tx);
  }
 }
cleanup:
 if(tx)i2s_del_channel(tx);
 if(rx)i2s_del_channel(rx);
 heap_caps_free(audio);
 voiceBusy=false;
 vTaskDelete(nullptr);
}
static void startVoiceLoopback(){
 if(voiceBusy)return;
 voiceBusy=true;
 if(xTaskCreate(voiceLoopbackTask,"CuteAudio",6144,nullptr,1,nullptr)!=pdPASS){
  voiceBusy=false;Serial.println("[VOICE] Task allocation failed");
 }
}
// Static graphics/glyph data belongs in PSRAM, not the scarce internal heap.
// These allocations happen exactly once, before NVS glyph restoration and BLE init.
static bool initExternalCaches() {
 mascotBackup=(uint16_t*)heap_caps_malloc(98*170*sizeof(uint16_t),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 glyphCache=(CJKGlyph*)heap_caps_calloc(MAX_GLYPHS,sizeof(CJKGlyph),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 smoothGlyphs=(SmoothGlyph*)heap_caps_calloc(MAX_SMOOTH_GLYPHS,sizeof(SmoothGlyph),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 bool ok=mascotBackup && glyphCache && smoothGlyphs;
 return ok;
}
// Authenticated plaintext LAN commands: protected by a 128-bit random token
// provisioned exclusively over paired BLE. Use trusted private Wi-Fi only.
static void stopLAN(){
 if(lanClient)lanClient.stop();
 lanServer.stop();
 lanListening=false;lanAuthed=false;lanBuffered=0;
}
static void lanLine(const char *line){
 if(!lanAuthed){
  if(strncmp(line,"AUTH ",5)==0 && lanSecret.length()==32 &&
      strlen(line+5)==32 && lanSecret.equals(String(line+5))){
   lanAuthed=true;
   lanClient.print("OK\n");
  }else{ lanClient.print("DENIED\n");lanClient.stop(); }
  return;
 }
 if(strcmp(line,"STATUS")==0){
  // Exactly the same ordered telemetry fields as BLE FFF4 (including Wi-Fi).
  String out="S:";
  out.reserve(96);
  out+=String(constrain((int)lroundf(batteryDisplaySOC),0,100));out+=",";
  out+=String(lanVolts,3);out+=",";
  out+=String(lanAmps,3);out+=",";
  out+=String(lanTemp);out+=",";
  out+=String(lanHealth);out+=",";
  out+=String(remainingMinutes);out+=",";
  out+=String(fullMinutes);out+=",1\n";
  lanClient.print(out);
  return;
 }
 if(strncmp(line,"CMD ",4)==0 && strlen(line+4)<=MAX_CMD){
  String cmd(line+4);
  // Wi-Fi provisioning and shutdown remain BLE/physical-button only.
  if(cmd.startsWith("W:") || cmd=="P:OFF"){
   lanClient.print("NACK\n");return;
  }
  char item[MAX_CMD+1]={0};
  memcpy(item,cmd.c_str(),cmd.length());
  if(commandQueue && xQueueSend(commandQueue,item,0)==pdTRUE)
   lanClient.print("ACK\n");
  else lanClient.print("NACK\n");
  return;
 }
 lanClient.print("NACK\n");
}
static void updateLAN(){
 if(!wifiOnline()){
  if(lanListening)stopLAN();
  return;
 }
 if(!lanListening){
  lanServer.begin();lanServer.setNoDelay(true);
  lanListening=true;
 }
 if(!lanClient || !lanClient.connected()){
  if(lanClient)lanClient.stop();
  lanAuthed=false;lanBuffered=0;
  WiFiClient incoming=lanServer.accept();
  if(incoming){
   lanClient=incoming;lanClient.setNoDelay(true);
   lanLastActivity=millis();
  }
  return;
 }
 // Bounded work to avoid delaying mascot animations, buttons or the LCD.
 int consumed=0;
 while(lanClient.available()>0 && consumed++<160){
  int v=lanClient.read();if(v<0)break;
  lanLastActivity=millis();
  if(v=='\r')continue;
  if(v=='\n'){
   lanBuffer[lanBuffered]=0;
   lanLine(lanBuffer);
   lanBuffered=0;
   if(!lanClient || !lanClient.connected())break;
  }else if(lanBuffered<sizeof(lanBuffer)-1){
   lanBuffer[lanBuffered++]=(char)v;
  }else{
   lanClient.print("NACK\n");lanClient.stop();lanBuffered=0;break;
  }
 }
 if(lanClient && millis()-lanLastActivity>35000UL){
  lanClient.stop();lanAuthed=false;
 }
}

void setup(){
 Serial.begin(115200);delay(700);
 Serial.println("=== CUTEDISPLAY 3.9 RIGHT-SIDE ANIMATIONS ===");
 if(!initExternalCaches()) {
  Serial.println("[MEM] Fatal: PSRAM cache allocation failed. Check QIO PSRAM board setting.");
  // Do not start rendering with null pointers or wipe the saved NVS state.
  while(true) {delay(1000);}
 }
 commandQueue=xQueueCreate(32,MAX_CMD+1);
 if(!commandQueue)Serial.println("[BLE] Queue creation failed");
 pinMode(PIN_USER_BUTTON,INPUT_PULLUP);
 pinMode(PIN_VOICE_BUTTON,INPUT_PULLUP);
 voiceButtonRaw=voiceButtonStable=digitalRead(PIN_VOICE_BUTTON);

 userButtonLastRaw=digitalRead(PIN_USER_BUTTON);
 userButtonStable=userButtonLastRaw;
 loadDisplayState();
 installStartupGlyphs();loadPersistedGlyphs();loadSmoothGlyphs();initBattery();
 // Start BLE before allocating the 108,800-byte DMA LCD frame buffer.
 // The last device log stopped immediately after LCD Ready, before BLE Ready.
 // Reserving BLE controller memory first avoids a fragmented/low internal heap
 // during radio initialization. Wi-Fi is still manual-start only.
 Serial.println("[BOOT] Initializing Bluetooth before LCD...");
 loadLANSecret();
 initBLE();
 Serial.println("[BOOT] Initializing LCD...");
 initLCD();
 setBrightness(brightness);
 stateDirty=false; // startup redraw is not a preference change
 loadWifiConfig();
 // Resume the saved network after the display and Bluetooth have settled.
 // Do not try to start the radio during framebuffer allocation.
 wifiInitFailed=false;
 wifiAttemptActive=false;
 wifiBootReadyAt=millis()+8000UL;
 nextWiFiAttempt=wifiBootReadyAt;
 Serial.printf("[WIFI] Saved=%s; deferred automatic connection\n",
   (wifiEnabled&&!wifiSSID.isEmpty())?"yes":"no");
}
void loop(){
 char input[MAX_CMD+1]={0};
 for(int q=0;q<8&&commandQueue&&xQueueReceive(commandQueue,input,0)==pdTRUE;q++){
  processCommand(String(input));
 }
 // Finish pending ordinary Wi-Fi shutdown.
 completeWiFiShutdown();
 unsigned long now=millis();
 checkWiFiOffSettled(now);
 // GPIO28: short press does nothing; hold >=1.4s starts audio loopback.
 bool rightRaw=digitalRead(PIN_VOICE_BUTTON);
 if(rightRaw!=voiceButtonRaw){voiceButtonRaw=rightRaw;voiceButtonChangedAt=now;}
 if(now-voiceButtonChangedAt>=35 && rightRaw!=voiceButtonStable){
  voiceButtonStable=rightRaw;
  if(rightRaw==LOW){voiceButtonPressedAt=now;voiceButtonLongHandled=false;}
  else{
   // Short press intentionally has no action.
   voiceButtonPressedAt=0;voiceButtonLongHandled=false;
  }
 }
 if(voiceButtonStable==LOW && voiceButtonPressedAt && !voiceButtonLongHandled &&
    now-voiceButtonPressedAt>=VOICE_HOLD_MS){
  voiceButtonLongHandled=true;
  startVoiceLoopback();
 }
 updateWiFi(now);
 updateLAN();
 if(!wifiOnline()){
  if(gatewayProbeKnown || gatewayReachable){
   gatewayProbeKnown=false;gatewayReachable=false;gatewayLatencyMs=0;
   if(lcdReady)redrawCurrent();
  }
  nextGatewayProbe=now+3000UL;
 }else if((int32_t)(now-nextGatewayProbe)>=0){
  // Short ICMP timeout; only redraw if the displayed icon changes.
  bool oldKnown=gatewayProbeKnown,oldReachable=gatewayReachable;
  gatewayReachable=pingDefaultGateway();gatewayProbeKnown=true;
  if(!gatewayReachable)gatewayLatencyMs=0;
  nextGatewayProbe=millis()+GATEWAY_PROBE_PERIOD_MS;
  if(lcdReady && (!oldKnown || oldReachable!=gatewayReachable))redrawCurrent();
 }
 if(bleConnected && networkCharacteristic && (int32_t)(now-nextNetworkTelemetry)>=0){
  nextNetworkTelemetry=now+20000UL;sendNetworkTelemetry();
 }
 bool statusChanged=(bleConnected!=lastDisplayedBle || wifiOnline()!=wifiLastConnected);
 if(statusChanged){
  // Refresh the iPhone's fallback destination when DHCP assigns a new IP.
  if(bleConnected && wifiOnline())sendNetworkField("IP");
  lastDisplayedBle=bleConnected;wifiLastConnected=wifiOnline();
  if(lcdReady && now-lastStatusRedraw>=250){lastStatusRedraw=now;redrawCurrent();}
 }
 updatePersonalityPose(now);
 if(stateDirty && now-stateDirtyAt>=3500UL)saveDisplayState();
 bool raw=digitalRead(PIN_USER_BUTTON);
 if(raw!=userButtonLastRaw){userButtonChangedAt=now;userButtonLastRaw=raw;}
 if(now-userButtonChangedAt>=35 && raw!=userButtonStable){
  userButtonStable=raw;
  if(raw==LOW){
   userButtonPressedAt=now;
   userButtonLongHandled=false;
  }else{
   // The long-press action already fired while held; do not toggle again.
   if(userButtonPressedAt && !userButtonLongHandled){
    wifiToastUntil=0;
    batteryOverlayUntil=now+BATTERY_CARD_MS;
    chargeNoticeUntil=0;
    redrawCurrent();
   }
   userButtonPressedAt=0;
   userButtonLongHandled=false;
  }
 }
 // Act at 1.4 s while GPIO0 is still LOW, not when the finger releases.
 if(userButtonStable==LOW && userButtonPressedAt && !userButtonLongHandled &&
    (unsigned long)(now-userButtonPressedAt)>=WIFI_HOLD_MS){
  userButtonLongHandled=true;  // exactly one toggle per physical hold
  setWiFiPower(!wifiEnabled,true); // draws popup immediately
 }
 if(now-lastBatteryRead>=BATTERY_SAMPLE_MS){
  lastBatteryRead=now;
  readBattery();
 }
 if(wifiToastUntil && (int32_t)(now-wifiToastUntil)>=0){
  wifiToastUntil=0;
  if(lcdReady)redrawCurrent();
 }
 if(batteryOverlayUntil && (int32_t)(now-batteryOverlayUntil)>=0){
  batteryOverlayUntil=0;redrawCurrent();
 }
 if(fullNoticeUntil && (int32_t)(now-fullNoticeUntil)>=0){fullNoticeUntil=0;redrawCurrent();}
 if(lowNoticeUntil && (int32_t)(now-lowNoticeUntil)>=0){lowNoticeUntil=0;redrawCurrent();}
 if(chargeNoticeUntil && (int32_t)(now-chargeNoticeUntil)>=0){
  chargeNoticeUntil=0;redrawCurrent();
 }
 // Refresh charging bar animation without changing the active display mode.
 if(chargeNoticeUntil && now-lastBatteryOverlayFrame>=220UL){
  lastBatteryOverlayFrame=now;
  if(!batteryOverlayUntil)redrawCurrent();
 }
 // Surprise actions start at randomized intervals and automatically end.
 // They never alter the user's chosen mood or mascot.
 if(!nextSurpriseAt)scheduleNextSurprise(millis());
 if(surpriseAction && millis()-surpriseStart>=SURPRISE_DURATION_MS){
  surpriseAction=0;
  scheduleNextSurprise(millis());
  if(mascotVisible && !scrolling)redrawCurrent();
 }else if(surprisesEnabled && mascotVisible && !surpriseAction
          && (int32_t)(millis()-nextSurpriseAt)>=0){
  surpriseAction=choosePerformance((esp_random()%3)==0);
  surpriseStart=millis();
  if(!scrolling)redrawCurrent();
 }
 if(mascotVisible && millis()-lastMascotAnimation>=MASCOT_ANIMATION_MS){
  lastMascotAnimation=millis();animPhase=(animPhase+1)%32;
  updateExpressiveEyes(lastMascotAnimation);
  // The scrolling message already redraws frequently; avoid unnecessary transfers.
  if(!scrolling)redrawCurrent();
 }
 // Animate mouth independently from the letters in ordinary Message Mode.
 // News already redraws up to ~28 fps while its typewriter is active.
 static unsigned long lastSpeakingFrame = 0;
 if(mascotVisible && mascotIsSpeaking() &&
    millis()-lastSpeakingFrame >= 105UL) {
   lastSpeakingFrame=millis();
   drawMessage();
 }
 if(bubbleEnabled && bubbleTypewriter
    && revealedCharacters<bubbleCharacterCount(message)
    && millis()-lastBubbleReveal>=BUBBLE_LETTER_MS){
  lastBubbleReveal=millis();revealedCharacters++;drawMessage();
 }
 if(scrolling&&millis()-lastScroll>=55UL){
  lastScroll=millis();scrollX-=3;
  if(scrollX+richWidth(message,asciiMessageScale(),jpMessageScale())<0)scrollX=contentRight();
  drawMessage();
 }
 // Deadline-aware idle: all rendering is event triggered above (mascot,
 // blinking, text, scrolling, notices). Wake in time for the next deadline;
 // always poll physical keys within 20 ms so input behavior stays responsive.
 uint32_t sleepMs=20;
 auto untilDue=[&](uint32_t deadline){
  int32_t remaining=(int32_t)(deadline-millis());
  if(remaining<=0){sleepMs=1;return;}
  if((uint32_t)remaining<sleepMs)sleepMs=(uint32_t)remaining;
 };
 if(mascotVisible)untilDue(lastMascotAnimation+MASCOT_ANIMATION_MS);
 if(scrolling)untilDue(lastScroll+55UL);
 if(bubbleEnabled && bubbleTypewriter &&
    revealedCharacters<bubbleCharacterCount(message))untilDue(lastBubbleReveal+BUBBLE_LETTER_MS);
 if(mascotVisible && mascotIsSpeaking())untilDue(lastSpeakingFrame+105UL);
 if(chargeNoticeUntil)untilDue(lastBatteryOverlayFrame+220UL);
 if(voiceButtonStable==LOW || userButtonStable==LOW)sleepMs=min(sleepMs,(uint32_t)8);
 if((int32_t)(millis()-(lastBatteryRead+BATTERY_SAMPLE_MS))<0)untilDue(lastBatteryRead+BATTERY_SAMPLE_MS);
 delay(max((uint32_t)1,sleepMs));
}
