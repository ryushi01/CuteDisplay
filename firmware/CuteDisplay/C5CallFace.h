#pragma once
// CuteDisplay Realtime Call Face — purpose-designed 320x170 vector artwork.
// New artwork, not the legacy 98x170 side mascot scaled beyond its viewport.
// Pure framebuffer drawing. No network, flash writes, image allocation or BLE.
// Expects lcd.ino's clipped pixel/rect/oval/line/textAt primitives and
// callModeActive, callFaceMood, callLipLevel, kittyActivity and animPhase state.
static constexpr uint16_t CF_INK=0x2104;
static constexpr uint16_t CF_WHITE=0xFFFF;
static constexpr uint16_t CF_CREAM=0xFFBC;
static constexpr uint16_t CF_PINK=0xFC9B;
static constexpr uint16_t CF_PINK_DARK=0xE9AF;
static constexpr uint16_t CF_YELLOW=0xFEE0;
static constexpr uint16_t CF_BLUSH=0xFCD8;
static constexpr uint16_t CF_BLUE=0x64BE;
static constexpr uint16_t CF_PURPLE=0xA47D;
static constexpr uint16_t CF_RED=0xF1A9;
// All geometry stays in x=[0,319], y=[0,169]. The body/head may be
// intentionally clipped at the screen boundaries for an immersive close-up.

