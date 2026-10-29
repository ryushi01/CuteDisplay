#pragma once
#include <stdint.h>
// French/Western Latin accents rendered on the unchanged built-in 5x7 glyph.
// Marks: 1 acute,2 grave,3 circumflex,4 diaeresis,5 tilde,6 cedilla,7 ring.
// Ligatures and letters without a straightforward ASCII base use existing font.
inline bool c5LatinAccent(uint32_t cp,char &base,uint8_t &mark){
 switch(cp){
 case 0x00C0: base='A';mark=2;return true;
 case 0x00C1: base='A';mark=1;return true;
 case 0x00C2: base='A';mark=3;return true;
 case 0x00C3: base='A';mark=5;return true;
 case 0x00C4: base='A';mark=4;return true;
 case 0x00C5: base='A';mark=7;return true;
 case 0x00C7: base='C';mark=6;return true;
 case 0x00C8: base='E';mark=2;return true;
 case 0x00C9: base='E';mark=1;return true;
 case 0x00CA: base='E';mark=3;return true;
 case 0x00CB: base='E';mark=4;return true;
 case 0x00CC: base='I';mark=2;return true;
 case 0x00CD: base='I';mark=1;return true;
 case 0x00CE: base='I';mark=3;return true;
 case 0x00CF: base='I';mark=4;return true;
 case 0x00D1: base='N';mark=5;return true;
 case 0x00D2: base='O';mark=2;return true;
 case 0x00D3: base='O';mark=1;return true;
 case 0x00D4: base='O';mark=3;return true;
 case 0x00D5: base='O';mark=5;return true;
 case 0x00D6: base='O';mark=4;return true;
 case 0x00D9: base='U';mark=2;return true;
 case 0x00DA: base='U';mark=1;return true;
 case 0x00DB: base='U';mark=3;return true;
 case 0x00DC: base='U';mark=4;return true;
 case 0x00DD: base='Y';mark=1;return true;
 case 0x0178: base='Y';mark=4;return true;
 default: return false;
 }
}
// Compose supported Latin base + combining accent on C5, leaving non-Latin
// Unicode and emoji untouched. Input may already be NFC.
inline uint32_t c5LatinCompose(uint32_t base,uint32_t combining){
 char b=0;uint8_t m=0;
 uint8_t target=0;
 switch(combining){
 case 0x0301:target=1;break;case 0x0300:target=2;break;
 case 0x0302:target=3;break;case 0x0308:target=4;break;
 case 0x0303:target=5;break;case 0x0327:target=6;break;
 case 0x030A:target=7;break;default:return 0;
 }
 for(uint32_t cp=0x00C0;cp<=0x0178;cp++){
  if(c5LatinAccent(cp,b,m) && (uint32_t)b==base && m==target)return cp;
 }
 return 0;
}
