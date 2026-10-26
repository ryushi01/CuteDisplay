/*
 CuteDisplay S3 Brain — Phase 3: encrypted BLE / segmented UART relay beta.
 This is a bench-test build, NOT production authorization: Just Works pairing
 provides encryption/bonding but no MITM protection. USB opt-in required.
 Retains original C5 recovery BLE and proven UART GPIO wiring.
*/
#include <Arduino.h>
#include <WiFi.h>
#include <Preferences.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLEAdvertising.h>
#include <BLESecurity.h>
// BLECharacteristic.h (included by the Arduino BLE library) provides
// ESP_GATT_PERM_* access permission constants on Arduino-ESP32 3.x.
// Do not include the ESP-IDF-internal esp_gatt_defs.h directly.
#include "BrainPinPlan.h"
#include "CuteLink.h"

static constexpr char BRAIN_NAME[]="CuteDisplay-Brain-DEV";
static constexpr size_t MAX_CMD=96;
static constexpr int SEG_BYTES=38;
static constexpr uint32_t PROXY_WINDOW_MS=600000UL;
static BLECharacteristic *controlChar=nullptr,*batteryChar=nullptr,*powerChar=nullptr,*networkChar=nullptr;
static bool clientConnected=false;
static bool wifiEnabled=false,wifiDHCP=true,wifiConnecting=false;
static String wifiSSID,wifiPassword,staticIP,staticMask,staticGateway,staticDNS;
static uint32_t wifiStarted=0,nextWiFiAttempt=0,lastWiFiPoll=0,lastRadioSent=0;
static bool priorWifiConnected=false;
static IPAddress configuredIP,configuredMask,configuredGateway,configuredDNS;

static volatile bool connectPending=false,disconnectPending=false;
static QueueHandle_t incomingCommands=nullptr,networkQueue=nullptr;
static bool proxyEnabled=false,faceOnline=false;
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

