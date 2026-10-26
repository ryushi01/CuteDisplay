/*
 CuteDisplay ESP32-S3 Brain — Phase 2 opt-in BLE-to-C5 diagnostic relay.
 Board target: Freenove ESP32-S3-CAM N16R8, Arduino-ESP32 3.x.
 UART HELLO/status/text path was verified on both boards.
 New USB-opt-in diagnostic BLE relay is LIMITED and untested.
 I2S/AI/camera and native iPhone pairing migration are NOT implemented.
 Do not flash this sketch to the LILYGO T-Display-C5.
*/
#include <Arduino.h>
#include "BrainPinPlan.h"
#include "CuteLink.h"
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLEAdvertising.h>

static constexpr char BRAIN_NAME[] = "CuteDisplay-Brain-DEV";
static constexpr char CONTROL_SERVICE[] = "FFF0";
static constexpr char CONTROL_CHAR[] = "FFF1";
static constexpr size_t MAX_CMD_BYTES = 96;

// Keep callbacks fast: process and validate BLE writes in loop(), never onWrite.
// Only harmless cosmetic commands are supported, with USB enable gate.
static QueueHandle_t controlQueue = nullptr;
static BLECharacteristic *controlCharacteristic = nullptr;
static bool clientConnected = false;
static volatile bool pendingConnect = false;
static volatile bool pendingDisconnect = false;

class BrainServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer *) override { pendingConnect = true; }
  void onDisconnect(BLEServer *) override { pendingDisconnect = true; }
};

class BrainCommandCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *characteristic) override {
    const String command = characteristic->getValue();
    if (command.length() == 0 || command.length() > MAX_CMD_BYTES || !controlQueue) return;
    char packet[MAX_CMD_BYTES + 1] = {};
    memcpy(packet, command.c_str(), command.length());
    // Queue full means command is dropped, never silently applied to a display.
    xQueueSend(controlQueue, packet, 0);
  }
};

// Serial=USB debug; Serial1=UART to C5; legacy BLE is diagnostic-only.
static CuteLink::Reader c5Reader;
static bool c5Online=false;
static uint16_t s3Seq=0;
static uint32_t lastC5=0,lastHello=0;
static char consoleBuffer[112]={};
static size_t consoleLen=0;
static constexpr uint32_t BLE_TEST_WINDOW_MS=300000UL;
static bool bleTestEnabled=false; // Disabled at boot; requires USB Serial command.
static uint32_t bleTestDeadline=0;
static uint16_t blePendingSeq=0; // One command in flight, no blind retries.
static uint32_t blePendingAt=0;
static uint16_t toC5(const char *type,const String &value=""){
 uint16_t seq=++s3Seq;
 if(!seq)seq=++s3Seq;
 if(!CuteLink::send(Serial1,seq,type,value)){
  Serial.println("[S3] Invalid UART payload");return 0;
 }
 return seq;
}
static void bleReply(const String &result){
 if(!controlCharacteristic)return;
 controlCharacteristic->setValue(result.c_str());
 if(clientConnected)controlCharacteristic->notify();
}
static void bleCloseGate(){
 bleTestEnabled=false;bleTestDeadline=0;
 if(controlQueue)xQueueReset(controlQueue);
}
// The diagnostic service has no enforced link authentication. Reject anything
// outside a small harmless allowlist (especially credentials and power commands).
static bool decodeSafeBle(String command,String &kind,String &value){
 if(command.length()==3&&command.startsWith("C:")&&command[2]>='0'&&command[2]<='5'){
  kind="MASCOT";value=command.substring(2);return true;
 }
 if(command.length()==3&&command.startsWith("M:")&&command[2]>='0'&&command[2]<='7'){
  kind="MOOD";value=command.substring(2);return true;
 }
 if(command.isEmpty()||command.length()>80)return false;
 for(size_t i=0;i<command.length();++i){
  uint8_t c=(uint8_t)command[i];
  if(c<32||c>126||c==':'||c=='|')return false;
 }
 kind="TEXT";value=command;return true;
}

