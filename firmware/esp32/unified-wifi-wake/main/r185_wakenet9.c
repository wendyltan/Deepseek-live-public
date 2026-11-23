/* R102 standalone WakeNet9 hardware acoustic candidate; no Wi-Fi, no DSH.
 * Not linked into R94. Model partition is NOT written by this component.
 * Requires a real authorized WakeNet9 hilexin model on an isolated test image.
 */
#include "r185_wakenet9.h"
#include "r224_media_owner.h"
#include <stdint.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_heap_caps.h"
#include "esp_wn_iface.h"
#include "esp_wn_models.h"
#ifdef DF_R327_MN5_DIRECT
#include "esp_mn_iface.h"
#include "esp_mn_models.h"
#include "esp_mn_speech_commands.h"
#ifdef DF_R340_AFE_MN5
#include "esp_afe_config.h"
#include "esp_afe_sr_iface.h"
#include "esp_afe_sr_models.h"
#endif
#endif
#include "model_path.h"
static const char *TAG="R185_WN9";
/* R251: only durable non-PCM stage markers, stored in RTC noinit RAM. */
extern void r251_wake_mark(unsigned stage);
static int64_t r251_not_before_us=0;
static bool r251_require_nonhit_before_rearm=false;
static unsigned r251_nonhit_frames=0;


static esp_codec_dev_handle_t mic;
static r185_listen_allowed allowed;
static r185_detect_event verified_wake_event;
static volatile bool user_opted_in=true,paused=true,owns_mic=false,ready=false;
static volatile bool reading_mic=false;
#ifdef DF_R341_AFE_DUALCORE
// Existing user-authenticated exclusive media lease; only the feeder
// reads microphone. Original r185 detector on core0 handles AFE fetch/MN5.
static const esp_afe_sr_iface_t *r341_afe=NULL;
static esp_afe_sr_data_t *r341_afe_data=NULL;
static int16_t *r341_frame=NULL;
static int r341_frame_samples=0;
static volatile bool r341_feeder_stop=false,r341_feeder_live=false;
static volatile bool r341_feeder_created=false;
static volatile uint32_t r341_raw_feed=0,r341_read_errors=0;
static volatile uint32_t r341_afe_feed_errors=0;
 /* Cross-core single-writer 32-bit diagnostic counters, no PCM or transcripts. */
 static volatile uint32_t r432_fetch_enter=0,r432_fetch_return=0;
 static volatile uint32_t r432_fetch_valid=0,r432_mn_total=0;
 /* R433: count ALL AFE return outcomes; never retain audio/sample contents.
  * Safe cross-core snapshot: counters only, approximate under concurrency.
  * Each branch may increment several independent error categories.
  */
 static volatile uint32_t r433_fetch_null=0,r433_ret_err=0;
 static volatile uint32_t r433_data_null=0,r433_size_bad=0;
 static volatile uint32_t r433_ret_timeout=0,r433_ret_other=0;
 static volatile int32_t r433_last_ret=0,r433_last_size=0;
 static volatile uint32_t r433_ring_peak_pct_x100=0;
