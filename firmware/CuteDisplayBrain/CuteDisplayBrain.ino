/*
 CuteDisplay ESP32-S3 Brain — Phase 0 BLE discovery and UART-ready skeleton.
 Board target: Freenove ESP32-S3-CAM N16R8, Arduino-ESP32 3.x.
 NOTE: Candidate I2S and inter-board UART pins are documented in
 BrainPinPlan.h but are NOT configured or enabled by this sketch.
 Until the GPIO breakout and serial protocol are bench-tested, this firmware
 intentionally DOES NOT forward display commands or claim S3 audio support.
 Do not flash this sketch to the LILYGO T-Display-C5.
*/
#include <Arduino.h>
#include "BrainPinPlan.h"
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

void setup() {
  Serial.begin(115200);
  delay(250);
  Serial.println("[S3] CuteDisplay brain development bootstrap");
  Serial.println("[S3] Audio, camera, UART, AI and iOS migration are NOT activated");
  Serial.printf("[S3] Planned UART TX=%d RX=%d, I2S BCLK=%d WS=%d DIN=%d DOUT=%d (INACTIVE)\n",
    BrainPinPlan::UART_TX, BrainPinPlan::UART_RX,
    BrainPinPlan::I2S_BCLK, BrainPinPlan::I2S_WS,
    BrainPinPlan::I2S_DIN, BrainPinPlan::I2S_DOUT);
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
