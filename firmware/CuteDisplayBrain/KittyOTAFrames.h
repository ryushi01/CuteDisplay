#pragma once
// OTA data frame validator for future idle-only LAN transport. Does not write
// firmware or enable remote deployment. Includes per-frame HMAC authentication.
#include <Arduino.h>
#include <mbedtls/md.h>
#include <cstring>

namespace KittyOTAFrames {
static constexpr size_t CHUNK_BYTES=48;
inline bool hexNibble(char c,uint8_t &v){
 if(c>='0'&&c<='9'){v=(uint8_t)(c-'0');return true;}
 if(c>='a'&&c<='f'){v=(uint8_t)(c-'a'+10);return true;}
 return false;
}
inline bool hexDecode(const String &s,uint8_t *out,size_t capacity){
 if((s.length()&1)||s.length()/2>capacity)return false;
 for(size_t i=0;i<s.length()/2;++i){
  uint8_t hi=0,lo=0;
  if(!hexNibble(s[2*i],hi)||!hexNibble(s[2*i+1],lo))return false;
  out[i]=(uint8_t)((hi<<4)|lo);
 }
 return true;
}
inline bool verifyFrame(const String &line,const uint8_t key[32],
                        const uint8_t nonce[16],uint32_t expectedOffset,
                        uint8_t data[CHUNK_BYTES],size_t &dataLen){
 dataLen=0;
 if(!key||!nonce||!data||line.length()>187||!line.startsWith("OTA_DATA "))return false;
 int p=line.indexOf(' ',9),q=p<0?-1:line.indexOf(' ',p+1);
 if(p!=17||q<0||q-p<3)return false;
 String off=line.substring(9,p),payload=line.substring(p+1,q),mac=line.substring(q+1);
 if(mac.length()!=32||payload.length()>CHUNK_BYTES*2||
    payload.length()==0||(payload.length()&1))return false;
 uint8_t offsetHex[4],providedMac[16],message[4+CHUNK_BYTES];
 if(!hexDecode(off,offsetHex,sizeof(offsetHex))||
    !hexDecode(mac,providedMac,sizeof(providedMac)))return false;
 uint32_t offset=((uint32_t)offsetHex[0]<<24)|((uint32_t)offsetHex[1]<<16)|
                 ((uint32_t)offsetHex[2]<<8)|offsetHex[3];
 if(offset!=expectedOffset)return false;
 dataLen=payload.length()/2;
 if(!hexDecode(payload,data,CHUNK_BYTES))return false;
 memcpy(message,offsetHex,4);memcpy(message+4,data,dataLen);
 uint8_t signedMessage[16+sizeof(message)];
 memcpy(signedMessage,nonce,16);
 memcpy(signedMessage+16,message,4+dataLen);
 uint8_t digest[32];
 if(mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256),
       key,32,signedMessage,16+4+dataLen,digest)!=0)return false;
 uint8_t difference=0;
 for(int i=0;i<16;++i)difference|=(uint8_t)(digest[i]^providedMac[i]);
 return difference==0;
}
}
