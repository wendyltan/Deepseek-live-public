// SPDX-License-Identifier: MIT
#include "audio_playback.h"
#include <string.h>

extern const uint8_t voice_start[] asm("_binary_VOICE_WAV_start");
extern const uint8_t voice_end[] asm("_binary_VOICE_WAV_end");

bool sample_asset(const uint8_t **pcm,size_t *samples){
    size_t count=(size_t)(voice_end-voice_start);
    if(count<45||count>1024u*1024u||memcmp(voice_start,"RIFF",4)||
       memcmp(voice_start+8,"WAVE",4)||
       memcmp(voice_start+12,"fmt ",4)||
       memcmp(voice_start+36,"data",4)||
       voice_start[20]!=1||voice_start[22]!=1||
       voice_start[24]!=0xC0||voice_start[25]!=0x5D||
       voice_start[26]!=0||voice_start[27]!=0||
       voice_start[34]!=16||(count-44)%2)return false;
    *pcm=voice_start+44;*samples=(count-44)/2u;
    return true;
}

#include "audio_playback_state.h"
#include "bsp/esp-bsp.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/task.h"
#include "r140_pcm_edges.h"
#include "r224_media_owner.h"

static const char *TAG="H10_REAL_AVATAR";
static uint32_t r268_dac_lease=0;
static bool r268_first_dac_frame=true;

bool r268_audio_speaker_open(void *unused){
    (void)unused;
    if(!r224_audio_claim(R224_MEDIA_PCM2,&r268_dac_lease))return false;
    if(!speaker)speaker=bsp_audio_codec_speaker_init();
    if(!speaker)goto failed;
    esp_codec_dev_sample_info_t fmt={.sample_rate=24000,.channel=1,.bits_per_sample=16};
    if(esp_codec_dev_open(speaker,&fmt)!=ESP_CODEC_DEV_OK)goto failed;
    if(esp_codec_dev_set_out_vol(speaker,volume)!=ESP_CODEC_DEV_OK){
        esp_codec_dev_close(speaker);goto failed;
    }
    r268_first_dac_frame=true;
    r303_wss_audio_offered=true;
#ifdef DF_R47_PCM2_DIAGNOSTIC
    // Reuse the 106-animation PCM2 state machine: preparing voice, not yet
    // speaking, while buffering the real network audio.
#ifdef DF_R434_MAC_PREWAKE_ONLY
    // R435: choose real m030 BEFORE the first DAC sample. Do not call this
    // speaking yet; the real PCM playback callback still owns that state.
    r435_mouth_first_frame_ready=false;
    r47_audio_motion=2;r47_motion_epoch++;
    for(unsigned wait=0;wait<18u && !r435_mouth_first_frame_ready;wait++)
        vTaskDelay(pdMS_TO_TICKS(25));
    ESP_LOGI(TAG,"R435_MOUTH_PREFRAME ready=%u",
             (unsigned)r435_mouth_first_frame_ready);
#else
    r47_audio_motion=1;r47_motion_epoch++;
#endif
#endif
    return true;
failed:
    r224_audio_release(R224_MEDIA_PCM2,r268_dac_lease);r268_dac_lease=0;
    return false;
}
bool r268_audio_speaker_write(void *unused,const int16_t *data,size_t count,bool last){
    (void)unused;
    if(!r268_dac_lease||count!=1440u)return false;
    for(size_t i=0;i<count;i+=480u){
        int16_t block[480];
        uint32_t block_peak=0,block_clips=0;
        for(unsigned j=0;j<480;j++){
            const int32_t source=(int32_t)data[i+j];
            const uint32_t peak=(uint32_t)(source<0?-source:source);
            if(peak>block_peak)block_peak=peak;
            if(peak>=32760u)block_clips++;
            block[j]=(int16_t)((source*7)/8);
        }
        // Write two RTC metrics ONCE per 20ms block, not per PCM sample.
        // Keep high-priority codec timing out of diagnostic contention.
        if(r281_trace.magic==R281_DIAG_MAGIC){
            if(block_peak>r281_trace.max_source_peak)
                r281_trace.max_source_peak=block_peak;
            r281_trace.clipped_source_samples+=block_clips;
        }
        r140_apply_pcm_edges(block,480,r268_first_dac_frame,last&&i+480u==count);
        const int64_t write_start_us=esp_timer_get_time();
        if(esp_codec_dev_write(speaker,block,sizeof(block))!=ESP_CODEC_DEV_OK)return false;
        if(r281_trace.magic==R281_DIAG_MAGIC){
            const uint32_t write_us=(uint32_t)(esp_timer_get_time()-write_start_us);
            r281_trace.speaker_blocks++;
            if(write_us>r281_trace.max_codec_write_us)
                r281_trace.max_codec_write_us=write_us;
            if(write_us>30000u)r281_trace.slow_codec_blocks++;
        }
#ifdef DF_R47_PCM2_DIAGNOSTIC
        if(r268_first_dac_frame){
#ifdef DF_R434_MAC_PREWAKE_ONLY
            // The m030 selection was already primed at codec open.
            if(r47_audio_motion!=2){r47_audio_motion=2;r47_motion_epoch++;}
#else
            r47_audio_motion=2;r47_motion_epoch++;
#endif
        }
#endif
        r268_first_dac_frame=false;
    }
    return true;
}
void r268_audio_speaker_close(void *unused){
    (void)unused;
    if(!r268_dac_lease)return;
    esp_codec_dev_close(speaker);
    r224_audio_release(R224_MEDIA_PCM2,r268_dac_lease);r268_dac_lease=0;
    r303_wss_audio_offered=false;
#ifdef DF_R47_PCM2_DIAGNOSTIC
    r47_audio_motion=3;r47_motion_epoch++;
#endif
}
