/*
 CuteDisplay S3 Brain — Phase 3: encrypted BLE / segmented UART relay beta.
 This is a bench-test build, NOT production authorization: Just Works pairing
 provides encryption/bonding but no MITM protection. USB opt-in required.
 Retains original C5 recovery BLE and proven UART GPIO wiring.
*/
#include <Arduino.h>
#include <WiFi.h>
#include <ESPmDNS.h>
#include <mbedtls/md.h>
#include <esp_system.h>
#include <esp_ota_ops.h>
#include <Preferences.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLEAdvertising.h>
#include <BLESecurity.h>
#include <esp_arduino_version.h>
#if defined(CONFIG_NIMBLE_ENABLED)
#include <host/ble_store.h>
#endif
#if defined(CONFIG_BLUEDROID_ENABLED)
#include <BLE2902.h>
#endif
// BLECharacteristic.h (included by the Arduino BLE library) provides
// ESP_GATT_PERM_* access permission constants on Arduino-ESP32 3.x.
// Do not include the ESP-IDF-internal esp_gatt_defs.h directly.
#include "BrainPinPlan.h"
#include "CuteLink.h"
#include "BrainC5OTA.h"
#include "KittyOTASafety.h"
#include "KittyOTAWriter.h"
#include "KittyOTAFrames.h"
#include "BrainAudioTest.h"
#include "BrainVoiceSTT.h"
#include "BrainClock.h"
#include "BrainAI.h"
#include "BrainRealtimeDirect.h"
#include "BrainMemoryAI.h"

static constexpr char BRAIN_NAME[]="CuteDisplay-Brain-DEV";
static constexpr char S3_FW_VERSION[]="CallFace-v23-dev";
static constexpr size_t MAX_CMD=96;
// Hex-encoding uses two characters/byte; 45 bytes fits the 96-char
// UART frame payload (one-digit chunk index, total, delimiters).
static constexpr int SEG_BYTES=45;
static constexpr uint32_t PROXY_WINDOW_MS=600000UL;
static BLECharacteristic *controlChar=nullptr,*batteryChar=nullptr,*powerChar=nullptr,*networkChar=nullptr;
static bool clientConnected=false;
static volatile bool bleAuthenticated=false;
static volatile bool pairingOK=false,pairingFailed=false;
static volatile bool encryptedControlReadSeen=false;
static volatile uint8_t pairingFailureReason=0;
static volatile uint16_t pairingFailureStatus=0;
static bool wifiEnabled=false,wifiDHCP=true,wifiConnecting=false;
static String wifiSSID,wifiPassword,staticIP,staticMask,staticGateway,staticDNS;
static uint32_t wifiStarted=0,nextWiFiAttempt=0,lastWiFiPoll=0,lastRadioSent=0;
static bool priorWifiConnected=false;
static volatile bool wifiDisconnectPending=false;
static volatile uint8_t wifiDisconnectReason=0;
static uint8_t lastWiFiFailure=0;
static String wifiCommandReply="ACK:WIFI";
static IPAddress configuredIP,configuredMask,configuredGateway,configuredDNS;
static constexpr uint16_t BRAIN_LAN_PORT=8848;
static WiFiServer brainLAN(BRAIN_LAN_PORT);
static WiFiClient lanClient;
static bool lanListening=false,lanAuthenticated=false,lanAwaitingCommand=false,brainMDNS=false;
static String lanSecret,lanNonce;
static char lanLine[192]={0};
static size_t lanLineLen=0;
static uint32_t lanLastActivity=0;
static void pollBrainLAN();
static void stopBrainLAN();
static void initBrainLANSecret();

static volatile bool connectPending=false,disconnectPending=false;
static QueueHandle_t incomingCommands=nullptr,networkQueue=nullptr;
static volatile bool bleDropNotReady=false,bleDropFull=false;
static volatile bool proxyEnabled=false,faceOnline=false;
static uint32_t proxyDeadline=0,lastFace=0,lastHello=0,lastHeartbeat=0,lastNetSent=0;
static uint16_t nextSeq=0;
static CuteLink::Reader frameReader;
static char usbLine[120]={};
static size_t usbLen=0;

// Single outstanding BLE-to-C5 command. Every command is 1..96 raw UTF-8
// bytes divided into 38-byte HEX segments, all individually acknowledged.
static String activeCommand;
static uint8_t activeChunk=0,chunkCount=0,retryCount=0;
static uint16_t activeSeq=0;
static uint32_t chunkSentAt=0;
static String activeFramePayload;

