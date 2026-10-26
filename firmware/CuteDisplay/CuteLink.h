#pragma once
// Phase-1 diagnostics (same copy in both sketches). NOT for production use.
// Frame: @CD1|sequence|type|payload|CRC8<LF>, CRC-8 0x07 over body.
#include <Arduino.h>
namespace CuteLink {
constexpr size_t LIMIT=160, PAYLOAD=96;
struct Frame { uint16_t seq=0; String type,payload; };
inline uint8_t crc(const String &s) {
 uint8_t v=0;
 for(size_t i=0;i<s.length();++i){v^=(uint8_t)s[i];for(int b=0;b<8;b++)v=(v&128)?(uint8_t)((v<<1)^7):(uint8_t)(v<<1);}
 return v;
}
inline bool fieldOk(const String &s) {
 if(s.length()>PAYLOAD)return false;
 for(size_t i=0;i<s.length();++i)if(s[i]=='|'||s[i]=='\r'||s[i]=='\n'||s[i]=='\0')return false;
 return true;
}
inline bool send(Stream &s,uint16_t seq,const char *kind,const String &payload="") {
 String type(kind);
 if(type.isEmpty()||type.length()>16||!fieldOk(type)||!fieldOk(payload))return false;
 String b="CD1|"+String(seq)+"|"+type+"|"+payload;
 if(b.length()+5>LIMIT)return false;
 uint8_t check=crc(b);const char *hex="0123456789ABCDEF";
 s.print('@');s.print(b);s.print('|');s.print(hex[check>>4]);s.print(hex[check&15]);s.print('\n');
 return true;
}
inline int unhex(char c) {
 if(c>='0'&&c<='9')return c-'0';
 if(c>='a'&&c<='f')return c-'a'+10;
 if(c>='A'&&c<='F')return c-'A'+10;
 return -1;
}
inline bool parse(const char *in,Frame &out) {
 String s(in);
 if(s.length()<13||s.length()>LIMIT||!s.startsWith("@CD1|"))return false;
 int last=s.lastIndexOf('|');
 if(last<0||s.length()!=(size_t)last+3)return false;
 int x=unhex(s[last+1]),y=unhex(s[last+2]);
 if(x<0||y<0)return false;
 String b=s.substring(1,last);
 if(crc(b)!=(uint8_t)(16*x+y))return false;
 int a=b.indexOf('|'),c=b.indexOf('|',a+1),d=b.indexOf('|',c+1);
 if(a!=3||c<=a+1||d<=c+1||b.indexOf('|',d+1)>=0)return false;
 String digits=b.substring(a+1,c);
 if(digits.isEmpty()||digits.length()>5)return false;
 uint32_t seq=0;
 for(size_t i=0;i<digits.length();++i){char ch=digits[i];if(ch<'0'||ch>'9')return false;seq=seq*10+ch-'0';}
 if(seq>65535)return false;
 String type=b.substring(c+1,d),payload=b.substring(d+1);
 if(type.isEmpty()||type.length()>16||!fieldOk(type)||!fieldOk(payload))return false;
 out.seq=seq;out.type=type;out.payload=payload;return true;
}
class Reader {
 char buf[LIMIT+1]={};size_t used=0;bool skipping=false;
public:
 uint32_t invalid=0;
 bool poll(Stream &s,Frame &out) {
  for(int n=0;n<192&&s.available()>0;++n){
   int c=s.read();if(c<0)break;
   if(c=='\r')continue;
   if(c=='\n'){
    if(skipping){++invalid;skipping=false;used=0;continue;}
    if(used){buf[used]=0;used=0;if(parse(buf,out))return true;++invalid;}
   }else if(!skipping){
    if(used<LIMIT)buf[used++]=(char)c;else{skipping=true;used=0;}
   }
  }
  return false;
 }
};
}
