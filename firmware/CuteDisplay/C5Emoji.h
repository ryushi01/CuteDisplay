#pragma once
#include <stdint.h>
// Compact colored 16x16 emoji, generated procedurally on C5. No assets,
// persistent writes, or extra PSRAM. Rendering callback plots RGB565 pixels.
// Friendly face emoji plus hearts / stars for common chat use.
inline bool c5EmojiSupported(uint32_t c) {
 return (c>=0x1F600 && c<=0x1F64F) || c==0x1F970 || c==0x1F973 ||
        c==0x1F929 || c==0x1F972 || c==0x1F976 || c==0x1F975 ||
        c==0x1F920 || c==0x1F914 || c==0x1F917 || c==0x1F923 ||
        c==0x1F92A || c==0x1F92B || c==0x1F92D || c==0x1F92F ||
        c==0x1F9D0 || c==0x1F979 || c==0x2764 || c==0x1F49B ||
        c==0x1F49A || c==0x1F499 || c==0x1F49C || c==0x1F5A4 ||
        c==0x1F90D || c==0x1F90E || c==0x1F496 || c==0x1F497 ||
        c==0x1F498 || c==0x1F495 || c==0x1F49E || c==0x1F49F ||
        c==0x2B50 || c==0x1F31F || c==0x1F320 || c==0x2728;
}
inline bool c5EmojiHeart(uint32_t c) {
 return c==0x2764 || (c>=0x1F495 && c<=0x1F49F) ||
        c==0x1F90D || c==0x1F90E || c==0x1F5A4;
}
template<class Plot>
inline void c5DrawEmoji(uint32_t cp,int x,int y,int scale,Plot plot) {
 const uint16_t Y=0xFFE0, DARK=0x2104, WHITE=0xFFFF, ROSE=0xF81F;
 const uint16_t RED=0xF800, BLUE=0x001F, GREEN=0x07E0;
 auto dot=[&](int px,int py,uint16_t c){
  if(px>=0 && px<16 && py>=0 && py<16)
   for(int yy=0;yy<scale;yy++)for(int xx=0;xx<scale;xx++)
    plot(x+px*scale+xx,y+py*scale+yy,c);
 };
 if(c5EmojiHeart(cp)){
  uint16_t ink=ROSE;
  if(cp==0x2764 || cp==0x1F498)ink=RED;
  else if(cp==0x1F49B)ink=Y;
  else if(cp==0x1F49A)ink=GREEN;
  else if(cp==0x1F499)ink=BLUE;
  else if(cp==0x1F5A4)ink=DARK;
  else if(cp==0x1F90D)ink=WHITE;
  else if(cp==0x1F90E)ink=0x9A45;
  for(int j=2;j<15;j++)for(int i=1;i<15;i++){
   bool heart=(j<=5 ? ((i>=2 && i<=6)||(i>=9 && i<=13)) :
               (i>=j-6 && i<=21-j));
   if(heart)dot(i,j,ink);
  }
  return;
 }
 if(cp==0x2B50 || cp==0x1F31F || cp==0x1F320 || cp==0x2728){
  for(int j=1;j<15;j++)for(int i=1;i<15;i++){
   int dx=i-8,dy=j-8;
   if((abs(dx)<=1 && abs(dy)<=7) || (abs(dy)<=1 && abs(dx)<=7) ||
      (abs(dx)==abs(dy) && abs(dx)<=4))dot(i,j,Y);
  }
  return;
 }
 // Familiar yellow face with black eyes and a mouth selected by emoji.
 for(int j=0;j<16;j++)for(int i=0;i<16;i++){
  int dx=i-8,dy=j-8,d2=dx*dx+dy*dy;
  if(d2<=56)dot(i,j,Y);
  else if(d2<=63 && ((i+j)&1)==0)dot(i,j,0xFBC0);
 }
 bool wink=cp==0x1F609 || cp==0x1F61C || cp==0x1F61D || cp==0x1F618;
 bool sad=cp==0x1F622 || cp==0x1F62D || cp==0x1F61E ||
          cp==0x1F641 || cp==0x1F614 || cp==0x1F625 || cp==0x1F615;
 bool open=cp==0x1F62E || cp==0x1F632 || cp==0x1F631 ||
           cp==0x1F62F || cp==0x1F62D || cp==0x1F603 || cp==0x1F604;
 bool hearts=cp==0x1F60D || cp==0x1F970;
 for(int eye=0;eye<2;eye++){
  int cx=eye?11:5;
  if(hearts){
   dot(cx,5,RED);dot(cx-1,4,RED);dot(cx+1,4,RED);dot(cx,6,RED);
  }else if(wink && eye==0){
   for(int k=-1;k<=1;k++)dot(cx+k,6,DARK);
  }else{
   dot(cx,5,DARK);dot(cx,6,DARK);
  }
 }
 if(open){
  for(int j=9;j<=12;j++)for(int i=6;i<=10;i++)
   if((i-8)*(i-8)+(j-10)*(j-10)<=5)dot(i,j,DARK);
 }else{
  for(int i=4;i<=12;i++){
   int v=i-8;
   int yy=sad?10-(16-v*v)/16:10+(16-v*v)/16;
   dot(i,yy,DARK);
  }
 }
 if(cp==0x1F622 || cp==0x1F62D){
  for(int k=7;k<13;k++)dot(4,k,BLUE);
 }
 if(cp==0x1F60A || cp==0x1F970 || cp==0x1F60D){
  dot(3,9,ROSE);dot(13,9,ROSE);
 }
}