static void r341_afe_feeder(void *ignored){
 (void)ignored;
 esp_codec_dev_sample_info_t fmt={.sample_rate=16000,.channel=1,.bits_per_sample=16};
 bool opened=false;uint32_t lease=0;
 r341_feeder_live=true;
 int64_t r341_last_feed_report_us=0;
 for(;!r341_feeder_stop;){
  if(paused || !user_opted_in || !allowed || !allowed()){
   if(opened){
    esp_codec_dev_close(mic);opened=false;
    r224_audio_release(R224_MEDIA_WAKE,lease);lease=0;owns_mic=false;
   }
   reading_mic=false;
   vTaskDelay(pdMS_TO_TICKS(15));continue;
  }
  if(!opened){
   if(!r224_audio_claim(R224_MEDIA_WAKE,&lease)){
    vTaskDelay(pdMS_TO_TICKS(35));continue;
   }
   owns_mic=true;
   if(esp_codec_dev_open(mic,&fmt)!=ESP_CODEC_DEV_OK){
    r341_read_errors++;
    r224_audio_release(R224_MEDIA_WAKE,lease);
    lease=0;owns_mic=false;
    vTaskDelay(pdMS_TO_TICKS(80));continue;
   }
   opened=true;
  }
  reading_mic=true;
  int status=esp_codec_dev_read(mic,r341_frame,(size_t)r341_frame_samples*2);
  reading_mic=false;
  if(status!=ESP_CODEC_DEV_OK){
   r341_read_errors++;
   esp_codec_dev_close(mic);opened=false;
   r224_audio_release(R224_MEDIA_WAKE,lease);lease=0;owns_mic=false;
   vTaskDelay(pdMS_TO_TICKS(80));continue;
  }
  if(paused || !user_opted_in || !allowed || !allowed())continue;
  if(r341_afe->feed(r341_afe_data,r341_frame)<0){
   r341_afe_feed_errors++;
   vTaskDelay(pdMS_TO_TICKS(2));continue;
  }
  r341_raw_feed++;
  int64_t r341_now=esp_timer_get_time();
  if(!r341_last_feed_report_us)r341_last_feed_report_us=r341_now;
  if(r341_now-r341_last_feed_report_us>=10000000){
   ESP_LOGI(TAG,"R341_FEED_RATE window_ms=%u fed_total=%lu "
            "mic_errors=%lu afe_feed_errors=%lu "
            "fetch_enter=%lu fetch_return=%lu fetch_valid=%lu mn_total=%lu "
            "afe_null=%lu afe_ret_err=%lu afe_data_null=%lu afe_size_bad=%lu "
            "afe_ret_timeout=%lu afe_ret_other=%lu last_ret=%ld "
            "last_size=%ld ring_peak_x100=%lu",
            (unsigned)((r341_now-r341_last_feed_report_us)/1000),
            (unsigned long)r341_raw_feed,(unsigned long)r341_read_errors,
            (unsigned long)r341_afe_feed_errors,
            (unsigned long)r432_fetch_enter,(unsigned long)r432_fetch_return,
            (unsigned long)r432_fetch_valid,(unsigned long)r432_mn_total,
            (unsigned long)r433_fetch_null,(unsigned long)r433_ret_err,
            (unsigned long)r433_data_null,(unsigned long)r433_size_bad,
            (unsigned long)r433_ret_timeout,(unsigned long)r433_ret_other,
            (long)r433_last_ret,(long)r433_last_size,
            (unsigned long)r433_ring_peak_pct_x100);
   r341_last_feed_report_us=r341_now;
  }
 }
 if(opened){
  esp_codec_dev_close(mic);
  r224_audio_release(R224_MEDIA_WAKE,lease);owns_mic=false;
 }
 reading_mic=false;r341_feeder_live=false;
 vTaskDelete(NULL);
}
#endif
static volatile bool r327_active_mn5=false;
const char *r185_wake_active_model(void){
 return "mn5q8_nihaodafeiyu";
}
/* The 4 boundaries are measured on the existing WakeNet task only.
 * A stalled read/detect leaves phase=1/3, while host can still query
 * the existing USB control task, without opening a second microphone.
 * 0 = waiting/other, 1=read, 2=permission-gate, 3=detect. */
static volatile r242_wake_stage r242_diag={0};
static volatile TickType_t r242_phase_tick=0;
/* R247 fixes an instrumentation blind spot: passing 16k samples into
 * WakeNet is not proof of keeping up with a 16k real-time stream.
 * Samples are reduced to bounded timing/energy counters in the existing
 * exclusive microphone task. No audio samples, waveforms or text retained.
 */
