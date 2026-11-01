#pragma once
// Kitty V6 C5-owned BLE transport: shared, allocation-bounded UART payload codec.
// Dormant until both board dispatchers use it; does NOT change v36 behavior.
#include <Arduino.h>
#include "CuteLink.h"

namespace KittyAppLink {
static constexpr size_t MAX_COMMAND = 96;
static constexpr size_t MAX_EVENT = 160;
static constexpr char CMD[] = "APP_CMD";
static constexpr char REPLY[] = "APP_REPLY";
static constexpr char EVENT[] = "APP_EVENT";
static constexpr char SESSION[] = "APP_SESSION";

inline bool hexNibble(char c, uint8_t &v) {
  if (c >= '0' && c <= '9') { v = c - '0'; return true; }
  if (c >= 'A' && c <= 'F') { v = c - 'A' + 10; return true; }
  return false;
}
// Hex protects CuteLink framing delimiters and supports UTF-8 and binary bytes.
// Neither function logs or stores its inputs.
inline bool encode(const String &value, String &encoded, size_t limit) {
  if (value.isEmpty() || value.length() > limit || value.length() * 2 > CuteLink::PAYLOAD) return false;
  static constexpr char DIGITS[] = "0123456789ABCDEF";
  encoded = "";
  if (!encoded.reserve(value.length() * 2)) return false;
  for (size_t i = 0; i < value.length(); ++i) {
    uint8_t b = static_cast<uint8_t>(value[i]);
    if (b == 0) { encoded = ""; return false; }
    encoded += DIGITS[b >> 4];
    encoded += DIGITS[b & 15];
  }
  return true;
}
inline bool decode(const String &encoded, String &value, size_t limit) {
  value = "";
  if (encoded.isEmpty() || (encoded.length() & 1) || encoded.length() > limit * 2) return false;
  if (!value.reserve(encoded.length() / 2)) return false;
  for (size_t i = 0; i < encoded.length(); i += 2) {
    uint8_t hi, lo;
    if (!hexNibble(encoded[i], hi) || !hexNibble(encoded[i+1], lo)) { value = ""; return false; }
    char b = static_cast<char>((hi << 4) | lo);
    if (b == '\0') { value = ""; return false; }
    value += b;
  }
  return true;
}
inline bool sendCommand(Stream &uart, uint16_t transaction, const String &command) {
  String payload;
  return transaction != 0 && encode(command, payload, MAX_COMMAND)
         && CuteLink::send(uart, transaction, CMD, payload);
}
inline bool readCommand(const CuteLink::Frame &frame, String &command) {
  return frame.type == CMD && frame.seq != 0
         && decode(frame.payload, command, MAX_COMMAND);
}
inline bool sendReply(Stream &uart, uint16_t transaction, const String &reply) {
  String payload;
  return transaction != 0 && encode(reply, payload, MAX_EVENT)
         && CuteLink::send(uart, transaction, REPLY, payload);
}
inline bool readReply(const CuteLink::Frame &frame, String &reply) {
  return frame.type == REPLY && frame.seq != 0
         && decode(frame.payload, reply, MAX_EVENT);
}
}
