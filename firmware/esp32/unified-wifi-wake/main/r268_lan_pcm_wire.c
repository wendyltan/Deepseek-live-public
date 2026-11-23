/* R268 network byte-order PCM envelope. No internal audio allocations. */
#include "r268_lan_pcm_wire.h"
#include <string.h>
bool r268_wire_encode(uint8_t *out,size_t out_cap,
                      uint8_t dir,uint64_t stream,uint32_t sequence,
                      const uint8_t *payload,size_t n) {
    if(!out||!payload||!n||n>R268_MAX_PAYLOAD||
       out_cap<R268_ENVELOPE+n||stream==0||
       (dir!=R268_MIC_UPLINK&&dir!=R268_SPEAKER_DOWNLINK))return false;
    out[0]=R268_MAGIC_0;out[1]=R268_MAGIC_1;
    out[2]=R268_VERSION;out[3]=dir;
    for(unsigned i=0;i<8;i++)out[4+i]=(uint8_t)(stream>>(56-8*i));
    for(unsigned i=0;i<4;i++)out[12+i]=(uint8_t)(sequence>>(24-8*i));
    memcpy(out+R268_ENVELOPE,payload,n);
    return true;
}
bool r268_wire_decode(const uint8_t *buffer,size_t len,
                      uint8_t dir,r268_pcm_wire_t *out) {
    if(!buffer||!out||len<=R268_ENVELOPE||
       len>R268_ENVELOPE+R268_MAX_PAYLOAD||
       buffer[0]!=R268_MAGIC_0||buffer[1]!=R268_MAGIC_1||
       buffer[2]!=R268_VERSION||buffer[3]!=dir||
       (dir!=R268_MIC_UPLINK&&dir!=R268_SPEAKER_DOWNLINK))return false;
    uint64_t sid=0;uint32_t seq=0;
    for(unsigned i=0;i<8;i++)sid=(sid<<8)|buffer[4+i];
    for(unsigned i=0;i<4;i++)seq=(seq<<8)|buffer[12+i];
    if(sid==0)return false;
    out->direction=dir;out->stream_id=sid;out->sequence=seq;
    out->data=buffer+R268_ENVELOPE;
    out->data_len=len-R268_ENVELOPE;
    return true;
}