static r247_wake_speed r247_running={0};
static r247_wake_speed r247_completed={0};
static TickType_t r247_window_start=0;
/* Snapshot is published from the WakeNet task and read by the USB task. */
static portMUX_TYPE r247_snap_mux=portMUX_INITIALIZER_UNLOCKED;
static void r247_reset_window(void) {
 /* A gap for voice capture, PCM playback, or mic lease cannot count as
  * slow WakeNet throughput in the next continuous listen window. */
 r247_window_start=0;
 r247_running=(r247_wake_speed){
   .model_chunk=r247_running.model_chunk,
   .model_channels=r247_running.model_channels,
   .model_rate=r247_running.model_rate,
 };
}
static void r247_roll_window(void) {
 TickType_t now=xTaskGetTickCount();
 if(!r247_window_start){r247_window_start=now;return;}
 unsigned elapsed_ms=(unsigned)((now-r247_window_start)*portTICK_PERIOD_MS);
 if(elapsed_ms < 10000u)return;
 r247_running.window_ms=elapsed_ms;
 portENTER_CRITICAL(&r247_snap_mux);
 r247_completed=r247_running;
 portEXIT_CRITICAL(&r247_snap_mux);
 r247_running=(r247_wake_speed){
   .model_chunk=r247_completed.model_chunk,
   .model_channels=r247_completed.model_channels,
   .model_rate=r247_completed.model_rate,
 };
 r247_window_start=now;
}
void r247_wake_speed_read(r247_wake_speed *out) {
 if(!out)return;
 /* Publish one consistent snapshot without blocking on the microphone. */
 portENTER_CRITICAL(&r247_snap_mux);
 *out=r247_completed;
 portEXIT_CRITICAL(&r247_snap_mux);
}
static inline unsigned r247_duration_us(int64_t start) {
 int64_t elapsed=esp_timer_get_time()-start;
 return elapsed<=0?0:(elapsed>1000000?1000000u:(unsigned)elapsed);
}
static inline void r242_set_phase(unsigned p){
 r242_diag.phase=p;
 r242_phase_tick=xTaskGetTickCount();
}
void r242_wake_stage_read(r242_wake_stage *out) {
 if(!out)return;
 out->read_enter=r242_diag.read_enter;
 out->read_ok=r242_diag.read_ok;
 out->read_error=r242_diag.read_error;
 out->gate_skip=r242_diag.gate_skip;
 out->detect_enter=r242_diag.detect_enter;
 out->detect_return=r242_diag.detect_return;
 out->detected=r242_diag.detected;
 out->open_fail=r242_diag.open_fail;
 out->phase=r242_diag.phase;
 TickType_t elapsed=xTaskGetTickCount()-r242_phase_tick;
 out->phase_age_ms=(unsigned)(elapsed*portTICK_PERIOD_MS);
}
static void task(void *unused) {
 (void)unused;
 srmodel_list_t *models=NULL;
 const esp_wn_iface_t *iface=NULL;
 const esp_mn_iface_t *mn_iface=NULL;
 bool mn_active=false,mn_allocated=false;
 model_iface_data_t *model=NULL;
 int16_t *frame=NULL;
 bool opened=false;
#ifdef DF_R340_AFE_MN5
 // Fail-closed official mono AFE in the same mic owner task. This first
 // candidate measures AFE and MN costs; does not claim realtime throughput.
 afe_config_t *r340_cfg=NULL;
 const esp_afe_sr_iface_t *r340_afe=NULL;
 esp_afe_sr_data_t *r340_data=NULL;
 int r340_read_samples=0;
 uint32_t r340_fetch_count=0,r340_mn_count=0;
 uint32_t r340_bad_feed=0,r340_bad_fetch=0;
 int64_t r340_start_us=0;
#ifdef DF_R344_AFE_PROFILE
 // Counters only; NEVER retain or log raw mic samples.
 uint32_t r344_null=0,r344_ret=0,r344_nodata=0,r344_size=0;
 uint32_t r344_detect_count=0,r344_detect_sum=0,r344_detect_max=0;
 uint32_t r344_hist[5]={0}; // <=16ms,<=32ms,<=64ms,<=128ms,>128ms
#endif
#ifdef DF_R387_AFE_FETCH_PROFILE
 uint64_t r387_fetch_us_sum=0;
 uint32_t r387_fetch_n=0,r387_fetch_max_us=0;
 uint32_t r387_fetch_buckets[5]={0};
#endif
#endif
 uint32_t mic_lease=0;
 esp_codec_dev_sample_info_t pcm={.sample_rate=16000,.channel=1,.bits_per_sample=16};
 /* Initialize once at boot. Listening remains user-opt-in OFF until the
  * verified local USB owner explicitly enables WakeNet. */
 /* Official model in a dedicated verified Flash partition, no raw speech
  * audio or transcripts are written or transmitted before a wake event. */
 models=esp_srmodel_init("model");
 if (!models){ESP_LOGE(TAG,"UNIFIED_MODEL_INIT_LOAD_FAIL");goto fail;}
 ESP_LOGI(TAG,"UNIFIED_MN5_PRECHECK internal_free=%u internal_largest=%u psram_free=%u",
  (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
  (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL),
  (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
 int n=0,frequency=0,model_channels=0;
#ifdef DF_R327_MN5_DIRECT
 /* Isolated direct-MultiNet candidate (Xiaozhi pattern, R265 local SDK).
  * One model/one board microphone; keep original WN9 as boot fallback.
  * No command keyword can bypass the existing physical wake/Voice3 gate. */
 if(heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL)>=38000u &&
    heap_caps_get_free_size(MALLOC_CAP_SPIRAM)>=3200000u){
  char *mn_name=esp_srmodel_filter(models,ESP_MN_PREFIX,"mn5q8_cn");
  if(!mn_name)ESP_LOGE(TAG,"UNIFIED_MN5_MODEL_FILTER_FAIL");
  if(mn_name)mn_iface=esp_mn_handle_from_name(mn_name);
  if(!mn_iface)ESP_LOGE(TAG,"UNIFIED_MN5_HANDLE_UNSUPPORTED");
  if(mn_iface)model=mn_iface->create(mn_name,3000);
  if(!model)ESP_LOGE(TAG,"UNIFIED_MN5_CREATE_FAIL internal_largest=%u psram_free=%u",
    (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL),
    (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
  if(model){
   n=mn_iface->get_samp_chunksize(model);
   frequency=mn_iface->get_samp_rate(model);
   model_channels=1;
   if(n>=160&&n<=3200&&frequency==16000 &&
      esp_mn_commands_alloc(mn_iface,model)==ESP_OK){
    mn_allocated=true;
    ESP_LOGI(TAG,"UNIFIED_MN5_MODEL_CREATED chunksize=%d rate=%d psram_free=%u",
      n,frequency,(unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
    if(esp_mn_commands_clear()==ESP_OK &&
       esp_mn_commands_add(1,"ni hao da fei yu")==ESP_OK &&
       esp_mn_commands_update()==NULL &&
       mn_iface->set_det_threshold(model,0.65f)>=0){
       mn_active=true;
       ESP_LOGI(TAG,"UNIFIED_MN5_COMMAND_CONFIG_READY keyword=ni_hao_da_fei_yu");
    }else{
       ESP_LOGE(TAG,"UNIFIED_MN5_COMMAND_CONFIG_FAILED");
    }
   }else{ESP_LOGE(TAG,"UNIFIED_MN5_CHUNK_OR_ALLOC_FAILED n=%d rate=%d",n,frequency);}
  }
 }else{ESP_LOGE(TAG,"UNIFIED_MN5_MIN_HEAP_GATE_FAILED");}
#ifdef DF_R340_AFE_MN5
 if(mn_active){
  r340_cfg=afe_config_init("M",models,AFE_TYPE_SR,AFE_MODE_LOW_COST);
  if(r340_cfg){
   r340_cfg->aec_init=false;r340_cfg->se_init=false;
   r340_cfg->ns_init=true;r340_cfg->vad_init=false;
   r340_cfg->wakenet_init=false;r340_cfg->agc_init=false;
   r340_cfg->memory_alloc_mode=AFE_MEMORY_ALLOC_MORE_PSRAM;
   r340_cfg->afe_ringbuf_size=32;
   /* Priority CPU0 scheduling: feeder6 > AFE5 > LVGL4 > animator3.
    * Keep MN5 detector exclusively on CPU1 prio4.
    * Previous config left the internal AFE worker's affinity unspecified,
    * causing valid mic feed without any consumer output after LVGL isolation.
    */
   r340_cfg->afe_perferred_core=0;
   r340_cfg->afe_perferred_priority=5;
   ESP_LOGI(TAG,"R432_AFE_TASK core=%d priority=%d ns=%u",
      r340_cfg->afe_perferred_core,r340_cfg->afe_perferred_priority,
      (unsigned)r340_cfg->ns_init);
   r340_afe=esp_afe_handle_from_config(r340_cfg);
  }
  if(r340_afe)r340_data=r340_afe->create_from_config(r340_cfg);
  int in=r340_data?r340_afe->get_feed_chunksize(r340_data):0;
  int out=r340_data?r340_afe->get_fetch_chunksize(r340_data):0;
  int ch=r340_data?r340_afe->get_feed_channel_num(r340_data):0;
  if(in<160 || in>3200 || out!=n || ch!=1){
   ESP_LOGW(TAG,"R340_AFE_FAIL_CLOSED feed=%d fetch=%d mn=%d ch=%d",in,out,n,ch);
   mn_active=false;
  }else{
   r340_read_samples=in;
   ESP_LOGI(TAG,"R340_AFE_READY feed=%d fetch=%d mn=%d ch=%d",in,out,n,ch);
  }
 }
 if(!mn_active){
  if(r340_data && r340_afe)r340_afe->destroy(r340_data);
  if(r340_cfg)afe_config_free(r340_cfg);
  r340_data=NULL;r340_afe=NULL;r340_cfg=NULL;
 }
#endif
 if(!mn_active){
  if(mn_allocated)esp_mn_commands_free();
  mn_allocated=false;
  if(model&&mn_iface)mn_iface->destroy(model);
  model=NULL;mn_iface=NULL;
  ESP_LOGE(TAG,"UNIFIED_MN5_INIT_FAILED_TOUCH_USB_ONLY");
 }
#endif
 if(!mn_active){
  /* Custom-only product mode: no installed WakeNet9 model.
   * Never try a missing model or claim voice works after init failure.
   * Keep the touch controls, USB diagnostics and the full Wi-Fi
   * ASR/DSH/TTS/animation pipeline available for supervised recovery. */
  ESP_LOGE(TAG,"UNIFIED_CUSTOM_MN5_WAKE_REQUIRED_NOT_READY");
  goto fail;
 }
 if(n<160||n>3200||frequency!=16000)goto fail;
 r327_active_mn5=mn_active;
 r247_running.model_chunk=(unsigned)n;
 r247_running.model_channels=(unsigned)(model_channels>0?model_channels:0);
 r247_running.model_rate=(unsigned)frequency;
 /* R250: keep the 1KiB input frame in internal RAM so WakeNet
  * does not repeatedly traverse 40MHz external RAM for each sample. */
 int allocation_samples=n;
#ifdef DF_R340_AFE_MN5
 if(mn_active && r340_read_samples>allocation_samples)
  allocation_samples=r340_read_samples;
#endif
 frame=heap_caps_malloc((size_t)allocation_samples*2,
                        MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT);
 if(!frame)goto fail;
#ifdef DF_R382_MN5_BENCH_ONLY
 // R382: pure MN5 compute/PSRAM bench on deterministic silence.
 // No mic, no DSH, no extra captures, no audio saved, no wake callback.
 // 16 warm-up frames + 64 measured frames (bounded to 80).
 // Never ship as production: startup latency and MN5 state are altered.
 if(mn_active && mn_iface && model){
  memset(frame,0,(size_t)n*sizeof(int16_t));
  uint64_t total_us=0;
  uint32_t min_us=UINT32_MAX,max_us=0;
  uint32_t buckets[5]={0};
  uint32_t non_detecting=0;
  for(unsigned step=0;step<80u;step++){
   int64_t start_us=esp_timer_get_time();
   esp_mn_state_t state=mn_iface->detect(model,frame);
   int64_t elapsed_us=esp_timer_get_time()-start_us;
   if(state==ESP_MN_STATE_DETECTED)non_detecting++;
   if(step<16u)continue;
   uint32_t duration=(elapsed_us>0 && elapsed_us<UINT32_MAX)
        ?(uint32_t)elapsed_us:UINT32_MAX;
   total_us+=duration;
   if(duration<min_us)min_us=duration;
   if(duration>max_us)max_us=duration;
   unsigned bucket=duration<=16000u?0u:
       duration<=32000u?1u:duration<=64000u?2u:
       duration<=128000u?3u:4u;
   buckets[bucket]++;
  }
  ESP_LOGI(TAG,"R382_MN5_PUREBENCH model=mn5q8_cn measured=64 "
            "mean_us=%llu min_us=%u max_us=%u "
            "le16=%u le32=%u le64=%u le128=%u gt128=%u "
            "unexpected_detect=%u internal_free=%u psram_free=%u",
            (unsigned long long)(total_us/64u),
            (unsigned)min_us,(unsigned)max_us,
            (unsigned)buckets[0],(unsigned)buckets[1],
            (unsigned)buckets[2],(unsigned)buckets[3],
            (unsigned)buckets[4],(unsigned)non_detecting,
            (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
            (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
  // Reset silence input for audio-front-end phase. Do not claim clean
  // means acoustic accuracy; this is a kernel-only throughput gate.
  memset(frame,0,(size_t)n*sizeof(int16_t));
 }
#endif
 /* Check real reserve AFTER loading. Do not starve LCD DMA/PCM2. */
 if((mn_active &&
     (heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL)<24000u ||
      heap_caps_get_free_size(MALLOC_CAP_SPIRAM)<300000u)) ||
    (!mn_active &&
     (heap_caps_get_free_size(MALLOC_CAP_INTERNAL)<72*1024 ||
      heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL)<32*1024 ||
      heap_caps_get_free_size(MALLOC_CAP_SPIRAM)<530000))){
   ESP_LOGW(TAG,"POST_MODEL_RESERVE_FAILED_TOUCH_ONLY");goto fail;
 }
#ifdef DF_R341_AFE_DUALCORE
 if(mn_active){
  r341_afe=r340_afe;r341_afe_data=r340_data;
  r341_frame_samples=r340_read_samples;
  r341_frame=heap_caps_malloc((size_t)r341_frame_samples*2,
                              MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT);
  if(!r341_frame)goto fail;
  r341_feeder_stop=false;
  if(xTaskCreatePinnedToCore(r341_afe_feeder,"r341_afe_mic",
      5*1024,NULL,6,NULL,0)!=pdPASS)goto fail;
  r341_feeder_created=true;
 }
#endif
 ready=true;paused=false;
 ESP_LOGI(TAG,"R327_WAKE_READY model=%s internal_largest=%u psram_free=%u",
          r185_wake_active_model(),
          (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL),
          (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
 for(;;){
  if(!user_opted_in || paused || !allowed || !allowed()){
   r247_reset_window();
   r242_set_phase(0);
   if(opened){esp_codec_dev_close(mic);opened=false;
    r224_audio_release(R224_MEDIA_WAKE,mic_lease);mic_lease=0;owns_mic=false;}
   vTaskDelay(pdMS_TO_TICKS(40));continue;
  }
#ifdef DF_R341_AFE_DUALCORE
  if(mn_active && !owns_mic){
   r247_reset_window();r242_set_phase(0);
   vTaskDelay(pdMS_TO_TICKS(10));continue;
  }
#endif
  if(!opened
#ifdef DF_R341_AFE_DUALCORE
     && !mn_active
#endif
     ){
   if(!r224_audio_claim(R224_MEDIA_WAKE,&mic_lease)){
    vTaskDelay(pdMS_TO_TICKS(60));continue;
   }
   owns_mic=true; // Covers codec OPEN, too: no false wait_released.
   if(esp_codec_dev_open(mic,&pcm)!=ESP_CODEC_DEV_OK){
    r242_diag.open_fail++;
    r224_audio_release(R224_MEDIA_WAKE,mic_lease);mic_lease=0;
    owns_mic=false;
    vTaskDelay(pdMS_TO_TICKS(100));continue;
   }
   opened=true;
  }
  r247_roll_window();
  reading_mic=true;
  r242_diag.read_enter++;
  r242_set_phase(1);
  int64_t read_start=esp_timer_get_time();
  int read_rc=ESP_CODEC_DEV_OK;
#ifdef DF_R341_AFE_DUALCORE
  if(mn_active){
#ifdef DF_R387_AFE_FETCH_PROFILE
   int64_t r387_fetch_start=esp_timer_get_time();
#endif
   r432_fetch_enter++;
   afe_fetch_result_t *enhanced=r340_afe->fetch_with_delay(
          r340_data,pdMS_TO_TICKS(15));
   r432_fetch_return++;
#ifdef DF_R387_AFE_FETCH_PROFILE
   uint32_t elapsed= (uint32_t)(esp_timer_get_time()-r387_fetch_start);
   r387_fetch_us_sum+=elapsed;
   r387_fetch_n++;
   if(elapsed>r387_fetch_max_us)r387_fetch_max_us=elapsed;
   unsigned idx=elapsed<=16000u?0u:elapsed<=32000u?1u:
                elapsed<=64000u?2u:elapsed<=128000u?3u:4u;
   r387_fetch_buckets[idx]++;
#endif
   if(!enhanced){
    r433_fetch_null++;
#ifdef DF_R344_AFE_PROFILE
    r344_null++;
#endif
    r340_bad_fetch++;r242_set_phase(0);continue;
   }
   /* Observe both the status code and any usable data metadata even when
    * returned results are invalid. Do not dereference the audio buffer. */
   r433_last_ret=(int32_t)enhanced->ret_value;
   r433_last_size=enhanced->data_size;
   if(enhanced->ret_value!=ESP_OK){
    r433_ret_err++;
    if(enhanced->ret_value==ESP_ERR_TIMEOUT)r433_ret_timeout++;
    else r433_ret_other++;
   }
   if(!enhanced->data)r433_data_null++;
   if(enhanced->data_size!=(int)((size_t)n*sizeof(int16_t)))
    r433_size_bad++;
   if(enhanced->ringbuff_free_pct>=0.0f &&
      enhanced->ringbuff_free_pct<=1.0f){
    uint32_t r433_ring=(uint32_t)(enhanced->ringbuff_free_pct*10000.0f);
    if(r433_ring>r433_ring_peak_pct_x100)
     r433_ring_peak_pct_x100=r433_ring;
   }
   if(enhanced->ret_value!=ESP_OK || !enhanced->data ||
      enhanced->data_size!=(int)((size_t)n*sizeof(int16_t))){
#ifdef DF_R344_AFE_PROFILE
    if(enhanced->ret_value!=ESP_OK)r344_ret++;
    if(!enhanced->data)r344_nodata++;
    if(enhanced->data_size!=(int)((size_t)n*sizeof(int16_t)))r344_size++;
#endif
    r340_bad_fetch++;r242_set_phase(0);continue;
   }
   memcpy(frame,enhanced->data,(size_t)n*sizeof(int16_t));
   r340_fetch_count++;
   r432_fetch_valid++;
  }else
#endif
  read_rc=esp_codec_dev_read(mic,frame,(size_t)(
#ifdef DF_R340_AFE_MN5
    mn_active?r340_read_samples:
#endif
    n)*2);
  unsigned read_us=r247_duration_us(read_start);
  reading_mic=false;
  r242_set_phase(2);
  r247_running.read_us_sum+=read_us;
  if(read_us>r247_running.read_us_max)r247_running.read_us_max=read_us;
  if(read_rc!=ESP_CODEC_DEV_OK){
   r247_reset_window();
   r242_diag.read_error++;
   esp_codec_dev_close(mic);opened=false;
   r224_audio_release(R224_MEDIA_WAKE,mic_lease);mic_lease=0;owns_mic=false;
   vTaskDelay(pdMS_TO_TICKS(120));continue;
  }
  r242_diag.read_ok++;
#if defined(DF_R340_AFE_MN5) && !defined(DF_R341_AFE_DUALCORE)
  if(mn_active){
   if(r340_afe->feed(r340_data,frame)<0){
    r340_bad_feed++;r242_set_phase(0);continue;
   }
   afe_fetch_result_t *out=r340_afe->fetch_with_delay(r340_data,0);
   if(!out){r242_set_phase(0);continue;}
   if(out->ret_value!=ESP_OK || !out->data ||
       out->data_size!=(int)((size_t)n*sizeof(int16_t))){
    r340_bad_fetch++;r242_set_phase(0);continue;
   }
   memcpy(frame,out->data,(size_t)n*sizeof(int16_t));
   r340_fetch_count++;
  }
#endif
  if(paused || !user_opted_in || !allowed()){
   r247_reset_window();
   r242_diag.gate_skip++;
   r242_set_phase(0);
   continue;
  }
  /* Observe true per-frame input energy without buffering it. */
  unsigned peak=0;
  for(int i=0;i<n;i++){
   int32_t v=frame[i];
   if(v<0)v=-v;
   if((unsigned)v>peak)peak=(unsigned)v;
  }
  r247_running.frames++;
  if(peak>r247_running.peak_16bit)r247_running.peak_16bit=peak;
  if(peak>=2500u)r247_running.loud_frames++;
  if(peak>=32760u)r247_running.clipped_frames++;
  r242_diag.detect_enter++;
  r242_set_phase(3);
  int64_t detect_start=esp_timer_get_time();
  int wake_result=0;
  if(mn_active){
#ifdef DF_R340_AFE_MN5
   r340_mn_count++;
#ifdef DF_R341_AFE_DUALCORE
   r432_mn_total++;
#endif
#endif
   esp_mn_state_t state=mn_iface->detect(model,frame);
   if(state==ESP_MN_STATE_DETECTED){
    esp_mn_results_t *rec=mn_iface->get_results(model);
    if(rec){
     for(int i=0;i<rec->num && i<ESP_MN_RESULT_MAX_NUM;i++){
      if(rec->command_id[i]==1 && rec->prob[i]>=0.65f){
       wake_result=1;
       break;
      }
     }
    }
    mn_iface->clean(model);
   }else if(state==ESP_MN_STATE_TIMEOUT){
    mn_iface->clean(model);
   }
  }else{
   wake_result=iface->detect(model,frame);
  }
  unsigned detect_us=r247_duration_us(detect_start);
#if defined(DF_R344_AFE_PROFILE) && defined(DF_R340_AFE_MN5)
  if(mn_active){
   r344_detect_count++;r344_detect_sum+=detect_us;
   if(detect_us>r344_detect_max)r344_detect_max=detect_us;
   unsigned bucket=detect_us<=16000u?0:detect_us<=32000u?1:
                   detect_us<=64000u?2:detect_us<=128000u?3:4;
   r344_hist[bucket]++;
  }
#endif
  r247_running.detect_us_sum+=detect_us;
  if(detect_us>r247_running.detect_us_max)r247_running.detect_us_max=detect_us;
  r242_diag.detect_return++;
  r242_set_phase(0);
#ifdef DF_R340_AFE_MN5
  if(mn_active){
   int64_t now=esp_timer_get_time();
   if(!r340_start_us)r340_start_us=now;
   if(now-r340_start_us>=10000000){
    ESP_LOGI(TAG,"R340_AFE_RATE elapsed_ms=%u fed=%lu fetch=%lu mn=%lu "
             "feed_bad=%lu fetch_bad=%lu psram=%u largest_internal=%u",
             (unsigned)((now-r340_start_us)/1000),
#ifdef DF_R341_AFE_DUALCORE
             (unsigned long)r341_raw_feed,(unsigned long)r340_fetch_count,
#else
             (unsigned long)r340_fetch_count,(unsigned long)r340_fetch_count,
#endif
             (unsigned long)r340_mn_count,(unsigned long)r340_bad_feed,
             (unsigned long)r340_bad_fetch,
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM),
             (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL));
#ifdef DF_R387_AFE_FETCH_PROFILE
    ESP_LOGI(TAG,"R387_FETCH_PROFILE n=%lu avg_us=%lu max_us=%lu "
             "h16=%lu h32=%lu h64=%lu h128=%lu hover=%lu",
             (unsigned long)r387_fetch_n,
             (unsigned long)(r387_fetch_n?r387_fetch_us_sum/r387_fetch_n:0),
             (unsigned long)r387_fetch_max_us,
             (unsigned long)r387_fetch_buckets[0],
             (unsigned long)r387_fetch_buckets[1],
             (unsigned long)r387_fetch_buckets[2],
             (unsigned long)r387_fetch_buckets[3],
             (unsigned long)r387_fetch_buckets[4]);
    r387_fetch_n=r387_fetch_max_us=0;
    r387_fetch_us_sum=0;
    for(unsigned k=0;k<5;k++)r387_fetch_buckets[k]=0;
#endif
#ifdef DF_R344_AFE_PROFILE
    // p95 is a bounded bucket estimate, not an exact percentile.
    uint32_t p95_target=(r344_detect_count*95u+99u)/100u, cumulative=0;
    unsigned p95_bucket=0;
    for(unsigned k=0;k<5;k++){
     cumulative+=r344_hist[k];
     if(cumulative>=p95_target){p95_bucket=k;break;}
    }
    ESP_LOGI(TAG,"R344_PROFILE null=%lu ret=%lu nodata=%lu size=%lu "
             "detect_n=%lu avg_us=%lu max_us=%lu p95_bucket=%u "
             "h16=%lu h32=%lu h64=%lu h128=%lu hover=%lu",
             (unsigned long)r344_null,(unsigned long)r344_ret,
             (unsigned long)r344_nodata,(unsigned long)r344_size,
             (unsigned long)r344_detect_count,
             (unsigned long)(r344_detect_count?
              r344_detect_sum/r344_detect_count:0u),
             (unsigned long)r344_detect_max,p95_bucket,
             (unsigned long)r344_hist[0],(unsigned long)r344_hist[1],
             (unsigned long)r344_hist[2],(unsigned long)r344_hist[3],
             (unsigned long)r344_hist[4]);
    r344_null=r344_ret=r344_nodata=r344_size=0;
    r344_detect_count=r344_detect_sum=r344_detect_max=0;
    for(unsigned k=0;k<5;k++)r344_hist[k]=0;
#endif
    r340_fetch_count=r340_mn_count=0;
#ifdef DF_R341_AFE_DUALCORE
    // r341_raw_feed is monotonic; the independent feeder emits a 10s
    // wall-clock snapshot even if no AFE output reaches the detector.
#endif
    r340_bad_feed=r340_bad_fetch=0;r340_start_us=now;
   }
  }
#endif
  /* Do not generate repeated hits from stale model smoothing/history. A
   * genuine non-hit streak must be observed before the next rearm. */
  if(wake_result<=0 && r251_require_nonhit_before_rearm){
   if(++r251_nonhit_frames>=8u)r251_require_nonhit_before_rearm=false;
  }
  if(wake_result>0 && !r251_require_nonhit_before_rearm &&
     esp_timer_get_time()>=r251_not_before_us){
   r251_wake_mark(101); /* Genuine model hit, before all handoff calls. */
   r251_not_before_us=esp_timer_get_time()+3000000;
   r251_require_nonhit_before_rearm=true;
   r251_nonhit_frames=0;
   r247_reset_window();
   r242_diag.detected++;
   paused=true; /* Transfer single microphone ownership before invoking event. */
#ifdef DF_R341_AFE_DUALCORE
   if(mn_active){
    for(unsigned ms=0;owns_mic && ms<600;ms+=10)
     vTaskDelay(pdMS_TO_TICKS(10));
    if(owns_mic){
     ESP_LOGE(TAG,"R341_MIC_HANDOFF_TIMEOUT fail_closed=1");
     paused=false;continue;
    }
    r340_afe->reset_buffer(r340_data);
   }else
#endif
   {
    esp_codec_dev_close(mic);opened=false;
    r224_audio_release(R224_MEDIA_WAKE,mic_lease);
    mic_lease=0;owns_mic=false;
   }
   /* R251 suspected crash isolation: do not call WakeNet's optional
    * clean() in the hot detection callback. The earlier R245 path was
    * unverified by human wake and its failure may interrupt this task
    * before the first verified DETECTED event reaches Mac. A 3-second
    * cooldown only discards repeat hit events; frames are still fed to
    * the SAME model so timing and state continue naturally. Never
    * silently destroy/recreate the model or start another mic reader.
    */
   r251_wake_mark(102); /* WN mic closed and its lease released. */
   ESP_LOGI(TAG,"R327_VERIFIED_PHYSICAL_WAKE model=%s",r185_wake_active_model()); /* no PCM/audio/text in logs */
   r251_wake_mark(103); /* About to deliver genuine physical wake event. */
#ifdef DF_R327_MN5_ACOUSTIC_ONLY
#ifdef DF_R341_AFE_DUALCORE
   if(mn_active)
    ESP_LOGI(TAG,"R341_MN5_ACOUSTIC_ONLY_HIT count=%u",
             (unsigned)r242_diag.detected);
   else
    ESP_LOGI(TAG,"R341_WN9_FALLBACK_HIT count=%u",
             (unsigned)r242_diag.detected);
#else
   ESP_LOGI(TAG,"R340_ACOUSTIC_ONLY_HIT count=%u",
            (unsigned)r242_diag.detected);
#endif
   paused=false; // no DSH/TTS, reopen mic only after existing cooldown
#else
   if(verified_wake_event)verified_wake_event();
#endif
   /* Greeting worker may already have advanced RTC marker: never rewind. */
  }
 }
fail:
 ready=false;paused=true;
#ifdef DF_R341_AFE_DUALCORE
 if(r341_feeder_created){
  r341_feeder_stop=true;
  for(unsigned ms=0;r341_feeder_live && ms<700;ms+=10)
   vTaskDelay(pdMS_TO_TICKS(10));
  if(r341_feeder_live || owns_mic){
   ESP_LOGE(TAG,"R341_FEEDER_STOP_TIMEOUT retain_resources");
   vTaskDelete(NULL); // never free AFE behind a live producer
  }
 }
 if(r341_frame){heap_caps_free(r341_frame);r341_frame=NULL;}
#endif
 if(opened){esp_codec_dev_close(mic);
  r224_audio_release(R224_MEDIA_WAKE,mic_lease);mic_lease=0;owns_mic=false;}
 if(frame)heap_caps_free(frame);
#ifdef DF_R340_AFE_MN5
 if(r340_data && r340_afe)r340_afe->destroy(r340_data);
 if(r340_cfg)afe_config_free(r340_cfg);
#endif
 if(mn_active && model && mn_iface)mn_iface->destroy(model);
 else if(model && iface)iface->destroy(model);
 if(mn_allocated)esp_mn_commands_free();
 r327_active_mn5=false;
 if(models)esp_srmodel_deinit(models);
 ESP_LOGW(TAG,"UNIFIED_MN5_OFF_TOUCH_USB_ONLY");
 vTaskDelete(NULL);
}
bool r185_wake_start(esp_codec_dev_handle_t source,r185_listen_allowed can,
                   r185_detect_event event){
 if(!source||!can||!event)return false;
 mic=source;allowed=can;verified_wake_event=event;
 paused=true;user_opted_in=true;ready=false;
 /* R250: keep model work from being preempted by same-core USB
  * control priority3; equal to animation priority4; no second mic. */
 return xTaskCreatePinnedToCore(task,"r185_wake",8*1024,NULL,4,NULL,1)==pdPASS;
}
void r185_wake_enable(bool enabled){user_opted_in=enabled;paused=!enabled;}
bool r185_wake_enabled(void){return ready && user_opted_in && !paused;}
void r185_wake_pause(void){paused=true;}
void r185_wake_resume(void){paused=!user_opted_in;}
bool r185_wake_wait_released(unsigned max_ms){
 r185_wake_pause();
 for(unsigned elapsed=0;owns_mic && elapsed<max_ms;elapsed+=20)
  vTaskDelay(pdMS_TO_TICKS(20));
 return !owns_mic;
}
bool r185_wake_ready(void){return ready;}

bool r185_wake_owns_mic(void){return owns_mic;}
bool r185_wake_read_inflight(void){return reading_mic;}
