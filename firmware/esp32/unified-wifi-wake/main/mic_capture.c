// SPDX-License-Identifier: MIT
#include "mic_capture.h"
#include "bsp/esp-bsp.h"
#include "esp_log.h"
#include "r224_media_owner.h"
#ifdef DF_R185_WN9
#include "r185_wakenet9.h"
#endif

static const char *TAG="H10_REAL_AVATAR";
esp_codec_dev_handle_t microphone;
static uint32_t r268_mic_lease=0;

/* R248: The ES7210 driver starts at +30dB but esp_codec_dev_open() later
 * re-applies codec_dev_t.mic_gain, which is zero-initialized by calloc.
 * Explicitly configure the shared board microphone's persistent gain before
 * any WakeNet or touch capture opens it. This is a one-time init, not a
 * second microphone owner and not a waveform/PCM logger.
 * Failure is visible and MUST block physical promotion, while preserving
 * the existing touch fallback instead of crashing the board.
 */
esp_codec_dev_handle_t r248_microphone_init_with_gain(void){
    esp_codec_dev_handle_t h=bsp_audio_codec_microphone_init();
    if(!h)return NULL;
    int rc=esp_codec_dev_set_in_gain(h,30.0f);
    if(rc!=ESP_CODEC_DEV_OK){
        ESP_LOGE(TAG,"R248_ES7210_GAIN_30DB_FAILED rc=%d",rc);
    }else{
        ESP_LOGI(TAG,"R248_ES7210_GAIN_30DB_EXPLICIT");
    }
    return h;
}
bool r268_audio_mic_open(void *unused){
    (void)unused;
#ifdef DF_R185_WN9
    if(!r185_wake_wait_released(2300))return false;
#endif
    if(!r224_audio_claim(R224_MEDIA_CAPTURE,&r268_mic_lease))return false;
    if(!microphone)microphone=r248_microphone_init_with_gain();
    if(!microphone)goto failed;
    esp_codec_dev_sample_info_t fmt={.sample_rate=16000,.channel=1,.bits_per_sample=16};
    if(esp_codec_dev_open(microphone,&fmt)!=ESP_CODEC_DEV_OK)goto failed;
    return true;
failed:
    r224_audio_release(R224_MEDIA_CAPTURE,r268_mic_lease);r268_mic_lease=0;
    return false;
}
bool r268_audio_mic_read(void *unused,int16_t *samples,size_t count){
    (void)unused;
    return r268_mic_lease && count==960u &&
       esp_codec_dev_read(microphone,samples,(int)(count*sizeof(*samples)))==ESP_CODEC_DEV_OK;
}
void r268_audio_mic_close(void *unused){
    (void)unused;
    if(!r268_mic_lease)return;
    esp_codec_dev_close(microphone);
    r224_audio_release(R224_MEDIA_CAPTURE,r268_mic_lease);r268_mic_lease=0;
}
