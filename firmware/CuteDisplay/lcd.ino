/*
 CuteDisplay 3.4 - T-Display C5 / ESP32-C5
 Message mode, 24 drink entries / four per page, rotating mascot,
 brightness, live AXP2602 battery level (BLE 180F / 2A19).

 Commands on FFF0/FFF1:
  Text               = message mode
  B:75               = brightness
  C:0 / C:1 / C:2   = bunny / kitty / chiikawa
  D:RESET            = clear staged drink list, does not change current LCD
  D:ADD:TEQUILA,9    = append one staged drink
  D:SHOW             = commit staged list and display rotating drinks pages
  D:TEQUILA,9;WINE,2 = legacy short-list format

 Preserve board_config.h, and install LILYGO's axp2602.h library.
*/
#include <Arduino.h>
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

#define PIN_CS 26
#define PIN_DC 8
#define PIN_RST 23
#define PIN_MOSI 9
#define PIN_SCLK 7
#define PIN_BL 25
#define BAT_SDA 2
#define BAT_SCL 3
#define LCD_W 320
#define LCD_H 170
#define MAX_CMD 96
#define MAX_GLYPHS 128
#define MAX_DRINKS 24
#define PAGE_SIZE 4
#define PAGE_MS 3500UL
#define BLACK 0x0000
#define WHITE 0xFFFF
#define PINK 0xF81F
#define SOFTPINK 0xFBB2
#define YELLOW 0xFFE0
#define PANEL 0x18C5
#define DARK 0x1083

esp_lcd_panel_handle_t panel = nullptr;
esp_lcd_panel_io_handle_t panelIO = nullptr;
uint16_t *pixels = nullptr;
SemaphoreHandle_t lcdSemaphore = nullptr;
QueueHandle_t commandQueue = nullptr;
AXP2602 axp;
BLECharacteristic *batteryCharacteristic = nullptr;
BLECharacteristic *powerCharacteristic = nullptr;
bool lcdReady = false;
bool pwmReady = false;
bool batteryReady = false;
volatile bool bleConnected = false;
int batteryLevel = -1;
unsigned long lastBatteryRead = 0;
unsigned long lastScroll = 0;
unsigned long lastPage = 0;

