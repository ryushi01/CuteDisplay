/*
 CuteDisplay ESP32-S3 Brain — Phase 1 UART test and BLE diagnostic.
 Board target: Freenove ESP32-S3-CAM N16R8, Arduino-ESP32 3.x.
 UART diagnostics are now included. Pins and frames have not been bench-tested.
 I2S/AI/camera and iPhone BLE command forwarding are NOT implemented.
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

// Keep all application processing in loop(), never in a BLE callback.
// Future versions will forward validated frames through a wired UART bridge.
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
static void toC5(const char *type,const String &value=""){
 if(!CuteLink::send(Serial1,++s3Seq,type,value))Serial.println("[S3] Invalid UART payload");
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
 }
 uint32_t now=millis();
 if(c5Online&&(uint32_t)(now-lastC5)>10000UL){
  c5Online=false;Serial.println("[S3] C5 UART timed out");
 }
 if(!c5Online&&(uint32_t)(now-lastHello)>2000UL){
  lastHello=now;toC5("HELLO","S3");
 }
}
static void runConsole(String cmd) {
 cmd.trim();
 if(cmd=="help"){
  Serial.println("[S3] help status hello ping battery msg <ASCII> mood <0-7> mascot <0-5>");
  return;
 }
 if(cmd=="status"){
  Serial.printf("[S3] online=%d BLE_client=%d invalid_frames=%lu\n",
    c5Online?1:0,clientConnected?1:0,(unsigned long)c5Reader.invalid);
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
  Serial.println("[S3] UART diagnostics only. Audio, AI, camera and phone migration INACTIVE");
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
  controlCharacteristic->setValue("S3_DEV_UART_NOT_READY");
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

  if (controlQueue) {
    char packet[MAX_CMD_BYTES + 1] = {};
    for (int i = 0; i < 4 && xQueueReceive(controlQueue, packet, 0) == pdTRUE; ++i) {
      // This is explicitly a diagnostic sink, NOT an implemented UART bridge.
      Serial.print("[S3] Received BLE command (not forwarded): ");
      Serial.println(packet);
      if (controlCharacteristic) {
        controlCharacteristic->setValue("UART_NOT_READY");
        if (clientConnected) controlCharacteristic->notify();
      }
    }
  }
  delay(10);
}
