// SPDX-License-Identifier: MIT
#include "anim_scheduler.h"
#include "esp_attr.h"
#include "esp_lv_adapter.h"
#include "freertos/task.h"

// R302: preserve the immutable complete avatar while a physical mic is busy.
// A <=1.6% breathing transform runs at most every 450ms; no SD reads,
// no DFSP decode and no writes to the shared RGB565 image PSRAM.
RTC_NOINIT_ATTR volatile r302_breath_trace_t r302_trace;
void r302_breathe_complete_image(r302_breath_state_t *state,
                                         bool enabled,bool is_wake,lv_obj_t *picture){
 if(r302_trace.magic!=R302_BREATH_MAGIC){
    r302_trace.magic=R302_BREATH_MAGIC;
    r302_trace.pulses=0;
    r302_trace.wake_pulses=0;
    r302_trace.mic_pulses=0;
    r302_trace.lock_misses=0;
    r302_trace.restores=0;
 }
 TickType_t now=xTaskGetTickCount();
 if(enabled){
    if(state->active && now-state->last_pulse<pdMS_TO_TICKS(450))
       return;
    if(esp_lv_adapter_lock(20)!=ESP_OK){
       r302_trace.lock_misses++;
       return;
    }
    if(picture && lv_obj_is_visible(picture)){
       if(!state->active){
          state->original_scale=(int32_t)lv_image_get_scale(picture);
          state->active=true;
       }
       static const int8_t steps[]={2,4,2,0};
       int32_t scale=state->original_scale+steps[(state->step++)%4u];
       lv_image_set_scale(picture,(uint32_t)scale);
       state->last_pulse=now;
       r302_trace.pulses++;
       if(is_wake)r302_trace.wake_pulses++;
       else r302_trace.mic_pulses++;
    }
    esp_lv_adapter_unlock();
 }else if(state->active){
    if(esp_lv_adapter_lock(20)!=ESP_OK){
       r302_trace.lock_misses++;
       return;
    }
    if(picture)lv_image_set_scale(picture,(uint32_t)state->original_scale);
    state->active=false;
    r302_trace.restores++;
    esp_lv_adapter_unlock();
 }
}