struct Drink { String name; int count; };
Drink staged[MAX_DRINKS];
Drink drinks[MAX_DRINKS];
int stagedCount = 0;
int drinkCount = 0;
int currentPage = 0;
int mascot = 1;
int theme = 0;
int brightness = 75;
enum DisplayMode { MESSAGE_MODE, DRINKS_MODE };
DisplayMode mode = MESSAGE_MODE;
String message = "こんにちわ";
bool bubbleEnabled = false; // Normal scrolling remains the default.
bool bubbleTypewriter = true;
size_t revealedCharacters = 0;
unsigned long lastBubbleReveal = 0;
const unsigned long BUBBLE_LETTER_MS = 135;
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
void scheduleNextSurprise(unsigned long now) {
 nextSurpriseAt = now + 40000UL + (esp_random() % 50000UL);
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
uint16_t mascotBackup[98 * 170];
int mascotPanelWidth() { return mascotVisible ? max(40, 98 * mascotPercent / 100) : 0; }
int contentRight() { return LCD_W - mascotPanelWidth() - (mascotVisible ? 3 : 0); }
int jpMessageScale() { return max(1, min(4, messageSize)); }
int asciiMessageScale() { return max(1, min(6, messageSize + 1)); }
void drawDrinks();
void drawMessage();
void redrawCurrent() { if(mode==DRINKS_MODE)drawDrinks();else drawMessage(); }

// 25 accent themes. Outside the bubble stays pure black; the bubble is light.
uint16_t themeColor() {
 switch(theme) {
  case 0: return 0xF81F; // Pink
  case 1: return 0x07FF; // Cyan
  case 2: return 0x07E0; // Mint
  case 3: return 0xFFE0; // Yellow
  case 4: return 0xA81F; // Lavender
  case 5: return 0xFB12; // Rose
  case 6: return 0x049F; // Ocean
  case 7: return 0xFD28; // Peach
  case 8: return 0xB7E0; // Lime
  case 9: return 0xF805; // Ruby
  case 10: return 0xBFFF; // Ice
  case 11: return 0xFC40; // Sunset
  case 12: return 0xD35F; // Lilac
  case 13: return 0xFE60; // Gold
  case 14: return 0x5CFF; // Sky
  case 15: return 0xFB6C; // Coral
  case 16: return 0x373A; // Turquoise
  case 17: return 0x2F31; // Emerald
  case 18: return 0x92FF; // Violet
  case 19: return 0xFA1D; // Magenta
  case 20: return 0xFD66; // Amber
  case 21: return 0x84BF; // Periwinkle
  case 22: return 0xF75F; // Pearl
  case 23: return 0xE98A; // Crimson
  case 24: return 0x97E8; // Neon
  default: return BLACK;
 }
}
// Only the accent color changes with the chosen theme.
uint16_t themeBackground() { return BLACK; }
uint16_t themeMascotBackground() { return BLACK; }
// Drinks mode only: contrasting, alternating tinted row panels.
// Keep the outside black and preserve the light speech-bubble treatment.
uint16_t themeRow(int index) {
 uint16_t c = themeColor();
 int r = (c >> 11) & 31;
 int g = (c >> 5) & 63;
 int b = c & 31;
 // Alternate two clearly visible dark charcoal + theme-accent blends.
 // The upper bound prevents light rows from competing with white quantities.
 int base = (index % 2) ? 2 : 4;
 r = min(31, base + (r * ((index % 2) ? 4 : 6)) / 31);
 g = min(63, base * 2 + (g * ((index % 2) ? 8 : 12)) / 63);
 b = min(31, base + (b * ((index % 2) ? 4 : 6)) / 31);
 return (uint16_t)((r << 11) | (g << 5) | b);
}
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
CJKGlyph glyphCache[MAX_GLYPHS];
int glyphCount = 0;

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
 int sum = 0;
 for(int i=0; i<(int)s.length();) sum += utfWidth(decodeUTF8(s,i),asciiScale,jpScale);
 return sum;
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
 pixels[y*LCD_W+x] = c;
}
void rect(int x,int y,int w,int h,uint16_t c) {
 if (!pixels) return;
 for (int yy=max(0,y); yy<min(LCD_H,y+h); ++yy)
  for (int xx=max(0,x); xx<min(LCD_W,x+w); ++xx)
   pixels[yy*LCD_W+xx]=c;
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
 else if(ch==' ')return;
 else{data[0]=2;data[1]=1;data[2]=81;data[3]=9;data[4]=6;}
 for(int cx=0;cx<5;cx++)for(int cy=0;cy<7;cy++)
  if(data[cx]&(1<<cy))rect(x+cx*scale,y+cy*scale,scale,scale,color);
}
void textAt(const String &s,int x,int y,int scale,uint16_t color) {
 for(int i=0;i<(int)s.length();i++) {
  int xx=x+i*6*scale;
  if(xx>=LCD_W||xx+5*scale<0)continue;
  glyph(xx,y,s[i],scale,color);
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
void richText(const String &str, int x, int y, int ascScale, int jpScale,
              uint16_t color, int clipRight) {
 for(int p=0; p<(int)str.length();) {
  uint32_t cp = decodeUTF8(str,p);
  int width = utfWidth(cp,ascScale,jpScale);
  if(x + width > 0 && x < clipRight) {
   if(cp < 128) {
    if(x + width <= clipRight) glyph(x,y,(char)cp,ascScale,color);
   } else {
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
void kitty(){
 // Pointed cat ears with shaded interiors and a glossy red/theme bow.
 for(int y=44;y<=86;y++){
  int w=7+(y-44)*26/42;
  rect(246-w/2,y,w,1,OUTLINE);
  rect(299-w/2,y,w,1,OUTLINE);
 }
 for(int y=49;y<=85;y++){
  int w=4+(y-49)*21/36;
  rect(246-w/2,y,w,1,WHITE);
  rect(299-w/2,y,w,1,WHITE);
 }
 oval(245,71,6,12,BLUSH);oval(299,71,6,12,BLUSH);
 outlinedOval(272,144,27,22,WHITE);
 outlinedOval(271,105,44,36,WHITE);
 // Side highlights and animated glossy bow / knot.
 oval(237,109,5,14,0xEF7D);
 oval(308,111,5,12,0xEF7D);
 int sway=(animPhase/4)%3-1;
 outlinedOval(290,72+sway,13,10,themeColor());
 outlinedOval(311,72-sway,9,12,themeColor());
 oval(301,72,7,7,YELLOW);oval(299,70,2,2,WHITE);
 // Signature nose and whiskers.
 oval(271,117,6,4,YELLOW);
 line(241,115,226,112,OUTLINE);line(241,122,226,124,OUTLINE);
 line(301,115,318,112,OUTLINE);line(301,122,318,124,OUTLINE);
 paws(155,animPhase%10==3);
}
void chiikawa(){
 outlinedOval(247,63,14,21,WHITE);outlinedOval(295,63,14,21,WHITE);
 oval(247,65,7,13,themeColor());oval(295,65,7,13,themeColor());
 outlinedOval(271,141,28,23,WHITE);
 outlinedOval(272,104,42,39,WHITE);
 oval(245,118,10,6,BLUSH);oval(299,118,10,6,BLUSH);
 paws(152,animPhase%12==5);
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

void mascotExpression(){
 int cx=271, eyeY=104;
 if(mascot==0) eyeY=102;
 if(mascot==5) eyeY=105;
 uint16_t accent=themeColor();
 bool blink=(animPhase==13 || animPhase==14 || animPhase==28);
 bool sleepy=(mood==5);
 bool sad=(mood==2);
 bool shy=(mood==7);
 bool angry=(mood==3);
 bool hungry=(mood==4);
 bool excited=(mood==6);
 // Existing facial moods, eyelid animation and surprise actions are preserved.
 int gx=gazeX, gy=gazeY;
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
 drawSurpriseEffects();
 for(int y=0;y<170;y++)for(int x=0;x<98;x++)
  mascotBackup[y*98+x]=pixels[y*LCD_W+222+x];
 rect(222,0,98,170,themeBackground());
 int dstW=mascotPanelWidth();
 int dstX=LCD_W-dstW;
 int bodyH=max(30,170*mascotPercent/100);
 int breathe=(animPhase/5)%2;
 int bounce=mood==6?(animPhase%8<4?4:0):
            mood==2?(animPhase/8)%2:
            mood==3?(animPhase%4<2?3:0):
            mood==5?(animPhase/10)%2:1+breathe;
 int top=(170-bodyH)/2-bounce;
 // Fixed character dimensions: no sudden shrinking or stretching.
 // Clamp the original whole sprite, including ears, to the display.
 dstX=constrain(dstX,0,LCD_W-dstW);
 top=constrain(top,0,LCD_H-bodyH);
 for(int y=0;y<bodyH;y++)for(int x=0;x<dstW;x++) {
  int sx=x*98/dstW,sy=y*170/bodyH;
  pixel(dstX+x,top+y,mascotBackup[sy*98+sx]);
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
 for (int i = 0; i < LCD_W * LCD_H; i++) pixels[i] = bg;
 return true;
}
void finishDrawing() {
 esp_err_t e=esp_lcd_panel_draw_bitmap(panel,0,0,LCD_W,LCD_H,pixels);
 if(e!=ESP_OK){Serial.printf("[LCD] Draw error: %d\n",e);xSemaphoreGive(lcdSemaphore);}
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
 if(bubbleEnabled){drawSpeechBubble();drawMascot();}
 else {drawMascot();richText(message,scrollX,(LCD_H-height)/2,a,j,themeColor(),contentRight());}
 finishDrawing();
}
void showMessage(String s) {
 s.trim(); if(s.isEmpty())return;
 message=s;mode=MESSAGE_MODE;
 revealedCharacters=0;lastBubbleReveal=millis();
 int width=richWidth(s,asciiMessageScale(),jpMessageScale());
 int right=contentRight();
 scrolling=!bubbleEnabled && width>right-16;
 scrollX=scrolling?right:(right-width)/2;
 drawMessage();lastScroll=millis();
 Serial.println("[MODE] Message");
}
int pageCount(){return max(1,(drinkCount+PAGE_SIZE-1)/PAGE_SIZE);}
void drawDrinks(){
 if(!beginDrawing())return;
 rect(0,0,4,LCD_H,themeColor());
 drawMascot();
 int start=currentPage*PAGE_SIZE;
 for(int row=0;row<PAGE_SIZE && start+row<drinkCount;row++){
  int y=12+row*39;
  // Contrasting dark-tinted rows only in Drinks Mode; outside stays black.
  rect(9,y-5,contentRight()-9,35,themeRow(row));
  rect(9,y-3,2,30,themeColor());
  String name=drinks[start+row].name;
  String qty="X"+String(drinks[start+row].count);
  int qtyX=(contentRight()-5)-qty.length()*12;
  // Keep a consistent 16-pixel Japanese glyph height in the compact rows.
  // English scales to 2x only when it fits before the quantity column.
  bool hasJapanese = false;
  for (int k=0; k<(int)name.length(); k++) {
   if ((unsigned char)name[k] >= 0x80) { hasJapanese=true; break; }
  }
  int nameScale = (!hasJapanese && 14+richWidth(name,2,1)<qtyX-6) ? 2 : 1;
  richText(name,14,y+8,nameScale,1,themeColor(),qtyX-5);
  textAt(qty,qtyX,y+4,2,WHITE);
 }
 // Small dots at the bottom-right of the character panel indicate pages.
 if(pageCount()>1 && mascotVisible){
  int pages=pageCount();
  int left=270-(pages*8)/2;
  for(int i=0;i<pages;i++)oval(left+i*8,161,2,2,i==currentPage?themeColor():WHITE);
 }
 finishDrawing();
}
void activateDrinks(){
 drinkCount=stagedCount;
 for(int i=0;i<drinkCount;i++)drinks[i]=staged[i];
 currentPage=0;lastPage=millis();
 mode=DRINKS_MODE;scrolling=false;
 drawDrinks();
 Serial.printf("[DRINKS] Showing %d drinks, %d pages\n",drinkCount,pageCount());
}
bool parseEntry(String entry,Drink &result){
 int comma=entry.indexOf(',');if(comma<=0)return false;
 String name=entry.substring(0,comma);
 String value=entry.substring(comma+1);
 int second=value.indexOf(',');if(second>=0)value=value.substring(0,second);
 name.trim();value.trim();
 if(name.isEmpty()||value.isEmpty())return false;
 for(int i=0;i<(int)value.length();i++)if(value[i]<'0'||value[i]>'9')return false;
 result.name=name;
 result.count=constrain(value.toInt(),0,9999);
 return !result.name.isEmpty();
}
void legacyDrinks(String payload){
 stagedCount=0;int start=0;
 while(start<(int)payload.length()&&stagedCount<MAX_DRINKS){
  int end=payload.indexOf(';',start);if(end<0)end=payload.length();
  Drink item;
  if(parseEntry(payload.substring(start,end),item))staged[stagedCount++]=item;
  start=end+1;
 }
 activateDrinks();
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
 Serial.printf("[BATTERY] %d%% %.3f V %.3f A\n",value,volts,amps);
 if(powerCharacteristic){
  String data=String(value)+","+String(volts,3)+","+String(amps,3)+","+
    String(axp.getTemperature())+","+String(axp.getSOH())+","+
    String(axp.getTimeToEmpty())+","+String(axp.getTimeToFull());
  powerCharacteristic->setValue(data.c_str());
  if(bleConnected)powerCharacteristic->notify();
 }
 if(batteryCharacteristic){
  uint8_t b=(uint8_t)value;
  batteryCharacteristic->setValue(&b,1);
  if(bleConnected)batteryCharacteristic->notify();
 }
}
void initBattery(){
 Wire.begin(BAT_SDA,BAT_SCL);Wire.setClock(400000);
 batteryReady=axp.begin();
 Serial.println(batteryReady?"[BATTERY] Ready":"[BATTERY] Unavailable");
 if(batteryReady)readBattery();
 lastBatteryRead=millis();
}
class ServerEvents:public BLEServerCallbacks{
 void onConnect(BLEServer *s)override{bleConnected=true;Serial.println("[BLE] Connected");}
 void onDisconnect(BLEServer *s)override{bleConnected=false;Serial.println("[BLE] Disconnected");}
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
 BLEAdvertising *ad=BLEDevice::getAdvertising();
 ad->addServiceUUID("FFF0");ad->addServiceUUID("180F");
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
 bus.max_transfer_sz=LCD_W*LCD_H*2+8;
 ESP_ERROR_CHECK(spi_bus_initialize(SPI2_HOST,&bus,SPI_DMA_CH_AUTO));
 esp_lcd_panel_io_spi_config_t io={};
 io.cs_gpio_num=PIN_CS;io.dc_gpio_num=PIN_DC;
 io.spi_mode=0;io.pclk_hz=20000000;io.trans_queue_depth=10;
 io.lcd_cmd_bits=8;io.lcd_param_bits=8;
 io.on_color_trans_done=lcdTransferred;io.user_ctx=lcdSemaphore;
 ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi((esp_lcd_spi_bus_handle_t)SPI2_HOST,&io,&panelIO));
 esp_lcd_panel_dev_config_t config={};
 config.reset_gpio_num=PIN_RST;config.rgb_endian=LCD_RGB_ENDIAN_BGR;config.bits_per_pixel=16;
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
 pixels=(uint16_t*)heap_caps_malloc(LCD_W*LCD_H*2,MALLOC_CAP_DMA);
 if(!pixels){Serial.println("[LCD] Buffer unavailable");return;}
 lcdReady=true;showMessage("こんにちわ");
 Serial.println("[LCD] Ready 320x170");
}
void processCommand(String cmd){
 cmd.trim();
 if(cmd.startsWith("G:")){acceptGlyph(cmd.substring(2));return;}
 if(cmd.startsWith("T:")){
  int n=cmd.substring(2).toInt();
  if(n>=0&&n<=24){theme=n;if(mode==DRINKS_MODE)drawDrinks();else drawMessage();}
  return;
 }
 if(cmd=="P:OFF"){
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
  if(n==0||n==1){bubbleEnabled=n==1;if(mode==MESSAGE_MODE)showMessage(message);}
  return;
 }
 if(cmd.startsWith("Y:")) {
  int n=cmd.substring(2).toInt();
  if(n==0||n==1){bubbleTypewriter=n==1;if(mode==MESSAGE_MODE && bubbleEnabled)showMessage(message);}
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
  if(n>=0&&n<=7){mood=n;animPhase=0;redrawCurrent();}
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
  if(n>=1&&n<=5){messageSize=n;if(mode==MESSAGE_MODE)showMessage(message);}
  return;
 }
 if(cmd.startsWith("B:")){setBrightness(cmd.substring(2).toInt());return;}
 if(cmd.startsWith("C:")){
  int n=cmd.substring(2).toInt();
  if(n>=0&&n<=5){mascot=n;if(mode==DRINKS_MODE)drawDrinks();else drawMessage();}
  return;
 }
 if(cmd=="D:RESET"){
  stagedCount=0;Serial.println("[DRINKS] Upload started");return;
 }
 if(cmd.startsWith("D:ADD:")){
  Drink item;
  if(stagedCount<MAX_DRINKS && parseEntry(cmd.substring(6),item)){
   staged[stagedCount++]=item;
   Serial.printf("[DRINKS] Added %d/%d: %s\n",stagedCount,MAX_DRINKS,item.name.c_str());
  }else Serial.println("[DRINKS] Rejected item");
  return;
 }
 if(cmd=="D:SHOW"){activateDrinks();return;}
 if(cmd.startsWith("D:")){legacyDrinks(cmd.substring(2));return;}
 showMessage(cmd);
}
void setup(){
 Serial.begin(115200);delay(700);
 Serial.println("=== CUTEDISPLAY 3.9 RIGHT-SIDE ANIMATIONS ===");
 commandQueue=xQueueCreate(32,MAX_CMD+1);
 if(!commandQueue)Serial.println("[BLE] Queue creation failed");
 installStartupGlyphs();initBattery();initLCD();initBLE();Serial.println("READY!");
}
void loop(){
 char input[MAX_CMD+1]={0};
 if(commandQueue && xQueueReceive(commandQueue,input,0)==pdTRUE)
  processCommand(String(input));
 if(millis()-lastBatteryRead>=10000UL){lastBatteryRead=millis();readBattery();}
 if(mode==DRINKS_MODE&&pageCount()>1&&millis()-lastPage>=PAGE_MS){
  lastPage=millis();currentPage=(currentPage+1)%pageCount();drawDrinks();
 }
 // Surprise actions start at randomized intervals and automatically end.
 // They never alter the user's chosen mood or mascot.
 if(!nextSurpriseAt)scheduleNextSurprise(millis());
 if(surpriseAction && millis()-surpriseStart>=SURPRISE_DURATION_MS){
  surpriseAction=0;
  scheduleNextSurprise(millis());
  if(mascotVisible && !(mode==MESSAGE_MODE&&scrolling))redrawCurrent();
 }else if(surprisesEnabled && mascotVisible && !surpriseAction
          && (int32_t)(millis()-nextSurpriseAt)>=0){
  surpriseAction=1+(esp_random()%12);
  surpriseStart=millis();
  if(!(mode==MESSAGE_MODE&&scrolling))redrawCurrent();
 }
 if(mascotVisible && millis()-lastMascotAnimation>=MASCOT_ANIMATION_MS){
  lastMascotAnimation=millis();animPhase=(animPhase+1)%32;
  updateExpressiveEyes(lastMascotAnimation);
  // The scrolling message already redraws frequently; avoid unnecessary transfers.
  if(!(mode==MESSAGE_MODE&&scrolling))redrawCurrent();
 }
 if(mode==MESSAGE_MODE && bubbleEnabled && bubbleTypewriter
    && revealedCharacters<bubbleCharacterCount(message)
    && millis()-lastBubbleReveal>=BUBBLE_LETTER_MS){
  lastBubbleReveal=millis();revealedCharacters++;drawMessage();
 }
 if(mode==MESSAGE_MODE&&scrolling&&millis()-lastScroll>=55UL){
  lastScroll=millis();scrollX-=3;
  if(scrollX+richWidth(message,asciiMessageScale(),jpMessageScale())<0)scrollX=contentRight();
  drawMessage();
 }
 delay(5);
}