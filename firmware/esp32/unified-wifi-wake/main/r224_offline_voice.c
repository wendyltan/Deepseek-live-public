#include "r224_offline_voice.h"
#include <string.h>
static uint32_t u32(const uint8_t *b){return (uint32_t)b[0]|(uint32_t)b[1]<<8|(uint32_t)b[2]<<16|(uint32_t)b[3]<<24;}
static uint16_t u16(const uint8_t *b){return (uint16_t)b[0]|(uint16_t)b[1]<<8;}
const char *r224_clip_filename(r224_clip_t id){
 static const char *const files[]={"wake_ack.wav","hello.wav","offline.wav","rice.wav","status.wav",
 "sleep.wav","touch.wav","unknown.wav","goodbye.wav","happy.wav"};
 if(id<0 || (unsigned)id>=sizeof(files)/sizeof(files[0]))return NULL;
 return files[id];
}
bool r224_wav_header_valid(const uint8_t *h,size_t n,uint32_t total){
 if(!h||n<44||total<46||total>750000u||(total&1))return false;
 if(memcmp(h,"RIFF",4)||memcmp(h+8,"WAVEfmt ",8)||memcmp(h+36,"data",4))return false;
 if(u32(h+4)!=total-8||u32(h+16)!=16||u16(h+20)!=1||u16(h+22)!=1||
    u32(h+24)!=24000||u32(h+28)!=48000||u16(h+32)!=2||u16(h+34)!=16||
    u32(h+40)!=total-44)return false;
 return true;
}
static r224_clip_t clip_for(uint16_t id){
 switch(id){case 1:return R224_HELLO;case 2:return R224_RICE;case 3:return R224_STATUS;
 case 4:return R224_SLEEP;case 5:return R224_HAPPY;case 6:return R224_GOODBYE;
 default:return R224_NO_CLIP;}
}
r224_clip_t r224_verified_wake(r224_offline_gate_t *g,uint32_t epoch,uint32_t now,
 bool verified,bool exclusive,bool idle){
 if(!g||!epoch||!verified||!exclusive||!idle)return R224_NO_CLIP;
 g->listening=true;g->boot_epoch=epoch;g->wake_at_ms=now;g->last_sequence=0;
 return R224_WAKE_ACK;
}
r224_clip_t r224_verified_command(r224_offline_gate_t *g,uint32_t epoch,uint32_t seq,
 uint32_t now,uint16_t command,bool verified){
 if(!g||!g->listening||!verified||epoch!=g->boot_epoch||seq<=g->last_sequence||!seq)
  return R224_NO_CLIP;
 if((uint32_t)(now-g->wake_at_ms)>8000u){g->listening=false;return R224_NO_CLIP;}
 r224_clip_t id=clip_for(command);
 if(id==R224_NO_CLIP)return R224_NO_CLIP;
 g->last_sequence=seq;g->listening=false;return id;
}
