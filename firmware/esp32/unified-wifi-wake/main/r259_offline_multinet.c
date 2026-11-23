/* R259 WakeNet9 -> exclusive mic -> official AFE WebRTC -> MultiNet5 CN Q8.
 * No Mac connection, model API, audio logging or SD writes. Fail closed on
 * resource exhaustion; keep the previously verified WakeNet9 task intact.
 */
#include "r259_offline_multinet.h"
#include "r259_offline_map.h"
#include "r224_media_owner.h"
#include "esp_mn_iface.h"
#include "esp_mn_models.h"
#include "esp_mn_speech_commands.h"
#include "model_path.h"
#include "esp_afe_config.h"
#include "esp_afe_sr_iface.h"
#include "esp_afe_sr_models.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define R259_WINDOW_MAX_MS 9000u
#define R259_FIFO_CAP 6400u
static const char *TAG="R259_MULTINET";
static volatile unsigned tries=0,found=0,low_internal=0,low_psram=0;
static volatile int last_id=0,last_fail=0;

void r259_read_diagnostics(unsigned *a,unsigned *h,int *last,int *err,
                           unsigned *internal,unsigned *psram){
 if(a){*a=tries;}
 if(h){*h=found;}
 if(last){*last=last_id;}
 if(err){*err=last_fail;}
 if(internal){*internal=low_internal;}
 if(psram){*psram=low_psram;}
}
static bool accepted_id(int cmd){
 for(size_t i=0;i<R259_COMMAND_COUNT;i++)
  if(R259_COMMANDS[i].command_id==cmd)return true;
 return false;
}
int r259_acoustic_command(esp_codec_dev_handle_t mic,unsigned window_ms){
 tries++;last_id=0;last_fail=0;
 if(!mic || window_ms<1000u || window_ms>R259_WINDOW_MAX_MS){last_fail=-1;return -1;}
 // Model + AFE + LCD/SD/PCM2 must coexist in actual free heap. If not,
 // fall back to WakeNet only: NEVER force PSRAM allocation into DMA RAM.
 low_internal=(unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL);
 low_psram=(unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
 if(low_internal<38000u || low_psram<1900000u){last_fail=-2;return -2;}
 uint32_t lease=0;
 if(!r224_audio_claim(R224_MEDIA_CAPTURE,&lease)){last_fail=-3;return -3;}
 int result=0;
 bool mic_open=false;
 srmodel_list_t *models=NULL;
 const esp_mn_iface_t *mn=NULL;
 model_iface_data_t *model=NULL;
 afe_config_t *cfg=NULL;
 const esp_afe_sr_iface_t *afe=NULL;
 esp_afe_sr_data_t *afe_data=NULL;
 int16_t *feed_pcm=NULL;
 int16_t *fifo=NULL;
 bool commands_allocated=false;
 do {
   models=esp_srmodel_init("model");
   if(!models){last_fail=-4;break;}
   char *name=esp_srmodel_filter(models,ESP_MN_PREFIX,"mn5q8_cn");
   if(!name){last_fail=-5;break;}
   mn=esp_mn_handle_from_name(name);
   if(!mn){last_fail=-6;break;}
   model=mn->create(name,(int)window_ms);
   if(!model){last_fail=-7;break;}
   int chunks=mn->get_samp_chunksize(model);
   if(chunks<=0 || chunks>(int)R259_FIFO_CAP/2 || mn->get_samp_rate(model)!=16000){last_fail=-8;break;}
   if(esp_mn_commands_alloc(mn,model)!=ESP_OK){last_fail=-9;break;}
   commands_allocated=true;
   for(size_t i=0;i<R259_COMMAND_COUNT;i++){
     if(esp_mn_commands_add(R259_COMMANDS[i].command_id,R259_COMMANDS[i].pinyin)!=ESP_OK){
       last_fail=-10;break;
     }
   }
   if(last_fail)break;
   if(esp_mn_commands_update()!=NULL){last_fail=-11;break;}
   cfg=afe_config_init("M",models,AFE_TYPE_SR,AFE_MODE_LOW_COST);
   if(!cfg){last_fail=-12;break;}
   cfg->aec_init=false;cfg->se_init=false;
   cfg->ns_init=true;cfg->vad_init=false;
   cfg->wakenet_init=false;cfg->agc_init=false;
   cfg->memory_alloc_mode=AFE_MEMORY_ALLOC_MORE_PSRAM;
   cfg->afe_ringbuf_size=12;
   afe=esp_afe_handle_from_config(cfg);
   if(!afe){last_fail=-13;break;}
   afe_data=afe->create_from_config(cfg);
   if(!afe_data){last_fail=-14;break;}
   int samples=afe->get_feed_chunksize(afe_data);
   int channels=afe->get_feed_channel_num(afe_data);
   if(samples<=0 || samples>3200 || channels!=1){last_fail=-15;break;}
   feed_pcm=heap_caps_malloc((size_t)samples*2, MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT);
   fifo=heap_caps_malloc(R259_FIFO_CAP*2,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
   if(!feed_pcm || !fifo){last_fail=-16;break;}
   esp_codec_dev_sample_info_t fmt={.sample_rate=16000,.channel=1,.bits_per_sample=16};
   if(esp_codec_dev_open(mic,&fmt)!=ESP_CODEC_DEV_OK){last_fail=-17;break;}
   mic_open=true;
   ESP_LOGI(TAG,"R259_TRUE_MN_WINDOW_READY chunks=%d feed=%d mem_internal=%u mem_psram=%u",
            chunks,samples,(unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL),
            (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
   int used=0;int64_t deadline=esp_timer_get_time()+(int64_t)window_ms*1000;
   unsigned fetched_frames=0,detect_frames=0;
   while(esp_timer_get_time()<deadline){
     if(esp_codec_dev_read(mic,feed_pcm,(size_t)samples*2)!=ESP_CODEC_DEV_OK){last_fail=-18;break;}
     if(afe->feed(afe_data,feed_pcm)<0){last_fail=-19;break;}
     // Poll the asynchronous AFE. Never block the mic feed thread for long;
     // if no processed frame is ready, the next real mic frame advances it.
     for(int fetch_i=0;fetch_i<3;fetch_i++){
       afe_fetch_result_t *frame=afe->fetch_with_delay(afe_data,1);
       if(!frame)break;
       if(frame->ret_value!=ESP_OK){last_fail=-20;break;}
       int count=frame->data_size/(int)sizeof(int16_t);
       if(!frame->data || count<=0 || count>(int)R259_FIFO_CAP-used){last_fail=-21;break;}
       memcpy(fifo+used,frame->data,(size_t)count*2);used+=count;fetched_frames++;
       while(used>=chunks){
         esp_mn_state_t state=mn->detect(model,fifo);
         detect_frames++;
         used-=chunks;
         if(used)memmove(fifo,fifo+chunks,(size_t)used*2);
         if(state==ESP_MN_STATE_DETECTED){
           esp_mn_results_t *rec=mn->get_results(model);
           if(rec && rec->num>0 && accepted_id(rec->command_id[0]) && rec->prob[0]>=0.60f){
             result=rec->command_id[0];last_id=result;found++;
             ESP_LOGI(TAG,"R259_VERIFIED_ACOUSTIC_CMD id=%d confidence=%u%%",
                     result,(unsigned)(rec->prob[0]*100));
           }
           break;
         }
       }
       if(result || last_fail)break;
     }
     if(result || last_fail)break;
   }
   ESP_LOGI(TAG,"R259_MN_WINDOW_RESULT id=%d err=%d fetch=%u detect=%u",
            result,last_fail,fetched_frames,detect_frames);
 }while(0);
 if(mic_open)esp_codec_dev_close(mic);
 if(feed_pcm)heap_caps_free(feed_pcm);
 if(fifo)heap_caps_free(fifo);
 if(afe_data && afe)afe->destroy(afe_data);
 if(cfg)afe_config_free(cfg);
 if(commands_allocated)esp_mn_commands_free();
 if(model && mn)mn->destroy(model);
 if(models)esp_srmodel_deinit(models);
 r224_audio_release(R224_MEDIA_CAPTURE,lease);
 if(last_fail)ESP_LOGW(TAG,"R259_MN_SAFE_FAILURE code=%d",last_fail);
 return last_fail?last_fail:result;
}

/* R263: read-only REAL model + AFE creation/destroy validation while the
 * original WakeNet is paused and owns no microphone. No fake acoustic hit.
 * We do not alter the production genuine-mic r259_acoustic_command at all.
 */
int r263_mn5_afe_alloc_probe(unsigned *psram_before,unsigned *psram_after,
                              unsigned *internal_after,unsigned *psram_recovered){
 srmodel_list_t *models=NULL;
 const esp_mn_iface_t *mn=NULL;
 model_iface_data_t *model=NULL;
 afe_config_t *cfg=NULL;
 const esp_afe_sr_iface_t *afe=NULL;
 esp_afe_sr_data_t *afe_data=NULL;
 int16_t *feed_pcm=NULL,*fifo=NULL;
 bool commands_allocated=false;
 int status=0;
 unsigned pre=(unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
 unsigned internal_before=(unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL);
 if(psram_before)*psram_before=pre;
 if(pre<3200000u || internal_before<38000u){status=-2;goto done;}
 models=esp_srmodel_init("model");
 if(!models){status=-4;goto done;}
 char *name=esp_srmodel_filter(models,ESP_MN_PREFIX,"mn5q8_cn");
 if(!name){status=-5;goto done;}
 mn=esp_mn_handle_from_name(name);
 if(!mn){status=-6;goto done;}
 model=mn->create(name,8000);
 if(!model){status=-7;goto done;}
 if(mn->get_samp_rate(model)!=16000 || mn->get_samp_chunksize(model)<=0){status=-8;goto done;}
 if(esp_mn_commands_alloc(mn,model)!=ESP_OK){status=-9;goto done;}
 commands_allocated=true;
 for(size_t i=0;i<R259_COMMAND_COUNT;i++){
   if(esp_mn_commands_add(R259_COMMANDS[i].command_id,R259_COMMANDS[i].pinyin)!=ESP_OK){
     status=-10;goto done;
   }
 }
 if(esp_mn_commands_update()!=NULL){status=-11;goto done;}
 cfg=afe_config_init("M",models,AFE_TYPE_SR,AFE_MODE_LOW_COST);
 if(!cfg){status=-12;goto done;}
 cfg->aec_init=false;cfg->se_init=false;cfg->ns_init=true;
 cfg->vad_init=false;cfg->wakenet_init=false;cfg->agc_init=false;
 cfg->memory_alloc_mode=AFE_MEMORY_ALLOC_MORE_PSRAM;
 cfg->afe_ringbuf_size=12;
 afe=esp_afe_handle_from_config(cfg);
 if(!afe){status=-13;goto done;}
 afe_data=afe->create_from_config(cfg);
 if(!afe_data){status=-14;goto done;}
 int samples=afe->get_feed_chunksize(afe_data);
 int channels=afe->get_feed_channel_num(afe_data);
 if(samples<=0 || samples>3200 || channels!=1){status=-15;goto done;}
 feed_pcm=heap_caps_malloc((size_t)samples*2,MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT);
 fifo=heap_caps_malloc(R259_FIFO_CAP*2,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 if(!feed_pcm||!fifo){status=-16;goto done;}
 if((unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM)<200000u ||
    (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL)<24000u)
   status=-23;
done:
 if(psram_after)*psram_after=(unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
 if(internal_after)*internal_after=(unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL);
 if(feed_pcm)heap_caps_free(feed_pcm);
 if(fifo)heap_caps_free(fifo);
 if(afe_data && afe)afe->destroy(afe_data);
 if(cfg)afe_config_free(cfg);
 if(commands_allocated)esp_mn_commands_free();
 if(model && mn)mn->destroy(model);
 if(models)esp_srmodel_deinit(models);
 unsigned restored=(unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
 if(psram_recovered)*psram_recovered=restored;
 if(status==0 && restored+8192u<pre)status=-25;
 ESP_LOGI(TAG,"R263_MN5_AFE_REAL_SDK_ALLOC rc=%d pre_psram=%u post_psram=%u returned=%u",
          status,pre,psram_after?*psram_after:0,restored);
 return status;
}
/* R265: ESP-SR's native MultiNet5 Q8 detect() on real 16kHz mono PCM.
 * The official multinet test app exercises raw 16k PCM; no synthesized hit,
 * no second microphone, no Mac, no storage of speech. This path avoids an
 * extra asynchronous AFE worker at the WakeNet->local-command boundary.
 * Frozen R259 AFE and R263 allocation probe remain separately available.
 */
int r265_direct_mn5_command(esp_codec_dev_handle_t mic,unsigned window_ms,
                            void (*on_listen_ready)(void)){
 tries++;last_id=0;last_fail=0;
 low_internal=(unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL);
 low_psram=(unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
 if(!mic || window_ms<1000u || window_ms>R259_WINDOW_MAX_MS){
  last_fail=-1;return -1;
 }
 if(low_internal<38000u || low_psram<3200000u){
  last_fail=-2;
  ESP_LOGW(TAG,"R265_MN5_RESERVE_DENIED internal=%u psram=%u",low_internal,low_psram);
  return -2;
 }
 uint32_t lease=0;
 if(!r224_audio_claim(R224_MEDIA_CAPTURE,&lease)){last_fail=-3;return -3;}
 srmodel_list_t *models=NULL;
 const esp_mn_iface_t *mn=NULL;
 model_iface_data_t *model=NULL;
 bool commands_allocated=false,mic_open=false;
 int16_t *chunk=NULL;
 int result=0;
 unsigned frames=0,read_errors=0;
 do{
  models=esp_srmodel_init("model");
  if(!models){last_fail=-4;break;}
  char *name=esp_srmodel_filter(models,ESP_MN_PREFIX,"mn5q8_cn");
  if(!name){last_fail=-5;break;}
  mn=esp_mn_handle_from_name(name);
  if(!mn){last_fail=-6;break;}
  model=mn->create(name,(int)window_ms);
  if(!model){last_fail=-7;break;}
  int n=mn->get_samp_chunksize(model);
  if(n<160 || n>3200 || mn->get_samp_rate(model)!=16000){last_fail=-8;break;}
  unsigned remain=(unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
  unsigned internal=(unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL);
  if(remain<300000u || internal<24000u){last_fail=-9;break;}
  if(esp_mn_commands_alloc(mn,model)!=ESP_OK){last_fail=-10;break;}
  commands_allocated=true;
  esp_mn_commands_clear();
  for(size_t i=0;i<R259_COMMAND_COUNT;i++){
   if(esp_mn_commands_add(R259_COMMANDS[i].command_id,R259_COMMANDS[i].pinyin)!=ESP_OK){
    last_fail=-11;break;
   }
  }
  if(last_fail)break;
  if(esp_mn_commands_update()!=NULL){last_fail=-12;break;}
  chunk=heap_caps_malloc((size_t)n*2,MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT);
  if(!chunk){last_fail=-13;break;}
  esp_codec_dev_sample_info_t fmt={.sample_rate=16000,.channel=1,.bits_per_sample=16};
  if(esp_codec_dev_open(mic,&fmt)!=ESP_CODEC_DEV_OK){last_fail=-14;break;}
  mic_open=true;
  // R266: readiness means the *physical ESP32 microphone* is open, not
  // merely that MN5 creation has started. The 8s clock starts afterwards.
  if(on_listen_ready)on_listen_ready();
  ESP_LOGI(TAG,"R265_REAL_PCM_MN5_READY chunks=%d window_ms=%u internal=%u psram=%u",
           n,window_ms,internal,remain);
  int64_t deadline=esp_timer_get_time()+(int64_t)window_ms*1000;
  while(esp_timer_get_time()<deadline){
   if(esp_codec_dev_read(mic,chunk,(size_t)n*2)!=ESP_CODEC_DEV_OK){
    last_fail=-15;read_errors++;break;
   }
   frames++;
   esp_mn_state_t state=mn->detect(model,chunk);
   if(state==ESP_MN_STATE_DETECTED){
    esp_mn_results_t *rec=mn->get_results(model);
    if(rec && rec->num>0 && accepted_id(rec->command_id[0]) &&
       rec->prob[0]>=0.60f){
     result=rec->command_id[0];last_id=result;found++;
     ESP_LOGI(TAG,"R265_TRUE_MN5_COMMAND id=%d conf_pct=%u",
              result,(unsigned)(rec->prob[0]*100));
    } else {
     ESP_LOGI(TAG,"R265_MN5_REJECTED_CANDIDATE frames=%u",frames);
    }
    break;
   }
   if(state==ESP_MN_STATE_TIMEOUT)break;
  }
  ESP_LOGI(TAG,"R265_MN5_ACOUSTIC_RESULT id=%d err=%d frames=%u read_err=%u",
           result,last_fail,frames,read_errors);
 }while(0);
 if(mic_open)esp_codec_dev_close(mic);
 if(chunk)heap_caps_free(chunk);
 if(commands_allocated)esp_mn_commands_free();
 if(model && mn)mn->destroy(model);
 if(models)esp_srmodel_deinit(models);
 r224_audio_release(R224_MEDIA_CAPTURE,lease);
 if(last_fail)ESP_LOGW(TAG,"R265_MN5_FAIL_CLOSED rc=%d",last_fail);
 return last_fail?last_fail:result;
}