class ServerEvents:public BLEServerCallbacks{
 void onConnect(BLEServer*)override{connectPending=true;}
 void onDisconnect(BLEServer*)override{disconnectPending=true;}
};
class CommandEvents:public BLECharacteristicCallbacks{
 void onWrite(BLECharacteristic *c)override{
  String v=c->getValue();
  if(!incomingCommands||v.isEmpty()||v.length()>MAX_CMD)return;
  for(size_t i=0;i<v.length();++i)if(v[i]=='\0')return;
  char row[MAX_CMD+1]={};
  memcpy(row,v.c_str(),v.length());
  if(xQueueSend(incomingCommands,row,0)!=pdTRUE)
    Serial.println("[S3] WARNING: command queue full; BLE write not delivered");
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
 if(!controlChar)return;
 controlChar->setValue(value.c_str());
 if(clientConnected)controlChar->notify();
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
 cancelCommand("PROXY_OFF");
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
 if(!networkQueue||v.length()>96)return;
 char item[97]={};
 memcpy(item,v.c_str(),v.length());
 if(xQueueSend(networkQueue,item,0)!=pdTRUE)
  Serial.println("[S3] Network telemetry queue full");
}
static void sendRadioStatus(bool immediate);
static void processFace(const CuteLink::Frame &f){
 lastFace=millis();
 if(!faceOnline)Serial.println("[S3] C5 UART connected");
 faceOnline=true;
 if(f.type=="HELLO"){
  if(activeSeq)cancelCommand("FACE_RESTART");
  sendRadioStatus(true);
  CuteLink::send(Serial1,f.seq,"ACK","HELLO");
  Serial.println("[C5] HELLO");
 } else if(f.type=="POWER"){
  reportPower(f.payload);
 } else if(f.type=="NET"){
  // C5 radios are disabled; ignore any stale C5 radio telemetry.
 } else if(f.type=="BATTERY"){
  Serial.printf("[C5] BATTERY %s\n",f.payload.c_str());
 } else if(f.type=="STATUS"){
  Serial.printf("[C5] STATUS %s\n",f.payload.c_str());
 } else if(f.type=="LOG"){
  Serial.printf("[C5] LOG %s\n",f.payload.c_str());
 } else if(f.type=="ACK"||f.type=="NACK"){
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
static bool brainWiFiOnline(){
 return wifiEnabled && WiFi.status()==WL_CONNECTED;
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
 if(!wifiDHCP){
  IPAddress ip,mask,gw,dns;
  if(ip.fromString(staticIP)&&mask.fromString(staticMask)&&
     gw.fromString(staticGateway)&&dns.fromString(staticDNS))
   WiFi.config(ip,gw,mask,dns);
 }
 WiFi.begin(wifiSSID.c_str(),wifiPassword.c_str());
 wifiConnecting=true;wifiStarted=millis();
 Serial.println("[S3] Brain WiFi connection started");
}
static void stopBrainWiFi(){
 WiFi.disconnect(true,false);
 WiFi.mode(WIFI_OFF);
 wifiConnecting=false;nextWiFiAttempt=0;
}
static void networkInfo(const String &field){
 if(!clientConnected)return;
 if(field=="LINK"){pushNetwork(String("N:LINK:")+(brainWiFiOnline()?"1":"0"));return;}
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
 if(cmd.startsWith("W:S:")){
  String v=cmd.substring(4);
  if(v.length()>0&&v.length()<=32)wifiSSID=v;
 }else if(cmd.startsWith("W:P:")){
  String v=cmd.substring(4);
  if(v.length()<=63)wifiPassword=v;
 }else if(cmd=="W:C"||cmd=="W:ON"){
  wifiEnabled=!wifiSSID.isEmpty();
  persistBrainWiFi();
  stopBrainWiFi();
  if(wifiEnabled)startBrainWiFi();
 }else if(cmd=="W:OFF"){
  wifiEnabled=false;persistBrainWiFi();stopBrainWiFi();
 }else if(cmd=="W:FORGET"){
  wifiEnabled=false;stopBrainWiFi();
  wifiSSID="";wifiPassword="";persistBrainWiFi();
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
 }else if(cmd.startsWith("W:GET:")){
  // No S3 LAN fallback server/token exists yet. Never reuse C5 LAN token.
  networkInfo(cmd.substring(6));
 }else if(cmd.startsWith("W:PING:")){
  // Ping support deferred: state is emitted as NO_WIFI or UNSUPPORTED.
  pushNetwork(brainWiFiOnline()?"N:PING:INVALID":"N:PING:NO_WIFI");
 }
 return true;
}
static void updateBrainWiFi(){
 uint32_t now=millis();
 if((uint32_t)(now-lastWiFiPoll)<500UL)return;
 lastWiFiPoll=now;
 bool online=brainWiFiOnline();
 if(online){wifiConnecting=false;nextWiFiAttempt=0;}
 if(wifiConnecting && !online && (uint32_t)(now-wifiStarted)>12000UL){
  wifiConnecting=false;
  WiFi.disconnect(false,false);
  nextWiFiAttempt=now+20000UL;
  Serial.println("[S3] Brain WiFi connect timed out; next retry later");
 }
 if(wifiEnabled && !online && !wifiConnecting &&
     nextWiFiAttempt && (int32_t)(now-nextWiFiAttempt)>=0){
  nextWiFiAttempt=0;startBrainWiFi();
 }
 if(online!=priorWifiConnected){
  priorWifiConnected=online;
  Serial.printf("[S3] Brain WiFi %s\n",online?"CONNECTED":"DISCONNECTED");
  networkInfo("LINK");
 }
}
static void sendRadioStatus(bool immediate){
 uint32_t now=millis();
 if(!faceOnline || (!immediate && (uint32_t)(now-lastRadioSent)<1800UL))return;
 lastRadioSent=now;
 String packet=String("b=")+(clientConnected?"1":"0")+
              ";w="+(brainWiFiOnline()?"1":"0")+
              ";ip="+(brainWiFiOnline()?WiFi.localIP().toString():String("-"));
 sendLink("RADIO",packet);
}

static void pollFace(){
 CuteLink::Frame f;
 for(int i=0;i<8 && frameReader.poll(Serial1,f);++i)processFace(f);
 uint32_t now=millis();
 if(faceOnline&&(uint32_t)(now-lastFace)>10000UL){
  faceOnline=false;
  Serial.println("[S3] Face UART timed out");
  cancelCommand("LINK_LOST");
 }
 if(!faceOnline&&(uint32_t)(now-lastHello)>=2000UL){
  lastHello=now;sendLink("HELLO","S3");
 }
 if(faceOnline&&(uint32_t)(now-lastHeartbeat)>=3000UL){
  lastHeartbeat=now;sendLink("HEARTBEAT");
 }
 sendRadioStatus(false);
 if(activeSeq&&(uint32_t)(now-chunkSentAt)>1200UL){
  if(retryCount<2){
   ++retryCount;
   Serial.println("[S3] Retrying UART chunk after ACK timeout");
   sendChunk(true);
  }else cancelCommand("UART_TIMEOUT");
 }
 if(proxyEnabled&&(int32_t)(now-proxyDeadline)>=0){
  stopProxy();Serial.println("[S3] Proxy test window expired");
 }
}
static void pollNetwork(){
 if(!clientConnected||!networkQueue||!networkChar)return;
 if((uint32_t)(millis()-lastNetSent)<50UL)return;
 char item[97]={};
 if(xQueueReceive(networkQueue,item,0)==pdTRUE){
  lastNetSent=millis();
  networkChar->setValue(item);
  networkChar->notify();
 }
}
static void pollBLECommands(){
 if(!incomingCommands || activeSeq || !proxyEnabled)return;
 char item[MAX_CMD+1]={};
 if(xQueueReceive(incomingCommands,item,0)!=pdTRUE)return;
 if(!faceOnline){proxyResult("ERR:FACE_OFFLINE");return;}
 String incoming(item);
 if(controlBrainWiFi(incoming)){
  proxyResult("ACK:WIFI");
  return;
 }
 acceptCommand(incoming);
}
static void consoleCommand(String cmd){
 cmd.trim();
 if(cmd=="help"){
  Serial.println("[S3] help status ping battery msg <text> mascot <0-5> mood <0-7> proxy on proxy off");
  return;
 }
 if(cmd=="status"){
  Serial.printf("[S3] face=%d BLE_client=%d proxy=%d active=%u bad_frames=%lu queued=%u\n",
   faceOnline,clientConnected,proxyEnabled,activeSeq,(unsigned long)frameReader.invalid,
   incomingCommands?(unsigned)uxQueueMessagesWaiting(incomingCommands):0);
  if(faceOnline){sendLink("GET_STATUS");sendRadioStatus(true);}
  Serial.printf("[S3] Brain WiFi %s, BLE client %s\n",
      brainWiFiOnline()?"ONLINE":"OFFLINE",clientConnected?"ON":"OFF");
  return;
 }
 if(cmd=="proxy on"||cmd=="ble on"){
  if(!faceOnline){Serial.println("[S3] Face offline; cannot enable proxy");return;}
  proxyEnabled=true;proxyDeadline=millis()+PROXY_WINDOW_MS;
  Serial.println("[S3] Encrypted BLE proxy test ENABLED for 10 minutes");
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
void setup(){
 Serial.begin(115200);delay(250);
 Serial.println("[S3] CuteDisplay Phase 3 secure BLE proxy beta");
 Serial1.begin(BrainPinPlan::UART_BAUD,SERIAL_8N1,BrainPinPlan::UART_RX,BrainPinPlan::UART_TX);
 Serial.printf("[S3] UART TX=%d RX=%d 115200\n",BrainPinPlan::UART_TX,BrainPinPlan::UART_RX);
 incomingCommands=xQueueCreate(256,MAX_CMD+1);
 networkQueue=xQueueCreate(48,97);
 if(!incomingCommands||!networkQueue){
  Serial.println("[S3] ERROR: unable to allocate command/telemetry queues");
  return;
 }
 BLEDevice::init(BRAIN_NAME);
 BLEDevice::setMTU(185);
 BLESecurity *security=new BLESecurity();
 security->setCapability(ESP_IO_CAP_NONE);
 security->setAuthenticationMode(ESP_LE_AUTH_REQ_SC_BOND);
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
 controlChar->setValue("PROXY_DISABLED");ctrl->start();
 BLEService *bs=server->createService("180F");
 batteryChar=bs->createCharacteristic("2A19",BLECharacteristic::PROPERTY_READ|BLECharacteristic::PROPERTY_NOTIFY);
 uint8_t unknown=255;batteryChar->setValue(&unknown,1);bs->start();
 BLEService *ps=server->createService("FFF3");
 powerChar=ps->createCharacteristic("FFF4",BLECharacteristic::PROPERTY_READ|BLECharacteristic::PROPERTY_NOTIFY);
 powerChar->setValue("0,0,0,0,0,0,0,0");ps->start();
 BLEService *ns=server->createService("FFF5");
 networkChar=ns->createCharacteristic("FFF6",
   BLECharacteristic::PROPERTY_READ|BLECharacteristic::PROPERTY_NOTIFY|
   BLECharacteristic::PROPERTY_READ_ENC);
 networkChar->setAccessPermissions(ESP_GATT_PERM_READ_ENCRYPTED);
 networkChar->setValue("N:LINK:0");ns->start();
 BLEAdvertising *ad=BLEDevice::getAdvertising();
 ad->addServiceUUID(BLEUUID("FFF0"));
 ad->addServiceUUID(BLEUUID("180F"));
 ad->setScanResponse(true);
 BLEDevice::startAdvertising();
 Serial.println("[S3] Encrypted FFF1 writes; BLE proxy starts disabled (proxy on)");
 // Start BLE before WiFi (avoids radio/heap fragmentation during BLE init).
 restoreBrainWiFi();
 if(wifiEnabled)startBrainWiFi();
 else WiFi.mode(WIFI_OFF);
}
void loop(){
 pollFace();
 pollUSB();
 updateBrainWiFi();
 if(connectPending){
  connectPending=false;clientConnected=true;
  Serial.println("[S3] BLE connected; encrypted write will trigger bonding if needed");
  sendRadioStatus(true);
  networkInfo("LINK");
 }
 if(disconnectPending){
  disconnectPending=false;clientConnected=false;
  stopProxy();
  if(networkQueue)xQueueReset(networkQueue);
  BLEDevice::startAdvertising();
  sendRadioStatus(true);
  Serial.println("[S3] BLE disconnected; proxy gate closed");
 }
 pollBLECommands();
 pollNetwork();
 delay(5);
}
