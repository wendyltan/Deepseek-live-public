#ifndef R140_PCM_EDGES_H
#define R140_PCM_EDGES_H
#include <stdint.h>
#include <stddef.h>
/* 8ms linear fade at the *physical* PCM stream endpoints, not each Qwen
   phrase. Middle frames stay unchanged and keep original speaker volume.
   Never scale user volume, edit voice text or open a second I2S codec. */
#define R140_FADE_SAMPLES 192u
static inline void r140_apply_pcm_edges(int16_t *pcm,size_t count,
                                         int first,int last){
    if(!pcm || !count)return;
    for(size_t i=0;i<count;i++){
        uint32_t gain=R140_FADE_SAMPLES;
        if(first && i<R140_FADE_SAMPLES && i<gain)gain=(uint32_t)i;
        if(last){
            size_t remaining=count-i-1;
            if(remaining<R140_FADE_SAMPLES && remaining<gain)gain=(uint32_t)remaining;
        }
        if(gain<R140_FADE_SAMPLES)
            pcm[i]=(int16_t)(((int32_t)pcm[i]*(int32_t)gain)/(int32_t)R140_FADE_SAMPLES);
    }
}
#endif