static void serviceC5() {
 CuteLink::Frame f;
 for(int i=0;i<4&&c5Reader.poll(Serial1,f);++i){
  lastC5=millis();
  if(!c5Online)Serial.println("[S3] C5 UART connected");
  c5Online=true;
  if(f.type=="HELLO"){
    CuteLink::send(Serial1,f.seq,"ACK","HELLO");
    Serial.println("[C5] HELLO");
  }else Serial.printf("[C5] seq=%u %s %s\n",f.seq,f.type.c_str(),f.payload.c_str());
  if(blePendingSeq&&f.seq==blePendingSeq&&(f.type=="ACK"||f.type=="NACK")){
   Serial.printf("[S3] BLE relay result: %s %s\n",f.type.c_str(),f.payload.c_str());
   bleReply(String(f.type=="ACK"?"ACK:":"NACK:")+f.payload);
   blePendingSeq=0;
  }
 }
 uint32_t now=millis();
 if(c5Online&&(uint32_t)(now-lastC5)>10000UL){
  c5Online=false;Serial.println("[S3] C5 UART timed out");
 }
 if(blePendingSeq&&(uint32_t)(now-blePendingAt)>3000UL){
  blePendingSeq=0;
  Serial.println("[S3] BLE relay UART ACK timed out; no retry");
  bleReply("ERROR:UART_TIMEOUT");
 }
 if(bleTestEnabled&&(int32_t)(now-bleTestDeadline)>=0){
  bleCloseGate();
  Serial.println("[S3] BLE test relay expired (5 minutes)");
  bleReply("DISABLED");
 }
 if(!c5Online&&(uint32_t)(now-lastHello)>2000UL){
  lastHello=now;toC5("HELLO","S3");
 }
}
static void runConsole(String cmd) {
 cmd.trim();
 if(cmd=="help"){
  Serial.println("[S3] help status hello ping battery msg <ASCII> mood <0-7> mascot <0-5> ble on ble off");
  return;
 }
 if(cmd=="ble on"){
  if(!c5Online){Serial.println("[S3] C5 offline; BLE test cannot enable");return;}
  bleTestEnabled=true;bleTestDeadline=millis()+BLE_TEST_WINDOW_MS;
  Serial.println("[S3] BLE test relay enabled for 5 minutes (unsecured test only)");
  bleReply("TEST_READY");return;
 }
 if(cmd=="ble off"){
  bleCloseGate();Serial.println("[S3] BLE test relay disabled");
  bleReply("DISABLED");return;
 }
 if(cmd=="status"){
  Serial.printf("[S3] online=%d BLE_client=%d BLE_test=%d pending=%u invalid_frames=%lu\n",
    c5Online?1:0,clientConnected?1:0,bleTestEnabled?1:0,blePendingSeq,
    (unsigned long)c5Reader.invalid);
  if(c5Online)toC5("GET_STATUS");
  return;
 }
 if(cmd=="hello"){toC5("HELLO","S3");return;}
 if(!c5Online){Serial.println("[S3] C5 offline; check crossed TX/RX and GND");return;}
 if(cmd=="ping"){toC5("PING");return;}
 if(cmd=="battery"){toC5("GET_BATTERY");return;}
 if(cmd.startsWith("msg ")){
  String value=cmd.substring(4);
  if(value.isEmpty()||value.length()>80||!CuteLink::fieldOk(value)){
    Serial.println("[S3] Text must be 1-80 ASCII bytes without pipes/newlines");return;
  }
  for(size_t i=0;i<value.length();++i)
   if((uint8_t)value[i]>127){Serial.println("[S3] Japanese/Unicode not available yet");return;}
  toC5("TEXT",value);return;
 }
 bool isMood=cmd.startsWith("mood "),isMascot=cmd.startsWith("mascot ");
 if(isMood||isMascot){
  String value=cmd.substring(isMood?5:7);
  if(value.length()!=1||value[0]<'0'||value[0]>(isMood?'7':'5')){
    Serial.println("[S3] Invalid mood/mascot index");return;
  }
  toC5(isMood?"MOOD":"MASCOT",value);return;
 }
 Serial.println("[S3] Unknown command; enter help");
}
static void serviceConsole() {
 for(int i=0;i<96&&Serial.available()>0;++i){
  int x=Serial.read();if(x<0)break;char ch=(char)x;
  if(ch=='\r')continue;
  if(ch=='\n'){
   consoleBuffer[consoleLen]=0;
   if(consoleLen)runConsole(String(consoleBuffer));
   consoleLen=0;
  }else if(consoleLen<sizeof(consoleBuffer)-1)consoleBuffer[consoleLen++]=ch;
  else {consoleLen=0;Serial.println("[S3] Console line too long");}
 }
}