static void cfTri(int ax,int ay,int bx,int by,int cx,int cy,uint16_t color){
 // Triangles filled by horizontal scan lines; no floating-point dependency.
 int minY=max(0,min(ay,min(by,cy))),maxY=min(LCD_H-1,max(ay,max(by,cy)));
 for(int y=minY;y<=maxY;y++){
  int xs[3],count=0;
  const int px[3]={ax,bx,cx},py[3]={ay,by,cy};
  for(int edge=0;edge<3;edge++){
   int j=(edge+1)%3;
   if(py[edge]==py[j])continue;
   int low=min(py[edge],py[j]),high=max(py[edge],py[j]);
   if(y<low||y>high)continue;
   xs[count++]=px[edge]+(px[j]-px[edge])*(y-py[edge])/(py[j]-py[edge]);
  }
  if(count>=2){
   int lo=min(xs[0],xs[1]),hi=max(xs[0],xs[1]);
   if(count==3){lo=min(lo,xs[2]);hi=max(hi,xs[2]);}
   rect(lo,y,hi-lo+1,1,color);
  }
 }
}
static void cfStar(int x,int y,int radius,uint16_t color){
 line(x-radius,y,x+radius,y,color);
 line(x,y-radius,x,y+radius,color);
 line(x-radius/2,y-radius/2,x+radius/2,y+radius/2,color);
 line(x-radius/2,y+radius/2,x+radius/2,y-radius/2,color);
 oval(x,y,2,2,CF_WHITE);
}
static void cfHeart(int x,int y,uint16_t color){
 oval(x-4,y-2,5,5,color);oval(x+4,y-2,5,5,color);
 cfTri(x-10,y,x+10,y,x,y+12,color);
}
static void cfEye(int x,int y,int rx,int ry,bool glint=true){
 oval(x,y,rx+2,ry+2,CF_INK);
 oval(x,y,rx,ry,CF_INK);
 if(glint){
  oval(x-3,y-4,max(1,rx/4),max(1,ry/4),CF_WHITE);
  pixel(x+3,y+3,CF_WHITE);
 }
}
static void cfLid(int x,int y,int half,bool down){
 line(x-half,y+(down?2:0),x,y+(down?5:-3),CF_INK);
 line(x,y+(down?5:-3),x+half,y+(down?2:0),CF_INK);
}
static void cfRipple(int x,int y,uint16_t color,int phase){
 // Only visible portions of three small listening arcs; no huge full-screen
 // dirty area when the audio is idle.
 int d=phase%3;
 for(int i=0;i<3;i++){
  int r=5+i*7+d*2;
  line(x-r,y-r/3,x-r-3,y,color);
  line(x-r-3,y,x-r,y+r/3,color);
 }
}
static uint16_t cfBlend565(uint16_t from,uint16_t to,uint8_t amount){
 int r=((from>>11)&31)*(255-amount)+((to>>11)&31)*amount;
 int g=((from>>5)&63)*(255-amount)+((to>>5)&63)*amount;
 int b=(from&31)*(255-amount)+(to&31)*amount;
 return (uint16_t)(((r/255)<<11)|((g/255)<<5)|(b/255));
}
static int cfEyeHeight(uint8_t mood){
 if(mood==5)return 2;
 if(mood==3)return 6;
 if(mood==2 || mood==7)return 8;
 if(mood==6)return 16;
 return 14;
}
static void drawFullScreenKittyFace(){
 const uint32_t t=millis();
 const bool listening=kittyActivity=="CALL_LISTENING"||kittyActivity=="CALL_READY";
 const bool thinking=kittyActivity=="CALL_THINKING";
 const bool speaking=kittyActivity=="CALL_SPEAKING";
 const bool connecting=kittyActivity=="CALL_CONNECTING";
 // Only these eight temporary moods are recognized; never change the user's
 // persistent normal-message mascot or mood settings.
 // AI expression tool calls can arrive before any speech PCM. Keep the
 // chosen mood queued, but render it ONLY during CALL_SPEAKING. Thinking
 // always uses the C5-local thoughtful face; listening stays friendly.
 uint8_t emotion=thinking?0:(speaking && callFaceMood<=7?callFaceMood:1);
 const bool transitioning=speaking && callFacePreviousMood!=emotion &&
   callFaceTransitionStart &&
   (uint32_t)(t-callFaceTransitionStart)<CALL_FACE_TRANSITION_MS;
 const uint8_t mix=transitioning?
   (uint8_t)(((uint32_t)(t-callFaceTransitionStart)*255UL)/CALL_FACE_TRANSITION_MS):255;
 const uint8_t prior=callFacePreviousMood<=7?callFacePreviousMood:1;
 const bool blink=(!speaking && (animPhase==8||animPhase==9||animPhase==25));
 const int gaze=thinking?7:listening?-3:0;
 const int bob=speaking?((t/180)%2?1:0):0;
 const uint16_t bg=emotion==3?0xFBEF:emotion==2?0xDF5D:
                   emotion==6?0xF59F:emotion==5?0xDDFB:
                   emotion==7?0xFD9B:0xF73E;
 const uint16_t oldBg=prior==3?0xFBEF:prior==2?0xDF5D:
                   prior==6?0xF59F:prior==5?0xDDFB:
                   prior==7?0xFD9B:0xF73E;
 rect(0,0,LCD_W,LCD_H,transitioning?cfBlend565(oldBg,bg,mix):bg);
 // Tonal stripes emphasize the panoramic aspect ratio without gradients
 // that would waste all 256 framebuffer palette entries.
 rect(0,0,320,11,emotion==3?0xFBCF:0xEE9C);
 rect(0,153,320,17,emotion==2?0xDDBE:0xF69D);
 // Tiny ambient adornments; all optional and independent from model timing.
 if(emotion==6 || emotion==1){
  cfStar(22,31,7,CF_YELLOW);cfStar(293,52,5,CF_YELLOW);
  if((animPhase%5)<2)cfStar(307,118,4,CF_WHITE);
 }
 if(emotion==2){oval(24,45,5,7,CF_BLUE);oval(300,92,4,6,CF_BLUE);}
 if(emotion==3){
  line(13,41,26,33,CF_RED);line(291,35,305,43,CF_RED);
 }
 if(emotion==5){textAt("Z",24,21,2,CF_PURPLE);}
 if(thinking){
  // Floating thought bubbles pulse above the cheek, distinct from every AI mood.
  const int drift=(animPhase/3)%3;
  oval(280,79-drift,4,4,CF_PURPLE);
  oval(295,61-drift,6,6,CF_WHITE);
  oval(295,61-drift,4,4,CF_PURPLE);
 }
 // New full-screen head: ears occupy the top corners, oval fills the
 // full 320x170 screen. It is intentionally *not* the side mascot.
 cfTri(49,42,58,0,129,35,CF_INK);
 cfTri(53,38,61,5,119,35,CF_WHITE);
 cfTri(192,34,266,0,274,45,CF_INK);
 cfTri(201,31,263,7,269,41,CF_WHITE);
 cfTri(63,34,64,14,103,34,CF_PINK);
 cfTri(221,31,256,15,262,35,CF_PINK);
 oval(160,118+bob,145,102,CF_INK);
 oval(160,119+bob,141,99,CF_WHITE);
 // Large pink bow above Kitty's right ear — distinct, unscaled artwork.
 oval(232,29,31,17,CF_PINK_DARK);
 oval(270,29,29,17,CF_PINK_DARK);
 oval(232,27,27,13,CF_PINK);
 oval(270,27,25,13,CF_PINK);
 cfTri(224,28,219,12,249,29,CF_PINK);
 cfTri(254,28,286,11,279,39,CF_PINK);
 oval(251,30,13,12,CF_PINK_DARK);
 oval(251,29,9,8,CF_YELLOW);
 // Whiskers are long and spread toward the left/right edges.
 line(28,96,77,104+bob,CF_INK);line(23,114,75,116+bob,CF_INK);
 line(28,133,77,126+bob,CF_INK);
 line(243,104+bob,293,96,CF_INK);line(245,116+bob,300,114,CF_INK);
 line(244,126+bob,294,133,CF_INK);
 // Cheeks, colored but unobtrusive during angry/sad.
 oval(85,130,13,6,emotion==3?0xF9B0:CF_BLUSH);
 oval(234,130,13,6,emotion==3?0xF9B0:CF_BLUSH);
 // Large eyes centered around x=116/204, intentionally separated on the
 // widescreen Kitty face and clear of bow, cheeks and nose.
 const int lx=117+gaze,rx=203+gaze,ey=91+bob;
 if(thinking){
  // Asymmetric thoughtful eyes, raised brow and sideways glance.
  cfEye(lx,ey+2,9,12);cfLid(rx,ey+4,13,false);
  line(lx-12,ey-20,lx+12,ey-24,CF_INK);
  line(rx-12,ey-22,rx+10,ey-19,CF_INK);
 }else if(transitioning){
  // Smoothly morph eye opening and position over 200ms, while the mouth
  // continues using live PCM-based lip-sync independently.
  int height=(cfEyeHeight(prior)*(255-mix)+cfEyeHeight(emotion)*mix)/255;
  if(height<=3){cfLid(lx,ey,15,false);cfLid(rx,ey,15,false);}
  else {cfEye(lx,ey,9,height);cfEye(rx,ey,9,height);}
 }else if(emotion==5 || blink){
  cfLid(lx,ey,15,false);cfLid(rx,ey,15,false);
 }else if(emotion==2){
  cfLid(lx,ey+1,15,true);cfLid(rx,ey+1,15,true);
  oval(rx+17,ey+19+(animPhase%4),3,8,CF_BLUE);
 }else if(emotion==3){
  // Angled brows plus narrowed pupils (a distinctly angry look).
  line(lx-17,ey-15,lx+8,ey-7,CF_INK);
  line(rx-8,ey-7,rx+17,ey-15,CF_INK);
  oval(lx,ey+3,8,6,CF_INK);oval(rx,ey+3,8,6,CF_INK);
 }else if(emotion==6){
  cfEye(lx,ey,10,16);cfEye(rx,ey,10,16);
  cfStar(lx-16,ey-17,4,CF_YELLOW);
  cfStar(rx+17,ey-16,4,CF_YELLOW);
 }else if(emotion==7){
  cfLid(lx,ey,13,false);cfEye(rx,ey,9,12);
  cfHeart(89,137,CF_PINK_DARK);
 }else{
  cfEye(lx,ey,9,14);cfEye(rx,ey,9,14);
 }
 // The nose is always a fixed yellow oval with a soft white highlight.
 oval(160,119+bob,12,8,CF_YELLOW);
 oval(157,117+bob,4,2,CF_WHITE);
 if(emotion==4 && !speaking){
  oval(160,144,5,5,CF_INK); // hungry / anticipation
 }
 // Lip sync is driven by *actual speaker PCM amplitude* from S3. No mouth
 // during silence, except a faint smile for friendly non-speaking states.
 if(speaking){
  int openness=callLipLevel>=7?13:callLipLevel>=4?10:callLipLevel>=1?6:3;
  oval(160,146,9,openness,CF_INK);
  if(openness>=10)oval(160,152,5,3,CF_PINK);
 }else if(emotion==1 || emotion==6 || emotion==7){
  line(152,148,160,151,CF_INK);line(160,151,168,148,CF_INK);
 }else if(emotion==3){
  line(153,151,167,151,CF_INK);
 }
 // Expression-independent state cues make the display useful even when the
 // realtime model never selects an explicit mood/gesture.
 if(listening)cfRipple(33,84,CF_PURPLE,animPhase/2);
 if(thinking){
  // Animated thought punctuation is wholly generated by the C5, not Open WebUI.
  textAt("?",294,34+(animPhase%4<2?0:-2),2,CF_PURPLE);
 }
 if(connecting){
  for(int i=0;i<3;i++)oval(147+i*12,141,2+(i==(int)(animPhase%3)),2,CF_PURPLE);
 }
 // Thin bottom status capsule. Only 20px high; face remains full-screen.
 String label=listening?"LISTENING":thinking?"THINKING":
              speaking?"SPEAKING":connecting?"CONNECTING":"CALL";
 int width=label.length()*6+24;
 // Lower-left capsule, deliberately away from the center lip-sync mouth.
 int x=11;
 oval(x+8,160,8,8,CF_INK);oval(x+width-8,160,8,8,CF_INK);
 rect(x+8,152,width-16,17,CF_INK);
 textAt(label,x+12,155,1,CF_WHITE);
 // Two lines of chronological conversation at the top. New lines arrive
 // at the lower row and push the older line upward (speech-bubble style).
 // Black text directly on the bright face, without any caption panel.
 auto showLine=[&](const String &source,int y){
  if(source.isEmpty())return;
  String shown=source;
  // Clip from the UTF-8 leading edge to keep the newest part of a line.
  if(shown.length()>49){
   int cut=shown.length()-49;
   while(cut<shown.length() && ((uint8_t)shown[cut]&0xC0)==0x80)cut++;
   shown=shown.substring(cut);
  }
  richText(shown,6,y,1,1,CF_INK,316);
 };
 showLine(callCaptionPrevious,3);
 showLine(callCaption,16);
}