// Just Works bonding encrypts the link but does not authenticate the peer
// against an active MITM. Do not treat it as production identity proof.
class BrainSecurityCallbacks:public BLESecurityCallbacks{
#if defined(CONFIG_BLUEDROID_ENABLED)
 void onAuthenticationComplete(esp_ble_auth_cmpl_t result)override{
  pairingFailureReason=result.fail_reason;
  pairingFailureStatus=result.fail_reason;
  if(result.success)pairingOK=true;else pairingFailed=true;
 }
#elif defined(CONFIG_NIMBLE_ENABLED)
 void onAuthenticationComplete(ble_gap_conn_desc *desc)override{
  if(desc && desc->sec_state.encrypted)pairingOK=true;
  else {pairingFailureStatus=0xFFFF;pairingFailed=true;}
 }
 // Newer Arduino-ESP32 NimBLE invokes the two-argument callback also on
 // failures. Older cores only expose the one-argument success callback.
 // Deliberately omit override for compatibility with both BLE headers.
 void onAuthenticationComplete(ble_gap_conn_desc *desc,int status){
  if(status==0 && desc && desc->sec_state.encrypted)pairingOK=true;
  else {pairingFailureStatus=(uint16_t)status;pairingFailed=true;}
 }
#endif
};
class ServerEvents:public BLEServerCallbacks{
 void onConnect(BLEServer*)override{connectPending=true;}
 // The Arduino-ESP32 BLE stack already calls BLESecurity::startSecurity
 // when security is configured. Avoid a second, racing SMP initiation.
 void onDisconnect(BLEServer*)override{disconnectPending=true;}
};
class CommandEvents:public BLECharacteristicCallbacks{
 // FFF1 requires encrypted READ at the GATT attribute level. A successful
 // callback proves that a bonded iPhone has a usable encrypted session even
 // if the BLE stack skips a fresh onAuthenticationComplete on bond restore.
 void onRead(BLECharacteristic *c)override{
  encryptedControlReadSeen=true;
 }
 void onWrite(BLECharacteristic *c)override{
  String v=c->getValue();
  if(!incomingCommands||v.isEmpty()||v.length()>MAX_CMD)return;
  for(size_t i=0;i<v.length();++i)if(v[i]=='\0')return;
  if(!bleAuthenticated || !proxyEnabled || !faceOnline){
   bleDropNotReady=true;return;
  }
  char row[MAX_CMD+1]={};
  memcpy(row,v.c_str(),v.length());
  if(xQueueSend(incomingCommands,row,0)!=pdTRUE)bleDropFull=true;
 }
};
static uint16_t sendLink(const char *kind,const String &payload=""){
 uint16_t seq=++nextSeq;
 if(!seq)seq=++nextSeq;
 if(!CuteLink::send(Serial1,seq,kind,payload)){
  Serial.println("[S3] UART frame encoding rejected");return 0;
 }
 return seq;
}
static void proxyResult(const String &value){
 if(lanAwaitingCommand &&
    (value.startsWith("ACK:CMD")||value.startsWith("ERR:"))){
  if(lanClient && lanAuthenticated)
   lanClient.println(value.startsWith("ACK:")?"ACK":"NACK");
  lanAwaitingCommand=false;
  return;
 }
 if(!controlChar)return;
 controlChar->setValue(value.c_str());
 if(clientConnected && bleAuthenticated)controlChar->notify();
}
static void cancelCommand(const char *reason){
 if(activeSeq){
  Serial.printf("[S3] Command stopped: %s\n",reason);
  proxyResult(String("ERR:")+reason);
 }
 activeSeq=0;activeChunk=0;chunkCount=0;retryCount=0;activeCommand="";
 activeFramePayload="";
}
static void stopProxy(){
 proxyEnabled=false;
 proxyDeadline=0;
 if(incomingCommands)xQueueReset(incomingCommands);
 // An iPhone BLE disconnect must not cancel a LAN-originated C5 command.
 if(!lanAwaitingCommand)cancelCommand("PROXY_OFF");
}
static String hexify(const String &part){
 const char *hex="0123456789ABCDEF";
 String out;out.reserve(part.length()*2);
 for(size_t i=0;i<part.length();++i){
  uint8_t c=(uint8_t)part[i];
  out+=hex[c>>4];out+=hex[c&15];
 }
 return out;
}
static void sendChunk(bool repeat=false){
 if(!repeat){
  int start=(int)activeChunk*SEG_BYTES;
  String segment=activeCommand.substring(start,min((int)activeCommand.length(),start+SEG_BYTES));
  activeFramePayload=String(activeChunk)+"/"+String(chunkCount)+"/"+hexify(segment);
  retryCount=0;
  activeSeq=sendLink("CMDHEX",activeFramePayload);
 } else if(activeSeq){
  CuteLink::send(Serial1,activeSeq,"CMDHEX",activeFramePayload);
 }
 chunkSentAt=millis();
}
static void acceptCommand(const String &cmd){
 if(cmd.isEmpty()||cmd.length()>MAX_CMD){
  proxyResult("ERR:INVALID_SIZE");return;
 }
 activeCommand=cmd;
 chunkCount=(activeCommand.length()+SEG_BYTES-1)/SEG_BYTES;
 activeChunk=0;
 sendChunk();
}
static void reportPower(const String &v){
 if(v.length()>95)return;
 if(powerChar){
  powerChar->setValue(v.c_str());
  if(clientConnected)powerChar->notify();
 }
 int p=v.indexOf(',');
 if(p<=0)return;
 String level=v.substring(0,p);
 for(size_t i=0;i<level.length();++i)if(level[i]<'0'||level[i]>'9')return;
 int soc=level.toInt();
 if(soc<0||soc>100)return;
 uint8_t b=soc;
 if(batteryChar){
  batteryChar->setValue(&b,1);
  if(clientConnected)batteryChar->notify();
 }
}
static void pushNetwork(const String &v){
 // Wi-Fi events can occur before a paired phone exists. Retain only the
 // last failure locally; do not overflow a queue no phone is draining.
 if(!networkQueue||!clientConnected||!bleAuthenticated||v.length()>96)return;
 char item[97]={};
 memcpy(item,v.c_str(),v.length());
 if(xQueueSend(networkQueue,item,0)!=pdTRUE)
  Serial.println("[S3] Network telemetry queue full");
}
static void sendRadioStatus(bool immediate);
static void toggleBrainWiFiByButton();
static bool pendingC5VoiceStart=false;
static uint16_t brainActivitySeq=33000;
static bool forceActivityResend=false;
static void processFace(const CuteLink::Frame &f){
 lastFace=millis();
 if(!faceOnline){
  Serial.println("[S3] C5 UART connected");
  BrainC5OTA::onConnected(Serial1);
 }
 faceOnline=true;
 if(f.type.startsWith("OTA_")){
  BrainC5OTA::onFrame(Serial1,f);
  return;
 }
 if(f.type=="PROBE"){
  // Exact sequence echo verifies the C5 transmitted and the S3 received it.
  // The C5's warning clears only after it also receives this matching ACK.
  CuteLink::send(Serial1,f.seq,"ACK","PROBE");
 } else if(f.type=="HELLO"){
  forceActivityResend=true;
  if(activeSeq)cancelCommand("FACE_RESTART");
  // Recovery: C5 rebooted while OTA_END ACK was in flight.
  if(BrainC5OTA::stage==BrainC5OTA::END){
   BrainC5OTA::stage=BrainC5OTA::WAIT_BOOT;
   BrainC5OTA::pending=0;
   BrainC5OTA::waitSince=millis();
   BrainC5OTA::lastSent=millis()-3001UL;
  }
  sendRadioStatus(true);
  CuteLink::send(Serial1,f.seq,"ACK","HELLO");
  Serial.println("[C5] HELLO");
 } else if(f.type=="POWER"){
  reportPower(f.payload);
 } else if(f.type=="NET"){
  // C5 radios are disabled; ignore any stale C5 radio telemetry.
 } else if(f.type=="BATTERY"){
  Serial.printf("[C5] BATTERY %s\n",f.payload.c_str());
 } else if(f.type=="CALL_TOGGLE"){
  // C5 left short tap starts or stops native Open WebUI Call Mode.
  bool turningOn=!BrainRealtimeDirect::active();
  if(turningOn && BrainTTS::running)BrainTTS::interrupt();
  bool busy=BrainVoiceSTT::running || BrainAI::busy ||
             BrainAudioTest::running || BrainC5OTA::updating() ||
             BrainTTS::running || BrainRealtimeAudio::active();
  if(!BrainRealtimeDirect::toggle(busy))
   Serial.println("[CALL] C5 button start refused; run USB command call diagnose");
 } else if(f.type=="VOICE_INTERRUPT"){
  pendingC5VoiceStart=false;
  BrainTTS::interrupt();
 } else if(f.type=="VOICE_CANCEL"){
  pendingC5VoiceStart=false;
  BrainTTS::interrupt();
  if(BrainAI::busy){String ignored;BrainAI::provision("AI:STOP",ignored);}
 } else if(f.type=="VOICE_START"){
  if(BrainRealtimeDirect::active() || BrainRealtimeAudio::active())return;
  // Decoder teardown is asynchronous: queue recording until I2S is free.
  if(BrainTTS::running){BrainTTS::interrupt();pendingC5VoiceStart=true;return;}
  if(!BrainC5OTA::updating() && !BrainAudioTest::running && !BrainVoiceSTT::running && !BrainAI::busy && !BrainTTS::running){
   if(BrainVoiceSTT::start())Serial.println("[VOICE] C5 button started recording");
  }else Serial.println("[VOICE] C5 button rejected: busy");
 } else if(f.type=="VOICE_STOP"){
  if(BrainRealtimeDirect::active() || BrainRealtimeAudio::active())return;
  pendingC5VoiceStart=false;
  if(BrainVoiceSTT::stop())Serial.println("[VOICE] C5 button released: send recording");
 } else if(f.type=="WIFI_TOGGLE"){
  // Physical GPIO0 long-press request from the C5, not an untrusted BLE write.
  toggleBrainWiFiByButton();
 } else if(f.type=="STATUS"){
  Serial.printf("[C5] STATUS %s\n",f.payload.c_str());
 } else if(f.type=="LOG"){
  Serial.printf("[C5] LOG %s\n",f.payload.c_str());
 } else if(f.type=="ACK"||f.type=="NACK"){
  BrainAI::onAck(f.seq,f.type,f.payload);
  // Check exact sequence before advancing the BLE command transaction.
  if(activeSeq && f.seq==activeSeq){
   if(f.type=="NACK"){
    cancelCommand("C5_REJECT");return;
   }
   bool finalChunk=(activeChunk+1)==chunkCount;
   if((!finalChunk && f.payload!="PART") ||
      (finalChunk && f.payload!="CMD")){
    cancelCommand("UNEXPECTED_ACK");return;
   }
   if(!finalChunk){
    ++activeChunk;
    sendChunk();
   }else{
    proxyResult("ACK:CMD");
    Serial.println("[S3] BLE -> C5 command acknowledged");
    activeSeq=0;activeChunk=0;chunkCount=0;retryCount=0;
    activeCommand="";activeFramePayload="";
   }
  }else if(f.payload!="HELLO"){
   Serial.printf("[C5] %s %s\n",f.type.c_str(),f.payload.c_str());
  }
 }
}
// Brain is the ONLY enabled radio endpoint in Phase 3.
// Secrets are stored on the S3 (not logged or sent to the C5).
static bool usableStationIP(IPAddress ip){
 return ip!=IPAddress(0,0,0,0) && ip!=IPAddress(255,255,255,255) &&
        ip[0]!=0 && ip[0]!=127 && ip[0]!=169 &&
        ip[0]<224 && ip[0]!=255;
}
static bool brainWiFiOnline(){
 return wifiEnabled && WiFi.status()==WL_CONNECTED &&
        usableStationIP(WiFi.localIP());
}
// Arduino Wi-Fi callbacks execute on a separate task: only record the
// numeric disconnect reason here, then process/log/notify from loop().
static void onBrainWiFiEvent(WiFiEvent_t event,WiFiEventInfo_t info){
 if(event==ARDUINO_EVENT_WIFI_STA_DISCONNECTED){
  uint8_t reason=info.wifi_sta_disconnected.reason;
  // Local intentional disconnect during W:C/reconfiguration is not an AP
  // authentication failure.
  if(reason!=8){
   wifiDisconnectReason=reason;
   wifiDisconnectPending=true;
  }
 }
}
static void persistBrainWiFi(){
 Preferences p;
 if(!p.begin("brainwifi",false))return;
 p.putBool("on",wifiEnabled);p.putBool("dhcp",wifiDHCP);
 p.putString("ssid",wifiSSID);p.putString("pass",wifiPassword);
 p.putString("ip",staticIP);p.putString("mask",staticMask);
 p.putString("gw",staticGateway);p.putString("dns",staticDNS);
 p.end();
}
static void restoreBrainWiFi(){
 Preferences p;
 if(!p.begin("brainwifi",true))return;
 wifiEnabled=p.getBool("on",false);
 wifiDHCP=p.getBool("dhcp",true);
 wifiSSID=p.getString("ssid","");
 wifiPassword=p.getString("pass","");
 staticIP=p.getString("ip","");
 staticMask=p.getString("mask","");
 staticGateway=p.getString("gw","");
 staticDNS=p.getString("dns","");
 p.end();
 // No credentials provisioned? Radio stays OFF instead of advertising false WiFi.
 if(wifiSSID.isEmpty())wifiEnabled=false;
}
static void startBrainWiFi(){
 if(!wifiEnabled || wifiSSID.isEmpty())return;
 WiFi.mode(WIFI_STA);
 WiFi.setAutoReconnect(false);
 // Allow intentionally open test networks as the iPhone UI permits a blank
 // password; otherwise retain a WPA2-or-better network minimum.
 WiFi.setMinSecurity(wifiPassword.isEmpty()?WIFI_AUTH_OPEN:WIFI_AUTH_WPA2_PSK);
 if(!wifiDHCP){
  IPAddress ip,mask,gw,dns;
  if(ip.fromString(staticIP)&&mask.fromString(staticMask)&&
     gw.fromString(staticGateway)&&dns.fromString(staticDNS))
   WiFi.config(ip,gw,mask,dns);
 }else{
  // Returning from a previous static-IP configuration must explicitly
  // restore DHCP. WiFi.mode(WIFI_OFF) alone may retain static IP state.
  // INADDR_NONE can be 0xFFFFFFFF (255.255.255.255) depending on
  // header inclusion order. Explicit zero IPAddress values select DHCP.
  const IPAddress dhcp(0,0,0,0);
  bool dhcpOK=WiFi.config(dhcp,dhcp,dhcp);
  Serial.printf("[S3 WIFI] DHCP reset %s\n",dhcpOK?"OK":"FAILED");
 }
 wifiDisconnectPending=false;
 wifiConnecting=true;wifiStarted=millis();
 // Never print Wi-Fi passwords. The SSID is also omitted from USB logs.
 Serial.printf("[S3] Brain WiFi joining: SSID_bytes=%u DHCP=%d (2.4GHz only)\n",
   (unsigned)wifiSSID.length(),wifiDHCP?1:0);
 pushNetwork("N:STATE:CONNECTING");
 wl_status_t started=WiFi.begin(wifiSSID.c_str(),wifiPassword.c_str());
 if(started==WL_CONNECT_FAILED){
  wifiConnecting=false;
  nextWiFiAttempt=millis()+20000UL;
  pushNetwork("N:FAIL:BEGIN_FAIL");
  pushNetwork("N:STATE:RETRYING");
  Serial.println("[S3] Brain WiFi station refused begin(); retry scheduled");
 }
}
static void stopBrainWiFi(){
 WiFi.disconnect(true,false);
 WiFi.mode(WIFI_OFF);
 wifiConnecting=false;nextWiFiAttempt=0;
 wifiDisconnectPending=false;
}
static void networkInfo(const String &field){
 if(!clientConnected || !bleAuthenticated)return;
 if(field=="LINK"){pushNetwork(String("N:LINK:")+(brainWiFiOnline()?"1":"0"));return;}
 if(field=="STATE"){
  pushNetwork(String("N:STATE:")+(brainWiFiOnline()?"CONNECTED":wifiConnecting?"CONNECTING":wifiEnabled?"DISCONNECTED":"OFF"));
  return;
 }
 if(field=="FAIL"){pushNetwork("N:FAIL:"+String(lastWiFiFailure));return;}
 if(field=="KEY"){
  if(bleAuthenticated && lanSecret.length()==64)pushNetwork("N:KEY:"+lanSecret);
  return;
 }
 if(field=="MODE"){pushNetwork(String("N:MODE:")+(wifiDHCP?"DHCP":"STATIC"));return;}
 if(field=="IP"){pushNetwork("N:IP:"+(brainWiFiOnline()?WiFi.localIP().toString():String("-")));return;}
 if(field=="MASK"){pushNetwork("N:MASK:"+(brainWiFiOnline()?WiFi.subnetMask().toString():String("-")));return;}
 if(field=="GW"){pushNetwork("N:GW:"+(brainWiFiOnline()?WiFi.gatewayIP().toString():String("-")));return;}
 if(field=="DNS"){pushNetwork("N:DNS:"+(brainWiFiOnline()?WiFi.dnsIP().toString():String("-")));return;}
 if(field=="RSSI"){pushNetwork("N:RSSI:"+(brainWiFiOnline()?String(WiFi.RSSI()):String("0")));return;}
 if(field=="SSID"){
  // Encode UTF-8 SSID into six-byte hex pieces, matching the current iPhone app.
  String name=brainWiFiOnline()?WiFi.SSID():wifiSSID;
  const char* hex="0123456789ABCDEF";
  for(int i=0;i<(int)name.length()&&i<32;i+=6){
   String piece;
   for(int j=i;j<i+6&&j<(int)name.length();++j){
    uint8_t c=(uint8_t)name[j];piece+=hex[c>>4];piece+=hex[c&15];
   }
   pushNetwork("N:S"+String(i/6)+":"+piece);
  }
  pushNetwork("N:END");
 }
}
// Safe firmware command filter: WiFi is handled on S3 and never reaches C5.
static bool controlBrainWiFi(const String &cmd){
 if(!cmd.startsWith("W:"))return false;
 wifiCommandReply="ACK:WIFI";
 if(cmd.startsWith("W:S:")){
  String v=cmd.substring(4);
  if(v.length()>0&&v.length()<=32)wifiSSID=v;
  else wifiCommandReply="ERR:BAD_SSID";
 }else if(cmd.startsWith("W:P:")){
  String v=cmd.substring(4);
  if(v.length()<=63&&(v.isEmpty()||v.length()>=8))wifiPassword=v;
  else wifiCommandReply="ERR:BAD_PASSWORD";
 }else if(cmd=="W:C"||cmd=="W:ON"){
  if(wifiSSID.isEmpty()){
   wifiCommandReply="ERR:NO_SSID";
   return true;
  }
  wifiEnabled=true;
  lastWiFiFailure=0;
  pushNetwork("N:FAIL:0");
  persistBrainWiFi();
  stopBrainWiFi();
  startBrainWiFi();
 }else if(cmd=="W:OFF"){
  wifiEnabled=false;persistBrainWiFi();stopBrainWiFi();
  pushNetwork("N:STATE:OFF");
  pushNetwork("N:LINK:0");
 }else if(cmd=="W:FORGET"){
  wifiEnabled=false;stopBrainWiFi();
  wifiSSID="";wifiPassword="";persistBrainWiFi();
  lastWiFiFailure=0;
  pushNetwork("N:STATE:OFF");
  pushNetwork("N:LINK:0");
 }else if(cmd=="W:DHCP"){
  wifiDHCP=true;persistBrainWiFi();
  if(wifiEnabled){stopBrainWiFi();startBrainWiFi();}
 }else if(cmd.startsWith("W:STATIC:")){
  String fields=cmd.substring(9);
  int a=fields.indexOf('|'),b=fields.indexOf('|',a+1),c=fields.indexOf('|',b+1);
  IPAddress ip,mask,gw,dns;
  if(a>0&&b>a&&c>b&&
    ip.fromString(fields.substring(0,a))&&
    mask.fromString(fields.substring(a+1,b))&&
    gw.fromString(fields.substring(b+1,c))&&
    dns.fromString(fields.substring(c+1))){
   staticIP=ip.toString();staticMask=mask.toString();
   staticGateway=gw.toString();staticDNS=dns.toString();
   wifiDHCP=false;persistBrainWiFi();
   if(wifiEnabled){stopBrainWiFi();startBrainWiFi();}
  }
 }else if(cmd=="W:INFO"){
  networkInfo("LINK");
  networkInfo("STATE");
  networkInfo("FAIL");
 }else if(cmd.startsWith("W:GET:")){
  // No S3 LAN fallback server/token exists yet. Never reuse C5 LAN token.
  networkInfo(cmd.substring(6));
 }else if(cmd.startsWith("W:PING:")){
  // Ping support deferred: state is emitted as NO_WIFI or UNSUPPORTED.
  pushNetwork(brainWiFiOnline()?"N:PING:INVALID":"N:PING:NO_WIFI");
 }else{
  wifiCommandReply="ERR:WIFI_UNKNOWN";
 }
 return true;
}
static void toggleBrainWiFiByButton(){
 if(wifiEnabled){
  wifiEnabled=false;
  persistBrainWiFi();
  stopBrainWiFi();
  sendLink("WIFI_STATE","OFF");
  Serial.println("[S3] C5 long press: Brain WiFi OFF");
 } else if(wifiSSID.isEmpty()){
  sendLink("WIFI_STATE","NO_CONFIG");
  Serial.println("[S3] C5 long press: configure S3 WiFi from iPhone first");
 } else {
  wifiEnabled=true;
  persistBrainWiFi();
  startBrainWiFi();
  sendLink("WIFI_STATE","ON");
  Serial.println("[S3] C5 long press: Brain WiFi ON, connecting...");
 }
 networkInfo("LINK");
 sendRadioStatus(true);
}
static void updateBrainWiFi(){
 uint32_t now=millis();
 static uint32_t badIPSince=0,lastBadIPLog=0;
 // Radio association is not proof of a valid DHCP lease or static IP.
 if(wifiEnabled && WiFi.status()==WL_CONNECTED &&
    !usableStationIP(WiFi.localIP())){
  if(!badIPSince)badIPSince=now;
  if((uint32_t)(now-lastBadIPLog)>5000UL){
   lastBadIPLog=now;
   Serial.printf("[S3 WIFI] Associated but INVALID IP=%s GW=%s DNS=%s mode=%s\\n",
       WiFi.localIP().toString().c_str(),
       WiFi.gatewayIP().toString().c_str(),
       WiFi.dnsIP().toString().c_str(),wifiDHCP?"DHCP":"STATIC");
  }
  if((uint32_t)(now-badIPSince)>15000UL){
   Serial.println("[S3 WIFI] Invalid address persisted; restarting STA DHCP/connect");
   badIPSince=0;wifiConnecting=false;
   WiFi.disconnect(false,false);
   nextWiFiAttempt=now+2500UL;
   pushNetwork("N:STATE:RETRYING");
   pushNetwork("N:IP:-");
  }
 }else badIPSince=0;
 if((uint32_t)(now-lastWiFiPoll)<500UL)return;
 lastWiFiPoll=now;
 if(wifiDisconnectPending){
  uint8_t reason=wifiDisconnectReason;
  wifiDisconnectPending=false;
  if(wifiEnabled && !brainWiFiOnline()){
   lastWiFiFailure=reason;
   Serial.printf("[S3] WiFi station disconnected: reason=%u\n",(unsigned)reason);
   pushNetwork("N:FAIL:"+String(reason));
   pushNetwork("N:STATE:DISCONNECTED");
  }
 }
 bool online=brainWiFiOnline();
 if(online){wifiConnecting=false;nextWiFiAttempt=0;}
 if(wifiConnecting && !online && (uint32_t)(now-wifiStarted)>12000UL){
  wifiConnecting=false;
  WiFi.disconnect(false,false);
  nextWiFiAttempt=now+20000UL;
  Serial.printf("[S3] Brain WiFi timed out: status=%d reason=%u; retry in 20s\n",
     (int)WiFi.status(),(unsigned)lastWiFiFailure);
  pushNetwork("N:STATE:RETRYING");
  if(!lastWiFiFailure)pushNetwork("N:FAIL:TIMEOUT");
 }
 if(wifiEnabled && !online && !wifiConnecting &&
     nextWiFiAttempt && (int32_t)(now-nextWiFiAttempt)>=0){
  nextWiFiAttempt=0;startBrainWiFi();
 }
 if(online!=priorWifiConnected){
  priorWifiConnected=online;
  Serial.printf("[S3] Brain WiFi %s\n",online?"CONNECTED":"DISCONNECTED");
  networkInfo("LINK");
  networkInfo("STATE");
  if(online){
   lastWiFiFailure=0;
   pushNetwork("N:FAIL:0");
   networkInfo("IP");
   Serial.printf("[S3] Brain WiFi IP=%s RSSI=%d dBm\n",
       WiFi.localIP().toString().c_str(),WiFi.RSSI());
  }
 }
}
static void sendRadioStatus(bool immediate){
 uint32_t now=millis();
 if(!faceOnline || (!immediate && (uint32_t)(now-lastRadioSent)<1800UL))return;
 lastRadioSent=now;
 String packet=String("b=")+(bleAuthenticated?"1":"0")+
              ";w="+(brainWiFiOnline()?"1":"0")+
              ";ip="+(brainWiFiOnline()?WiFi.localIP().toString():String("-"));
 sendLink("RADIO",packet);
}