void setup() {
  Serial.begin(115200);
  delay(250);
  Serial.println("[S3] CuteDisplay brain development bootstrap");
  Serial.println("[S3] Phase 2 opt-in BLE test; audio/AI/camera/iPhone migration INACTIVE");
  Serial.printf("[S3] UART TX=%d RX=%d, I2S BCLK=%d WS=%d DIN=%d DOUT=%d (I2S INACTIVE)\n",
    BrainPinPlan::UART_TX, BrainPinPlan::UART_RX,
    BrainPinPlan::I2S_BCLK, BrainPinPlan::I2S_WS,
    BrainPinPlan::I2S_DIN, BrainPinPlan::I2S_DOUT);
  Serial1.begin(BrainPinPlan::UART_BAUD, SERIAL_8N1, BrainPinPlan::UART_RX, BrainPinPlan::UART_TX);
  Serial.println("[S3] UART1 started for C5; USB console: Newline + help");
  controlQueue = xQueueCreate(16, MAX_CMD_BYTES + 1);
  if (!controlQueue) {
    Serial.println("[S3] Fatal: cannot allocate BLE command queue");
    return;
  }

  BLEDevice::init(BRAIN_NAME);
  BLEServer *server = BLEDevice::createServer();
  server->setCallbacks(new BrainServerCallbacks());
  BLEService *control = server->createService(CONTROL_SERVICE);
  controlCharacteristic = control->createCharacteristic(
    CONTROL_CHAR,
    BLECharacteristic::PROPERTY_READ |
    BLECharacteristic::PROPERTY_WRITE |
    BLECharacteristic::PROPERTY_NOTIFY
  );
  controlCharacteristic->setCallbacks(new BrainCommandCallbacks());
  controlCharacteristic->setValue("BLE_TEST_DISABLED");
  control->start();
  BLEAdvertising *advertising = BLEDevice::getAdvertising();
  advertising->addServiceUUID(CONTROL_SERVICE);
  advertising->setScanResponse(true);
  BLEDevice::startAdvertising();
  Serial.println("[S3] Advertises CuteDisplay-Brain-DEV / service FFF0, char FFF1");
}

void loop() {
  serviceC5();
  serviceConsole();
  if (pendingConnect) {
    pendingConnect = false;
    clientConnected = true;
    Serial.println("[S3] BLE client connected");
  }
  if (pendingDisconnect) {
    pendingDisconnect = false;
    clientConnected = false;
    BLEDevice::startAdvertising();
    Serial.println("[S3] BLE client disconnected; advertising restarted");
  }

  // One BLE write at a time. Never print raw BLE data (could be a password).
  if(controlQueue && blePendingSeq==0){
   char packet[MAX_CMD_BYTES+1]={};
   if(xQueueReceive(controlQueue,packet,0)==pdTRUE){
    String kind,payload;
    if(!bleTestEnabled){
     Serial.println("[S3] BLE write blocked: test gate closed");
     bleReply("ERROR:DISABLED");
    }else if(!c5Online){
     Serial.println("[S3] BLE write blocked: C5 offline");
     bleReply("ERROR:C5_OFFLINE");
    }else if(!decodeSafeBle(String(packet),kind,payload)){
     Serial.println("[S3] BLE write rejected: test-only command allowlist");
     bleReply("ERROR:TEST_ONLY");
    }else{
     uint16_t seq=toC5(kind.c_str(),payload);
     if(seq){
      blePendingSeq=seq;blePendingAt=millis();
      Serial.printf("[S3] BLE test forwarded %s seq=%u\n",kind.c_str(),seq);
      bleReply("SENT:"+String(seq));
     }else bleReply("ERROR:FRAME");
    }
   }
  }
  delay(10);
}
