#pragma once
// Minimal Ogg Opus stream writer. Requires ALREADY ENCODED valid Opus packets.
// Implements RFC 7845 mono headers, per-page CRC, sequence and 48k granules.
// This class does NOT perform Opus encoding.
#include <Arduino.h>
namespace BrainOggOpus {
class Writer {
 uint8_t *out=nullptr;
 size_t used=0,capacity=0;
 uint32_t serial=0,seq=0;
 static void le16(uint8_t*p,uint16_t v){p[0]=v;p[1]=v>>8;}
 static void le32(uint8_t*p,uint32_t v){for(int i=0;i<4;i++)p[i]=v>>(8*i);}
 static void le64(uint8_t*p,uint64_t v){for(int i=0;i<8;i++)p[i]=v>>(8*i);}
 static uint32_t crc(const uint8_t *p,size_t n){
  uint32_t v=0;
  for(size_t i=0;i<n;i++){
   v^=(uint32_t)p[i]<<24;
   for(int b=0;b<8;b++)v=(v&0x80000000u)?(v<<1)^0x04c11db7u:v<<1;
  }
  return v;
 }
 bool page(const uint8_t*packet,size_t len,uint64_t granule,uint8_t flags){
  // One packet per page; up to 65025 bytes per packet (255 lacing values).
  if(!packet || len>65024)return false;
  size_t segments=len/255+1;
  if(segments>255)return false;
  size_t pageBytes=27+segments+len;
  if(used+pageBytes>capacity)return false;
  uint8_t *p=out+used;
  memset(p,0,27+segments);
  memcpy(p,"OggS",4);p[4]=0;p[5]=flags;
  le64(p+6,granule);le32(p+14,serial);le32(p+18,seq++);
  p[26]=(uint8_t)segments;
  size_t remaining=len;
  for(size_t i=0;i<segments;i++){size_t n=min((size_t)255,remaining);p[27+i]=(uint8_t)n;remaining-=n;}
  memcpy(p+27+segments,packet,len);
  le32(p+22,crc(p,pageBytes));
  used+=pageBytes;
  return true;
 }
public:
 bool begin(uint8_t*buffer,size_t maxBytes,uint32_t streamSerial,uint16_t preSkip=3840){
  if(!buffer||maxBytes<128)return false;
  out=buffer;capacity=maxBytes;used=0;seq=0;serial=streamSerial;
  uint8_t head[19]={};
  memcpy(head,"OpusHead",8);head[8]=1;head[9]=1;
  le16(head+10,preSkip);le32(head+12,16000);head[16]=0;head[17]=0;head[18]=0;
  if(!page(head,sizeof(head),0,0x02))return false;
  const char vendor[]="CuteDisplay";
  uint8_t tags[8+4+sizeof(vendor)-1+4]={};
  memcpy(tags,"OpusTags",8);
  le32(tags+8,sizeof(vendor)-1);memcpy(tags+12,vendor,sizeof(vendor)-1);
  le32(tags+12+sizeof(vendor)-1,0);
  return page(tags,sizeof(tags),0,0);
 }
 // granulePosition is absolute samples in 48kHz units, INCLUDING encoder pre-skip.
 bool packet(const uint8_t*opus,size_t len,uint64_t granulePosition,bool last){
  return page(opus,len,granulePosition,last?0x04:0);
 }
 size_t size()const{return used;}
};
}