// Some boards leave UART1 unresponsive after the USB auto-reset at upload end.
// Only when *no C5 frame has ever arrived* do we restart UART1 in-place.
// This never resets the S3, clears NVS, or interrupts an established link.
static uint32_t uartRecoveryAt=0;
static uint8_t uartRecoveryAttempts=0;
static void recoverFreshBootUART(uint32_t now){
 if(faceOnline || lastFace!=0 || BrainC5OTA::updating())return;
 if(now<12000UL || (uint32_t)(now-uartRecoveryAt)<9000UL || uartRecoveryAttempts>=4)return;
 uartRecoveryAt=now;
 ++uartRecoveryAttempts;
 Serial.printf("[S3 UART] No C5 frames since boot; restart UART1 (attempt %u)\n",uartRecoveryAttempts);
 Serial1.flush();
 Serial1.end();
 delay(25);
 Serial1.setRxBufferSize(2048);
 Serial1.setTxBufferSize(2048);
 Serial1.begin(BrainPinPlan::UART_BAUD,SERIAL_8N1,BrainPinPlan::UART_RX,BrainPinPlan::UART_TX);
 lastHello=0; // Force the normal HELLO retry in pollFace().
}
static void pollFace(){
 CuteLink::Frame f;
 for(int i=0;i<16 && frameReader.poll(Serial1,f);++i)processFace(f);
 uint32_t now=millis();
 recoverFreshBootUART(now);
 if(faceOnline&&(uint32_t)(now-lastFace)>10000UL){
  faceOnline=false;
  Serial.printf("[S3] Face UART timed out: silence=%lums bad_frames=%lu queued=%u\n",
     (unsigned long)(now-lastFace),(unsigned long)frameReader.invalid,
     incomingCommands?(unsigned)uxQueueMessagesWaiting(incomingCommands):0);
  cancelCommand("LINK_LOST");
 }
 if(!faceOnline&&(uint32_t)(now-lastHello)>=2000UL){
  lastHello=now;sendLink("HELLO","S3");
 }
 if(faceOnline&&(uint32_t)(now-lastHeartbeat)>=3000UL){
  lastHeartbeat=now;sendLink("HEARTBEAT");
 }
 sendRadioStatus(false);
 if(activeSeq&&(uint32_t)(now-chunkSentAt)>2500UL){
  if(retryCount<2){
   ++retryCount;
   Serial.println("[S3] Retrying UART chunk after ACK timeout");
   sendChunk(true);
  }else cancelCommand("UART_TIMEOUT");
 }
 if(proxyEnabled && proxyDeadline && (int32_t)(now-proxyDeadline)>=0){
  stopProxy();Serial.println("[S3] Proxy test window expired");
 }
}
static void pollNetwork(){
 if(!clientConnected||!bleAuthenticated||!networkQueue||!networkChar)return;
 if((uint32_t)(millis()-lastNetSent)<50UL)return;
 char item[97]={};
 if(xQueueReceive(networkQueue,item,0)==pdTRUE){
  lastNetSent=millis();
  networkChar->setValue(item);
  networkChar->notify();
 }
}
static void pollBLECommands(){
 if(bleDropNotReady){
  bleDropNotReady=false;
  proxyResult("ERR:NOT_READY");
  Serial.println("[S3] BLE write rejected: pairing or Face not ready");
 }
 if(bleDropFull){
  bleDropFull=false;
  proxyResult("ERR:QUEUE_FULL");
  Serial.println("[S3] BLE write rejected: command queue full");
 }
 // Never deliver app/WiFi credentials until the BLE link is encrypted and
 // the pairing-complete event has enabled this session.
 if(!incomingCommands || activeSeq || !proxyEnabled || !bleAuthenticated)return;
 char item[MAX_CMD+1]={};
 if(xQueueReceive(incomingCommands,item,0)!=pdTRUE)return;
 if(!faceOnline){proxyResult("ERR:FACE_OFFLINE");return;}
 if(BrainC5OTA::updating()){
  proxyResult("ERR:DISPLAY_UPDATING");return;
 }
 String incoming(item);
 if(incoming.startsWith("TIME:")){
  proxyResult(BrainClock::configure(incoming)?"ACK:TIME_ZONE":"ERR:TIME_ZONE");
  return;
 }
 if(incoming.startsWith("AI:")){
   if((BrainRealtimeDirect::active() || BrainRealtimeAudio::active()) && incoming=="AI:GO"){
    proxyResult("ERR:CALL_ACTIVE");return;
   }
   String result;
  if(BrainAI::provision(incoming,result)){
   // Do not expose AI:DATA hex, key, or prompt in serial logs.
   if(incoming.startsWith("AI:BEGIN:"))
    Serial.printf("[AI CTRL] Provisioning field %c (%s)\n",
                  incoming.length()>9?incoming[9]:'?',result.c_str());
   else if(incoming=="AI:END" || incoming=="AI:GO" || incoming=="AI:PING")
    Serial.printf("[AI CTRL] %s: %s\n",
                  incoming=="AI:GO"?"Start":incoming=="AI:PING"?"Ping":"Field complete",result.c_str());
   proxyResult(result);return;
  }
  Serial.println("[AI CTRL] Unsupported AI command rejected");
  proxyResult("ERR:AI_UNKNOWN");return;
 }
 if(incoming=="A:VOICE:STOP"){
  proxyResult(BrainVoiceSTT::stop()?"ACK:VOICE_STOPPING":"ERR:VOICE_NOT_RECORDING");
  return;
 }
 if(incoming=="A:VOICE"){
  if(BrainC5OTA::updating() || BrainAudioTest::running || BrainVoiceSTT::running || BrainAI::busy || BrainTTS::running || BrainRealtimeDirect::active() || BrainRealtimeAudio::active()){
   proxyResult("ERR:AUDIO_BUSY");return;
  }
  proxyResult(BrainVoiceSTT::start()?"ACK:VOICE_STARTED":"ERR:VOICE_START");
  return;
 }
 if(incoming=="A:TEST"){
  if(BrainAudioTest::running || BrainVoiceSTT::running || BrainTTS::running || BrainRealtimeDirect::active() || BrainRealtimeAudio::active()){proxyResult("ERR:AUDIO_BUSY");return;}
  if(BrainC5OTA::updating()){proxyResult("ERR:DISPLAY_UPDATING");return;}
  BrainAudioTest::start();
  proxyResult("ACK:AUDIO_TEST");
  return;
 }
 if(incoming.startsWith("A:MIC:")||incoming.startsWith("A:SPK:")){
  bool ok=BrainAudioTest::setLevel(incoming);
  proxyResult(ok?"ACK:AUDIO":"ERR:AUDIO");
  return;
 }
 if(controlBrainWiFi(incoming)){
  proxyResult(wifiCommandReply);
  return;
 }
 acceptCommand(incoming);
}
static void consoleCommand(String cmd){
 cmd.trim();
 if(cmd=="help"){
  Serial.println("[S3] call status / call diagnose / call start / call stop / call mood 0..15");
  Serial.println("[S3] c5 ota status (automatic OTA when a newer embedded C5 image is available)");
  Serial.println("[S3] audio beep / audio diagnose / audio test / memory status / system status / memory probe / memory format CONFIRM");
  Serial.println("[S3] help status ping battery msg <text> mascot <0-5> mood <0-7> proxy on proxy off ble bonds clear");
  return;
 }
 if(cmd.startsWith("A:MIC:")||cmd.startsWith("A:SPK:")){
  BrainAudioTest::setLevel(cmd);return;
 }
 if(cmd=="audio diagnose"||cmd=="audio beep"||cmd=="audio test"){
  if(BrainRealtimeDirect::active()||BrainRealtimeAudio::active()){
   Serial.println("[AUDIO] Call Mode owns I2S; end call first");return;
  }
 }
 if(cmd=="audio diagnose"){BrainAudioTest::diagnose();return;}
 if(cmd=="audio beep"){BrainAudioTest::beep();return;}
 if(cmd=="audio test"){
  if(BrainC5OTA::updating())Serial.println("[AUDIO] Wait until C5 OTA completes");
  else BrainAudioTest::start();
  return;
 }
 if(cmd.startsWith("memory recall ")){
  String query=cmd.substring(14);
  String recent=KittyMemory::recall(query);
  Serial.printf("[MEMORY] recent recall: %s\n",recent.isEmpty()?"NO MATCH":recent.c_str());
  uint32_t id=KittyMemory::requestSearch(query);
  Serial.printf("[MEMORY] archive search request=%lu (try again after 100ms if needed)\n",(unsigned long)id);
  return;
 }
 if(cmd=="memory format CONFIRM"){
  bool accepted=KittyMemory::requestFormat();
  Serial.println(accepted?
    "[MEMORY] Format requested. This erases the complete SD card. Watch C5 status.":
    "[MEMORY] Format refused: SD initialization or another format is in progress.");
  return;
 }
 if(cmd=="memory probe"){
  bool accepted=KittyMemory::queue("memory diagnostic probe","SD write test only");
  Serial.printf("[MEMORY] probe queued=%d; check 'memory status' after a moment\n",accepted?1:0);
  return;
 }
 if(cmd=="memory status"){
  Serial.printf("[MEMORY] mounted=%d indexed=%u/%u saved=%lu failed=%lu free_psram=%lu\n",
    KittyMemory::ready()?1:0,(unsigned)KittyMemory::indexCount,
    (unsigned)KittyMemory::INDEX_MAX,(unsigned long)KittyMemory::saved,
    (unsigned long)KittyMemory::failed,
    (unsigned long)heap_caps_get_free_size(MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
  Serial.printf("[MEMORY] profile_facts=%u\n",(unsigned)KittyMemory::factCount);
  Serial.print(KittyMemory::factSummary());
  return;
 }
 if(cmd=="system status" || cmd=="diagnostics"){
  // Read-only snapshot; does not stop I2S, read the SD filesystem or
  // allocate large buffers. CPU percentage is deliberately NOT guessed.
  Serial.printf("[SYS] uptime_ms=%lu reset_reason=%d cpu_mhz=%lu cores=%d loop_core=%d\n",
    (unsigned long)millis(),(int)esp_reset_reason(),
    (unsigned long)ESP.getCpuFreqMHz(),(int)ESP.getChipCores(),(int)xPortGetCoreID());
  Serial.printf("[SYS HEAP] internal_free=%lu internal_min=%lu internal_largest=%lu psram_free=%lu psram_min=%lu psram_largest=%lu\n",
    (unsigned long)heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
    (unsigned long)heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
    (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
    (unsigned long)heap_caps_get_free_size(MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT),
    (unsigned long)heap_caps_get_minimum_free_size(MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT),
    (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
  Serial.printf("[SYS CPU] frequency_mhz=%lu free_rtos_tasks=%lu loop_stack_highwater_bytes=%lu (instant CPU load unavailable)\n",
    (unsigned long)ESP.getCpuFreqMHz(),(unsigned long)uxTaskGetNumberOfTasks(),
    (unsigned long)uxTaskGetStackHighWaterMark(nullptr));
  // Task measurements are high-water stack headroom in bytes, not CPU load.
  // Never walk the whole RTOS task list from the realtime WebSocket loop.
  Serial.printf("[SYS TASKS] audio_core=0 audio_priority=3 audio_stack_free=%lu sd_core=0 sd_priority=1 sd_stack_free=%lu ai_core=0 ai_priority=1 ai_stack_free=%lu\n",
    (unsigned long)(BrainRealtimeAudio::owner?uxTaskGetStackHighWaterMark(BrainRealtimeAudio::owner):0),
    (unsigned long)(KittyMemory::worker?uxTaskGetStackHighWaterMark(KittyMemory::worker):0),
    (unsigned long)(BrainAI::worker?uxTaskGetStackHighWaterMark(BrainAI::worker):0));
  Serial.printf("[SYS MEMORY] mounted=%d state=%u facts=%u indexed=%lu/%lu saved=%lu failed=%lu queue=%u ai_queue=%u\n",
    KittyMemory::ready()?1:0,(unsigned)KittyMemory::status(),
    (unsigned)KittyMemory::factCount,(unsigned long)KittyMemory::indexCount,
    (unsigned long)KittyMemory::INDEX_MAX,(unsigned long)KittyMemory::saved,
    (unsigned long)KittyMemory::failed,
    (unsigned)(KittyMemory::writes?uxQueueMessagesWaiting(KittyMemory::writes):0),
    (unsigned)(KittyMemory::consolidationCandidates?uxQueueMessagesWaiting(KittyMemory::consolidationCandidates):0));
  Serial.printf("[SYS SD] used_kb=%lu total_kb=%lu available_kb=%lu\n",
    (unsigned long)KittyMemory::usedKB(),(unsigned long)KittyMemory::capacityKB(),
    (unsigned long)(KittyMemory::capacityKB()>KittyMemory::usedKB()?
       KittyMemory::capacityKB()-KittyMemory::usedKB():0));
  Serial.printf("[SYS CALL] state=%s connected=%d audio_active=%d speaker_buffer_ms=%lu speaker_peak_ms=%lu speaker_dropped_ms=%lu underruns=%lu mic_dropped=%lu stage=%s\n",
    BrainRealtimeDirect::activity().c_str(),BrainRealtimeDirect::active()?1:0,
    BrainRealtimeAudio::active()?1:0,(unsigned long)BrainRealtimeAudio::bufferedMs(),
    (unsigned long)BrainRealtimeAudio::peakSpeakerMs(),
    (unsigned long)BrainRealtimeAudio::droppedSpeakerMs(),
    (unsigned long)BrainRealtimeAudio::speakerUnderruns,
    (unsigned long)BrainRealtimeAudio::droppedMic,BrainRealtimeAudio::issue());
  Serial.printf("[SYS WORK] memory_ai_running=%d memory_ai_aborting=%d legacy_ai=%d stt=%d tts=%d ota=%d wifi=%d\n",
    BrainMemoryAI::running?1:0,BrainMemoryAI::abortRequested?1:0,
    BrainAI::busy?1:0,BrainVoiceSTT::running?1:0,
    BrainTTS::running?1:0,BrainC5OTA::updating()?1:0,
    WiFi.status()==WL_CONNECTED?1:0);
  return;
 }
 if(cmd=="c5 ota status"){
  Serial.printf("[S3 OTA] automatic update enabled; stage=%d target_v=%lu\n",
   (int)BrainC5OTA::stage,(unsigned long)C5Image::version);
  return;
 }
 if(cmd=="call diagnose"){
  bool busy=BrainVoiceSTT::running || BrainAI::busy ||
    BrainAudioTest::running || BrainC5OTA::updating() ||
    BrainTTS::running || BrainRealtimeAudio::active();
  Serial.printf("[CALL] DIAG busy flags: legacy_stt=%d legacy_ai=%d audio_test=%d tts=%d c5_ota=%d i2s_owner=%d\n",
   BrainVoiceSTT::running?1:0,BrainAI::busy?1:0,
   BrainAudioTest::running?1:0,BrainTTS::running?1:0,
   BrainC5OTA::updating()?1:0,BrainRealtimeAudio::active()?1:0);
  BrainRealtimeDirect::diagnose(busy);
  return;
 }
 if(cmd.startsWith("call mood ")){
  // Optional visual check: does not change Open WebUI, AI persona or
  // persistent C5 mood. Requires an active realtime call.
  int mood=cmd.substring(10).toInt();
  if(cmd.length()!=11 || cmd[10]<'0'||cmd[10]>'7' ||
     !BrainRealtimeDirect::active()){
   Serial.println("[CALL FACE] Start Call Mode, then use call mood 0..7");return;
  }
  BrainRealtimeDirect::chooseMood(mood,true);
  Serial.printf("[CALL FACE] temporary full-screen expression=%d\n",mood);
  return;
 }
 if(cmd=="call status"){
  Serial.printf("[CALL] state=%s socket_requested=%d i2s_owner=%d i2s_ready=%d playback_buffer_ms=%lu playback_peak_ms=%lu playback_skipped_ms=%lu underruns=%lu mic_dropped=%lu\n",
   BrainRealtimeDirect::activity().c_str(),BrainRealtimeDirect::active()?1:0,
   BrainRealtimeAudio::active()?1:0,BrainRealtimeAudio::initialized()?1:0,
   (unsigned long)BrainRealtimeAudio::bufferedMs(),
   (unsigned long)BrainRealtimeAudio::peakSpeakerMs(),
   (unsigned long)BrainRealtimeAudio::droppedSpeakerMs(),
   (unsigned long)BrainRealtimeAudio::speakerUnderruns,
   (unsigned long)BrainRealtimeAudio::droppedMic);
  Serial.printf("[CALL AUDIO] last_stage=%s psram_found=%d internal_free=%lu largest_internal=%lu psram_free=%lu\n",
   BrainRealtimeAudio::issue(),psramFound()?1:0,
   (unsigned long)heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
   (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
   (unsigned long)heap_caps_get_free_size(MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
  return;
 }
 if(cmd=="call stop"){
  BrainRealtimeDirect::stop();
  Serial.println("[CALL] Manual USB stop requested");
  return;
 }
 if(cmd=="call start"){
  if(BrainRealtimeDirect::active()){Serial.println("[CALL] Already active");return;}
  if(BrainTTS::running)BrainTTS::interrupt();
  bool busy=BrainVoiceSTT::running || BrainAI::busy || BrainAudioTest::running ||
            BrainC5OTA::updating() || BrainTTS::running || BrainRealtimeAudio::active();
  if(!BrainRealtimeDirect::toggle(busy)){
   Serial.println("[CALL] USB start refused; run 'call diagnose' for exact safe reason");
   BrainRealtimeDirect::diagnose(busy);
  }
  return;
 }
 if(cmd=="ble bonds clear"){
  // Explicit USB-only recovery action, never triggered by Bluetooth.
  // Requires the phone to disconnect first; avoids wiping WiFi or C5 NVS.
  if(clientConnected){
   Serial.println("[S3] Disconnect iPhone before clearing Bluetooth bonds");
   return;
  }
#if defined(CONFIG_NIMBLE_ENABLED)
  int rc=ble_store_clear();
  Serial.printf("[S3] NimBLE bond store clear result=%d (0=success); restart S3 and re-pair iPhone\n",rc);
#else
  Serial.println("[S3] This build is not NimBLE; clear old iPhone bond and re-pair");
#endif
  return;
 }
 if(cmd=="status"){
  Serial.printf("[S3] face=%d BLE_client=%d paired=%d proxy=%d active=%u bad_frames=%lu queued=%u\n",
   faceOnline,clientConnected,bleAuthenticated,proxyEnabled,activeSeq,(unsigned long)frameReader.invalid,
   incomingCommands?(unsigned)uxQueueMessagesWaiting(incomingCommands):0);
  if(faceOnline){sendLink("GET_STATUS");sendRadioStatus(true);}
  Serial.printf("[S3] Brain WiFi %s, BLE client %s\n",
      brainWiFiOnline()?"ONLINE":"OFFLINE",clientConnected?"ON":"OFF");
  return;
 }
 if(cmd=="proxy on"||cmd=="ble on"){
  if(!faceOnline){Serial.println("[S3] Face offline; cannot enable proxy");return;}
  if(!bleAuthenticated){
   Serial.println("[S3] iPhone is not securely paired; proxy stays disabled");
   return;
  }
  proxyEnabled=true;proxyDeadline=0;
  Serial.println("[S3] Authenticated BLE proxy enabled for this connection");
  proxyResult("PROXY_READY");return;
 }
 if(cmd=="proxy off"||cmd=="ble off"){
  stopProxy();Serial.println("[S3] Proxy OFF");return;
 }
 if(!faceOnline){Serial.println("[S3] C5 offline");return;}
 if(cmd=="ping"){sendLink("PING");return;}
 if(cmd=="wifi status"){
  Serial.printf("[S3] Brain WiFi enabled=%d connected=%d, SSID=%s\n",
    wifiEnabled,brainWiFiOnline(),wifiSSID.c_str());
  return;
 }
 if(cmd=="battery"){sendLink("GET_BATTERY");return;}
 if(cmd.startsWith("msg ")){
  String v=cmd.substring(4);
  if(v.isEmpty()||v.length()>80||!CuteLink::fieldOk(v)){
   Serial.println("[S3] Use <=80 bytes simple text");return;
  }
  sendLink("TEXT",v);return;
 }
 if(cmd.startsWith("mascot ")||cmd.startsWith("mood ")){
  bool mascot=cmd.startsWith("mascot ");
  String n=cmd.substring(mascot?7:5);
  if(n.length()==1 && n[0]>='0' && n[0]<=(mascot?'5':'7')){
   sendLink(mascot?"MASCOT":"MOOD",n);return;
  }
 }
 Serial.println("[S3] Unknown command");
}
static void pollUSB(){
 for(int i=0;i<96&&Serial.available()>0;++i){
  int c=Serial.read();if(c<0)break;char ch=(char)c;
  if(ch=='\r')continue;
  if(ch=='\n'){
   usbLine[usbLen]=0;
   if(usbLen)consoleCommand(String(usbLine));
   usbLen=0;
  }else if(usbLen<sizeof(usbLine)-1)usbLine[usbLen++]=ch;
  else{usbLen=0;Serial.println("[S3] USB line too long");}
 }
}
// Local control is available only after encrypted-BLE provisioning.
// The key is persistent in the S3's NVS and never transmitted on LAN.
static int lanHex(char c){
 if(c>='0'&&c<='9')return c-'0';
 if(c>='a'&&c<='f')return c-'a'+10;
 if(c>='A'&&c<='F')return c-'A'+10;
 return -1;
}
static String lanEncode(const uint8_t *bytes,size_t n){
 const char*digits="0123456789abcdef";
 String out;out.reserve(n*2);
 for(size_t i=0;i<n;++i){out+=digits[bytes[i]>>4];out+=digits[bytes[i]&15];}
 return out;
}
static void initBrainLANSecret(){
 Preferences prefs;
 if(!prefs.begin("brainlan",false)){
  Serial.println("[S3] LAN key NVS unavailable; LAN control disabled");
  return;
 }
 lanSecret=prefs.getString("secret","");
 if(lanSecret.length()!=64)lanSecret="";
 for(size_t i=0;i<lanSecret.length();++i){
  if(lanHex(lanSecret[i])<0){lanSecret="";break;}
 }
 if(lanSecret.isEmpty()){
  uint8_t secretBytes[32];esp_fill_random(secretBytes,sizeof(secretBytes));
  lanSecret=lanEncode(secretBytes,sizeof(secretBytes));
  memset(secretBytes,0,sizeof(secretBytes));
  if(prefs.putString("secret",lanSecret)!=lanSecret.length())
    lanSecret="";
 }
 prefs.end();
 if(lanSecret.length()!=64)Serial.println("[S3] LAN key could not be persisted");
}
static bool verifyBrainLANHMAC(const String &hmac){
 if(lanSecret.length()!=64||lanNonce.length()!=32||hmac.length()!=64)return false;
 uint8_t secret[32]={0};
 for(int i=0;i<32;i++){
  int a=lanHex(lanSecret[i*2]),b=lanHex(lanSecret[i*2+1]);
  if(a<0||b<0)return false;
  secret[i]=(uint8_t)((a<<4)|b);
 }
 uint8_t expected[32]={0};
 const mbedtls_md_info_t *md=mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
 int ok=md?mbedtls_md_hmac(md,secret,sizeof(secret),
                (const uint8_t*)lanNonce.c_str(),lanNonce.length(),expected):-1;
 memset(secret,0,sizeof(secret));
 if(ok!=0)return false;
 uint8_t differences=0;
 for(int i=0;i<32;i++){
  int a=lanHex(hmac[i*2]),b=lanHex(hmac[i*2+1]);
  if(a<0||b<0){differences=1;continue;}
  differences|=(uint8_t)(expected[i]^((a<<4)|b));
 }
 memset(expected,0,sizeof(expected));
 return differences==0;
}
static void stopBrainLAN(){
 if(lanAwaitingCommand)cancelCommand("LAN_LINK_LOST");
 if(lanClient)lanClient.stop();
 lanAuthenticated=false;lanAwaitingCommand=false;
 lanNonce="";lanLineLen=0;
 if(lanListening){brainLAN.end();lanListening=false;}
 if(brainMDNS){MDNS.end();brainMDNS=false;}
}
static void handleBrainLANLine(const String &line){
 if(!lanClient)return;
 if(!lanAuthenticated){
  if(line.startsWith("AUTH ")&&verifyBrainLANHMAC(line.substring(5))){
   lanAuthenticated=true;lanNonce="";
   lanClient.println("OK");
   Serial.println("[S3] LAN authenticated");
  }else{
   lanClient.println("DENIED");lanClient.stop();
  }
  return;
 }
 if(line=="OTA_CAPS"){
  // Read-only inventory after HMAC authentication; never writes flash.
  const KittyOTASafety::Status ota=KittyOTASafety::inspect();
  const bool busy=BrainC5OTA::updating() || BrainRealtimeDirect::active() ||
     BrainRealtimeAudio::active() || BrainAI::busy || BrainVoiceSTT::running ||
     BrainTTS::running || BrainAudioTest::running;
  lanClient.printf("OTA:FW:%s\n",S3_FW_VERSION);
  lanClient.printf("OTA:RUNNING_SIZE:%lu\n",(unsigned long)ota.runningBytes);
  lanClient.printf("OTA:NEXT_SIZE:%lu\n",(unsigned long)ota.nextBytes);
  lanClient.printf("OTA:RUNNING_SUBTYPE:%u\n",(unsigned)ota.runningSubtype);
  lanClient.printf("OTA:BUSY:%u\n",busy?1:0);
  lanClient.println("OTA:DEPLOY_SUPPORTED:0");
  return;
 }
 if(line=="OTA_STATUS"){
  const KittyOTASafety::Status ota=KittyOTASafety::inspect();
  lanClient.printf("OTA:IMAGE_STATE:%u\n",(unsigned)ota.imageState);
  lanClient.printf("OTA:ROLLBACK_PENDING:%u\n",ota.rollbackPending?1:0);
  lanClient.printf("OTA:ROLLBACK_SUPPORTED:%u\n",ota.rollbackSupported?1:0);
  lanClient.println("OTA:TRANSFER_ENABLED:0");
  return;
 }
 if(line=="STATUS"){
  lanClient.println("N:LINK:1");
  lanClient.println("N:STATE:CONNECTED");
  lanClient.println("N:IP:"+WiFi.localIP().toString());
  lanClient.println("N:MODE:"+String(wifiDHCP?"DHCP":"STATIC"));
  lanClient.println("N:MASK:"+WiFi.subnetMask().toString());
  lanClient.println("N:GW:"+WiFi.gatewayIP().toString());
  lanClient.println("N:DNS:"+WiFi.dnsIP().toString());
  lanClient.println("N:RSSI:"+String(WiFi.RSSI()));
  return;
 }
 if(!line.startsWith("CMD ")){lanClient.println("NACK");return;}
 String command=line.substring(4);
 // LAN traffic is unencrypted: network credentials and IP changes are BLE-only.
 if(command.startsWith("W:")){lanClient.println("NACK:BLE_REQUIRED");return;}
 if(command.isEmpty()||command.length()>MAX_CMD){
  lanClient.println("NACK:INVALID_SIZE");return;
 }
 if(BrainC5OTA::updating()||lanAwaitingCommand||activeSeq||
    (incomingCommands&&uxQueueMessagesWaiting(incomingCommands))){
  lanClient.println("NACK:BUSY");return;
 }
 if(!faceOnline){lanClient.println("NACK:FACE_OFFLINE");return;}
 lanAwaitingCommand=true;
 acceptCommand(command);
}
static void pollBrainLAN(){
 if(!brainWiFiOnline()||lanSecret.length()!=64){
  if(lanListening||lanClient||brainMDNS)stopBrainLAN();
  return;
 }
 if(!lanListening){
  brainLAN.begin();
  lanListening=true;
  if(MDNS.begin("cutedisplay-brain")){
   MDNS.addService("cutedisplay","tcp",BRAIN_LAN_PORT);
   brainMDNS=true;
  }
  Serial.printf("[S3] Brain LAN listening %s:%u (Bonjour=%d)\n",
    WiFi.localIP().toString().c_str(),(unsigned)BRAIN_LAN_PORT,brainMDNS);
 }
 WiFiClient incoming=brainLAN.accept();
 if(incoming){
  IPAddress theirIP=incoming.remoteIP(),ourIP=WiFi.localIP(),mask=WiFi.subnetMask();
  bool sameSubnet=mask!=IPAddress(0,0,0,0);
  for(int j=0;j<4;++j)
   if((theirIP[j]&mask[j])!=(ourIP[j]&mask[j]))sameSubnet=false;
  if(!sameSubnet||lanAwaitingCommand){incoming.stop();}
  else{
   if(lanClient)lanClient.stop();
   lanClient=incoming;lanAuthenticated=false;
   lanLineLen=0;lanLastActivity=millis();
   uint8_t challenge[16];esp_fill_random(challenge,sizeof(challenge));
   lanNonce=lanEncode(challenge,sizeof(challenge));
   lanClient.println("CHALLENGE "+lanNonce);
  }
 }
 if(!lanClient)return;
 if(!lanClient.connected()||(uint32_t)(millis()-lanLastActivity)>45000UL){
  if(lanAwaitingCommand)cancelCommand("LAN_CLIENT_LOST");
  lanClient.stop();lanAuthenticated=false;lanNonce="";
  lanAwaitingCommand=false;lanLineLen=0;return;
 }
 int budget=256;
 while(budget-->0&&lanClient.available()){
  int value=lanClient.read();
  if(value<0)break;
  const char character=(char)value;lanLastActivity=millis();
  if(character=='\r')continue;
  if(character=='\n'){
   lanLine[lanLineLen]=0;
   if(lanLineLen)handleBrainLANLine(String(lanLine));
   lanLineLen=0;
   if(!lanClient)break;
  }else if((uint8_t)character<32||lanLineLen>=sizeof(lanLine)-1){
   lanClient.println("NACK");lanClient.stop();
   lanLineLen=0;break;
  }else lanLine[lanLineLen++]=character;
 }
}
void setup(){
 Serial.begin(115200);delay(250);
 Serial.printf("[S3 BOOT] reset_reason=%d free_internal=%lu min_internal=%lu free_psram=%lu\\n",
  (int)esp_reset_reason(),
  (unsigned long)heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
  (unsigned long)heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
  (unsigned long)heap_caps_get_free_size(MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
 Serial.printf("[S3] CuteDisplay Brain FW=%s\n",S3_FW_VERSION);
#if defined(CONFIG_NIMBLE_ENABLED)
 Serial.println("[S3] BLE host=NimBLE");
#elif defined(CONFIG_BLUEDROID_ENABLED)
 Serial.println("[S3] BLE host=Bluedroid");
#else
 Serial.println("[S3] BLE host=UNKNOWN");
#endif
 Serial1.setRxBufferSize(2048);
 Serial1.setTxBufferSize(2048);
 Serial1.begin(BrainPinPlan::UART_BAUD,SERIAL_8N1,BrainPinPlan::UART_RX,BrainPinPlan::UART_TX);
 BrainAI::init();
 KittyMemory::init();
 BrainRealtimeDirect::init();
 BrainTTS::init();
 BrainVoiceSTT::init();
 BrainClock::init();
 BrainAudioTest::loadLevels();
 Serial.printf("[S3] UART TX=%d RX=%d baud=%d\n",
    BrainPinPlan::UART_TX,BrainPinPlan::UART_RX,BrainPinPlan::UART_BAUD);
 incomingCommands=xQueueCreate(16,MAX_CMD+1);
 networkQueue=xQueueCreate(48,97);
 if(!incomingCommands||!networkQueue){
  Serial.println("[S3] ERROR: unable to allocate command/telemetry queues");
  return;
 }
 BLEDevice::init(BRAIN_NAME);
 BLEDevice::setMTU(185);
 BLESecurity *security=new BLESecurity();
 security->setCapability(ESP_IO_CAP_NONE);
 // iPhone reported peer-unspecified SMP failure 0x0508 on SC-only pairing.
 // Permit standard Just Works bonding for compatibility, but continue
 // requiring encryption on FFF1 and FFF6. This pairing has no MITM defense.
 security->setAuthenticationMode(true,false,false);
#if ESP_ARDUINO_VERSION >= ESP_ARDUINO_VERSION_VAL(3,3,12)
 // Allow iOS's encrypted FFF1 read to initiate the SMP exchange rather
 // than beginning it automatically while AccessorySetupKit is discovering.
 BLESecurity::setForceAuthentication(false);
 Serial.println("[S3] BLE profile: bonded Just Works, no SC-only requirement, on-demand SMP");
#else
 Serial.println("[S3] BLE core <3.3.12: forced pairing may still race; update ESP32 board package");
#endif
 Serial.printf("[S3] Arduino-ESP32 core %s\n",ESP_ARDUINO_VERSION_STR);
 BLEDevice::setSecurityCallbacks(new BrainSecurityCallbacks());
 BLEServer *server=BLEDevice::createServer();
 server->setCallbacks(new ServerEvents());
 BLEService *ctrl=server->createService("FFF0");
 controlChar=ctrl->createCharacteristic("FFF1",
   BLECharacteristic::PROPERTY_READ|BLECharacteristic::PROPERTY_WRITE|
   BLECharacteristic::PROPERTY_NOTIFY|
   BLECharacteristic::PROPERTY_READ_ENC|BLECharacteristic::PROPERTY_WRITE_ENC);
 // Bluedroid: encrypted read/write permissions. Just Works does not provide MITM.
 controlChar->setAccessPermissions(ESP_GATT_PERM_READ_ENCRYPTED|ESP_GATT_PERM_WRITE_ENCRYPTED);
 controlChar->setCallbacks(new CommandEvents());
#if defined(CONFIG_BLUEDROID_ENABLED)
 controlChar->addDescriptor(new BLE2902());
#endif
 controlChar->setValue("PROXY_DISABLED");ctrl->start();
 BLEService *bs=server->createService("180F");
 batteryChar=bs->createCharacteristic("2A19",BLECharacteristic::PROPERTY_READ|BLECharacteristic::PROPERTY_NOTIFY);
 uint8_t unknown=255;
#if defined(CONFIG_BLUEDROID_ENABLED)
 batteryChar->addDescriptor(new BLE2902());
#endif
 batteryChar->setValue(&unknown,1);bs->start();
 BLEService *ps=server->createService("FFF3");
 powerChar=ps->createCharacteristic("FFF4",BLECharacteristic::PROPERTY_READ|BLECharacteristic::PROPERTY_NOTIFY);
#if defined(CONFIG_BLUEDROID_ENABLED)
 powerChar->addDescriptor(new BLE2902());
#endif
 powerChar->setValue("0,0,0,0,0,0,0,0");ps->start();
 BLEService *ns=server->createService("FFF5");
 networkChar=ns->createCharacteristic("FFF6",
   BLECharacteristic::PROPERTY_READ|BLECharacteristic::PROPERTY_NOTIFY|
   BLECharacteristic::PROPERTY_READ_ENC);
 networkChar->setAccessPermissions(ESP_GATT_PERM_READ_ENCRYPTED);
#if defined(CONFIG_BLUEDROID_ENABLED)
 networkChar->addDescriptor(new BLE2902());
#endif
 networkChar->setValue("N:LINK:0");ns->start();
 BLEAdvertising *ad=BLEDevice::getAdvertising();
 ad->addServiceUUID(BLEUUID("FFF0"));
 ad->addServiceUUID(BLEUUID("180F"));
 ad->setScanResponse(true);
 BLEDevice::startAdvertising();
 Serial.println("[S3] Encrypted FFF1 writes; relay activates automatically once BLE pairs");
 // Start BLE before WiFi (avoids radio/heap fragmentation during BLE init).
 WiFi.onEvent(onBrainWiFiEvent);
 initBrainLANSecret();
 restoreBrainWiFi();
 if(wifiEnabled)startBrainWiFi();
 else WiFi.mode(WIFI_OFF);
}
void loop(){
 static bool bootChirpDone=false;
 if(!bootChirpDone && millis()>4500 && !BrainAudioTest::running && !BrainC5OTA::updating() && !BrainRealtimeDirect::active() && !BrainRealtimeAudio::active()){
  bootChirpDone=true;
  BrainAudioTest::beep(false);
 }
 BrainC5OTA::permitUpdate=!activeSeq && !lanAwaitingCommand &&
    !BrainRealtimeDirect::active() && !BrainRealtimeAudio::active() &&
    incomingCommands && uxQueueMessagesWaiting(incomingCommands)==0;
 pollFace();
 BrainC5OTA::tick(Serial1,faceOnline);
 static bool voiceWasCapturing=false;
 if(BrainVoiceSTT::capturing)voiceWasCapturing=true;
 else if(voiceWasCapturing){
  voiceWasCapturing=false;
  if(BrainVoiceSTT::running)proxyResult("AI:STATUS:VOICE_UPLOADING");
 }
 BrainVoiceSTT::Result voiceResult={};
 if(BrainVoiceSTT::take(voiceResult)){
  if(voiceResult.ok){
   proxyResult("AI:STATUS:TRANSCRIBED");
   if(!BrainAI::startWithPrompt(String(voiceResult.text)))
    proxyResult("AI:STATUS:VOICE_BUSY");
  }else{
   Serial.printf("[VOICE] Error: %s\n",voiceResult.error);
   proxyResult("AI:STATUS:VOICE_ERROR");
  }
 }
 BrainAI::tick(Serial1,faceOnline && !BrainC5OTA::updating() && !activeSeq);
 // SD status updates are tiny and do not block audio or SD I/O.
 static uint8_t lastCardState=255;
 uint8_t cardState=KittyMemory::status();
 if(cardState!=lastCardState && faceOnline && !BrainC5OTA::updating()){
  CuteLink::send(Serial1,++brainActivitySeq,"SD_STATE",String((int)cardState));
  lastCardState=cardState;
 }

 // Capacity comes from cached SD worker readings; no card I/O on loop/audio.
 static uint32_t lastSDUsageSend=0;
 if(faceOnline && !BrainC5OTA::updating() &&
    ((uint32_t)(millis()-lastSDUsageSend)>=15000UL || lastSDUsageSend==0)){
  lastSDUsageSend=millis();
  String usage=String((unsigned long)KittyMemory::usedKB())+":"+
               String((unsigned long)KittyMemory::capacityKB());
  CuteLink::send(Serial1,++brainActivitySeq,"SD_USAGE",usage);
 }
 // Notify C5 once per successfully persisted, changed structured memory.
 static uint32_t lastMemoryNotice=0;
 uint32_t newNotice=KittyMemory::memorizedNoticeSeq;
 if(newNotice!=lastMemoryNotice && faceOnline && !BrainC5OTA::updating()){
  lastMemoryNotice=newNotice;
  CuteLink::send(Serial1,++brainActivitySeq,"FACT_SAVED","1");
 }
 BrainRealtimeDirect::tick(BrainVoiceSTT::running || BrainTTS::running ||
                           BrainAudioTest::running || BrainC5OTA::updating());
 // Face Control is a lightweight S3->C5 UART side channel; the 24kHz I2S
 // Core 0 task never draws, transmits UART, or performs extra network work.
 if(faceOnline && !BrainC5OTA::updating() && BrainRealtimeDirect::active()){
  String caption;
  if(BrainRealtimeDirect::takeCaption(caption)){
   CuteLink::send(Serial1,++brainActivitySeq,"CALL_TEXT",caption);
  }
  uint8_t emotion=1;
  if(BrainRealtimeDirect::takeMood(emotion)){
   CuteLink::send(Serial1,++brainActivitySeq,"CALL_MOOD",String((int)emotion));
  }
  static uint32_t lastLipFrame=0;
  static int previousLip=-1;
  uint32_t faceNow=millis();
  if((uint32_t)(faceNow-lastLipFrame)>=125UL){
   lastLipFrame=faceNow;
   int next=BrainRealtimeDirect::activity()=="CALL_SPEAKING"?
            (int)BrainRealtimeAudio::lipLevel():0;
   if(previousLip!=next){
    CuteLink::send(Serial1,++brainActivitySeq,"CALL_LIP",String(next));
    previousLip=next;
   }
  }
 }
 if(pendingC5VoiceStart && !BrainTTS::running &&
    !BrainRealtimeDirect::active() && !BrainRealtimeAudio::active()){
  pendingC5VoiceStart=false;
  if(!BrainC5OTA::updating() && !BrainAudioTest::running && !BrainVoiceSTT::running && !BrainAI::busy)
   BrainVoiceSTT::start();
 }
 // The optional Ollama memory pass is strictly inactive throughout Call Mode
 // and every normal STT/AI/TTS turn. It runs only after 20 seconds idle.
 BrainMemoryAI::tick(BrainRealtimeDirect::active() || BrainRealtimeAudio::active() ||
  BrainVoiceSTT::running || BrainVoiceSTT::capturing || BrainAI::busy ||
  BrainTTS::running || BrainAudioTest::running || BrainC5OTA::updating() ||
  pendingC5VoiceStart);
 BrainTTS::tick(BrainVoiceSTT::running || BrainAudioTest::running || BrainC5OTA::updating() || BrainAI::busy ||
                BrainRealtimeDirect::active() || BrainRealtimeAudio::active());
 static String priorActivity;
 static uint32_t lastActivitySend=0;
 // A failed realtime call is not an active call and MUST NOT mask the
 // original long-press PTT status. Show Call error only transiently while
 // idle, then give the HUD back to manual STT/AI/TTS.
 static bool callErrorWasVisible=false;
 static uint32_t callErrorAt=0;
 const bool callError=BrainRealtimeDirect::activity()=="CALL_ERROR";
 if(callError && !callErrorWasVisible)callErrorAt=millis();
 callErrorWasVisible=callError;
 const bool showCallError=callError && (uint32_t)(millis()-callErrorAt)<3000UL;
 String activity=BrainRealtimeDirect::active()?BrainRealtimeDirect::activity()
   :BrainVoiceSTT::capturing?"LISTENING":BrainVoiceSTT::running?"UPLOADING"
   :BrainAI::busy?"THINKING":BrainTTS::running?"SPEAKING"
   :showCallError?"CALL_ERROR":"";
 if((activity!=priorActivity || forceActivityResend ||
     millis()-lastActivitySend>=15000UL) &&
    faceOnline && !BrainC5OTA::updating()){
  CuteLink::send(Serial1,++brainActivitySeq,"ACTIVITY",activity);
  priorActivity=activity;
  forceActivityResend=false;
  lastActivitySend=millis();
 }
 // Status notifications are separate from command acknowledgements.
 String aiEvent;
 for(int i=0;i<4 && BrainAI::takeStatus(aiEvent);i++){
  if(clientConnected && bleAuthenticated)proxyResult(aiEvent);
 }

 pollUSB();
 updateBrainWiFi();
 BrainClock::tick(brainWiFiOnline());
 BrainClock::sendDisplay(Serial1,faceOnline && !BrainC5OTA::updating() && !BrainAI::pending && !activeSeq);
 pollBrainLAN();
 if(connectPending){
  connectPending=false;clientConnected=true;
  bleAuthenticated=false;
  encryptedControlReadSeen=false;
  if(controlChar)controlChar->setValue("PAIRING_PENDING");
  // Do not clear pairingOK: onConnect() can finish security before loop().
  Serial.println("[S3] BLE connected; awaiting encrypted FFF1 read and bonding");
  bleDropNotReady=false;bleDropFull=false;
  sendRadioStatus(true);
 }
 if(disconnectPending){
  disconnectPending=false;clientConnected=false;
  bleAuthenticated=false;pairingOK=false;pairingFailed=false;
  encryptedControlReadSeen=false;
  stopProxy();
  if(controlChar)controlChar->setValue("PROXY_DISABLED");
  bleDropNotReady=false;bleDropFull=false;
  if(networkQueue)xQueueReset(networkQueue);
  BLEDevice::startAdvertising();
  sendRadioStatus(true);
  Serial.println("[S3] BLE disconnected; proxy gate closed");
 }
 if(pairingOK || (encryptedControlReadSeen && clientConnected)){
  bool viaRead=encryptedControlReadSeen;
  encryptedControlReadSeen=false;
  pairingOK=false;
  bleAuthenticated=true;
  proxyEnabled=true;proxyDeadline=0; // Session-scoped, no USB command needed.
  Serial.printf("[S3] BLE session authenticated; relay READY (encrypted-read=%d)\n",viaRead?1:0);
  proxyResult("PROXY_READY");
  networkInfo("LINK");
  networkInfo("STATE");
  networkInfo("IP");
  networkInfo("KEY");
  sendRadioStatus(true);
 }
 if(pairingFailed){
  pairingFailed=false;
  bleAuthenticated=false;
  stopProxy();
  if(controlChar)controlChar->setValue("PAIRING_FAILED");
  Serial.printf("[S3] BLE pairing FAILED: host_status=%u (0x%04X) bluedroid_reason=%u\n",
     (unsigned)pairingFailureStatus,(unsigned)pairingFailureStatus,
     (unsigned)pairingFailureReason);
  if(pairingFailureStatus==0x0508){
   Serial.println("[S3] NimBLE 0x0508: unspecified peer SMP failure (bond compatibility test not yet verified).");
  }
 }
 pollBLECommands();
 pollNetwork();
 delay(5);
}
