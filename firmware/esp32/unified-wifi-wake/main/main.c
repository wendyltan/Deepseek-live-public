// SPDX-License-Identifier: MIT
// H10 bounded duplex USB voice with coherent full PCM playback, not Opus on device: one REAL 240x240 classic animation and one REAL
// locally generated Qwen3 WAV; NOT live microphone->DSH nor an SD file test.
// Third-party private media embedded only into the isolated build in Tools.
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#ifdef DF_R46_PCM2_ONLY
#include "freertos/stream_buffer.h"
#endif
#include "esp_log.h"
#include "esp_system.h"
#include "esp_attr.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "esp_random.h"
#include "esp_partition.h"
#include "esp_lv_adapter.h"
#include "bsp/esp-bsp.h"
#include "bsp/display.h"
#include "esp_codec_dev.h"
#include "lvgl.h"
#include "audio_playback.h"
#include "mic_capture.h"
#include "usb_control.h"
#include "anim_scheduler.h"
#include "ui_controller.h"
#include "audio_playback_state.h"
#include "ui_controller_state.h"
/* lvgl.h includes snapshot header when enabled */
#ifdef DF_R33_BOARD_UI
#include "r42_mic_icon.h"
#endif
#ifdef DF_R33_BOARD_UI
#include "driver/i2c_master.h"
#endif
#include "r62_wifi.h"
#include "r268_lan_transport.h"
#include "r83_user_sd.h"
#include "r133_features.h"
#include "r150_rules.h"
#include "r140_pcm_edges.h"
#include "dfsp_decoder.h"
#define R71_DFSP_COMPRESSED_MAX 65536u
#include "dfsp_blit.h"
#include "dfsp_stage.h"
#include "r412_listening_overlay.h"
#include "driver/usb_serial_jtag.h"
#include "driver/usb_serial_jtag_vfs.h"
#include <stdio.h>
#include <stdlib.h>
#include "esp_rom_crc.h"
#include "r224_media_owner.h"
#include "r232_greeting_origin.h"
#include "r237_wake_window.h"
#include "mbedtls/base64.h"
#ifdef DF_H12_SD_ANIM
#include "h12_sd_motion.h"
static volatile unsigned h12_req_id=0;
volatile uint32_t h12_req_seq=0;
volatile uint32_t h12_done_seq=0;
static bool h12_use_sd=false;
#ifdef DF_H13_SD_UPLOAD
// R154: explicit SD upload gate. The animation task is the sole owner of
// the active SD reader; USB cannot mount/write until it acknowledges PAUSED.
static volatile bool r154_sd_upload_pause_requested=false;
static volatile bool r154_sd_upload_paused=false;
static uint32_t r229_usb_sd_lease=0;
#endif
static uint32_t h12_actual_seq=0;
static unsigned h12_actual_id=0;
static volatile uint32_t h12_rendered_seq=0;
static volatile unsigned h12_rendered_id=0;
#ifdef DF_H13_SD_UPLOAD
static volatile bool h13_boot_idle_pending=false;
#endif
#endif
#ifdef DF_H13_SD_UPLOAD
#include "h13_sd_usb.h"
#ifdef DF_R225_LOCAL_OFFLINE
#include "r224_sd_voice_player.h"
#ifdef DF_R185_WN9
#include "r259_offline_map.h"
#include "r259_offline_multinet.h"
#endif
#include "r225_voice_upload.h"
#include "r226_sd_wake_cache.h"
#endif
#endif
#ifdef DF_R185_WN9
#include "r185_wakenet9.h"
#endif
#ifdef DF_H11_PREVIEW_STATES
#include "h11_state_protocol.h"
static df_h11_state h11_current_state = {0,"idle"};
#endif
#define SPRITE_W 240
#define SPRITE_FRAME 240
#define RATE 24000
#define MAX_PEAK 30000
#define FIRST_VOL 86
#define MIC_RATE 16000
#define MIC_FRAMES 150
#ifdef DF_H28_HOLD_MIC
#define MIC_HOLD_MAX_FRAMES 1000 /* 20 seconds; 16kHz x 20ms */
#define MIC_HOLD_MIN_FRAMES 5    /* 100ms: discard incidental short taps */
static volatile bool h28_mic_button_pressed=false;
volatile bool h28_mic_press_session=false;
#ifdef DF_R185_WN9
static volatile bool r185_auto_capture=false;
static uint64_t r228_wake_boot_epoch=0; // reset-scoped correlation, not a secret
static uint32_t r228_wake_seq=0;
#endif
volatile bool h28_touch_requested=false;
static volatile bool r133_drag_requested=false;
static uint32_t r133_drag_count=0;
static volatile bool h28_touch_return_idle=false;
static uint32_t h28_last_idle_stage_tick=0;
static uint32_t h28_last_bonus_tick=0;
static uint32_t h28_tap_count=0;
volatile TickType_t h30_touch_requested_at=0;
static uint32_t h28_ordinary_count=0;
static uint32_t h28_bonus_count=0;
// A local-only gesture/idle first-frame receipt; never fake host DSH state.
static volatile unsigned h28_local_frame_id=0;
static volatile unsigned h28_local_frame_kind=0; /* 1 touch, 2 idle */
#endif
#define MIC_BLOCK 320
#define MIC_STACK_BYTES (14*1024)
#define COMMAND_STACK_BYTES (12*1024)
// R276: real 78-second ESP32 animation trace: 32KiB task had at least
// 20,444 bytes unused (peak stack <12.4KiB). Reserve 24KiB, preserving
// >11KiB headroom for animation's unusual SD/decode paths while returning
// 8KiB internal RAM for Wi-Fi+TLS. 8KiB did overflow on real hardware.
// Never move this flash/SD-reading worker stack to PSRAM (cache-off hazard).
#define ANIMATION_TASK_STACK_BYTES (24 * 1024)
#define VOICE_TASK_STACK_BYTES (12 * 1024)
_Static_assert(MAX_PEAK<32767 && FIRST_VOL<=100,"bounded audio");
extern const uint8_t anim_start[] asm("_binary_ANIM_DFS_start");
extern const uint8_t anim_end[] asm("_binary_ANIM_DFS_end");

#ifdef DF_R185_WN9
extern const uint8_t r185_greeting_start[] asm("_binary_R185_GREETING_WAV_start");
extern const uint8_t r185_greeting_end[] asm("_binary_R185_GREETING_WAV_end");
#endif
static const char *TAG="H10_REAL_AVATAR";
lv_obj_t *picture;
lv_obj_t *status_label;
static lv_image_dsc_t image_desc;
/* R70_PERFORMANCE_COUNTERS: read-only, collected in animation worker. */
static volatile uint32_t r70_frames=0,r70_decoding_errors=0;
static volatile uint32_t r70_frame_max_ms=0,r70_frame_last_ms=0;
static volatile uint32_t r70_frame_long=0,r70_gap_max_ms=0,r70_last_frame_tick=0;
static volatile uint32_t r70_opaque_last=0,r70_opaque_invalid=0;
// R510 bounded diagnostic averages. Only numeric drawing costs, no imagery.
static volatile uint32_t r510_stage_ready=0,r510_perf_frames=0;
static volatile uint32_t r510_avg_load_us=0,r510_avg_decode_us=0;
static volatile uint32_t r510_avg_lock_us=0,r510_avg_draw_us=0;
// R322: read-only animation liveness, safe over USB after battery-only freeze.
// 0=running, 1=SD voice lease, 2=SD transfer, 3=static test,
// 4=mic capture, 5=decoder failure, 6=LVGL lock timeout.
static volatile uint32_t r322_anim_heartbeat=0,r322_anim_last_tick=0;
static volatile uint32_t r322_anim_hold=0,r322_anim_failures=0;

/* R71_SCREEN_LAYER_PROBE */
static volatile uint32_t r71_drawn_frames=0,r71_offscreen=0;
static volatile uint32_t r71_hidden=0,r71_bad_descriptor=0,r71_overlay_conflict=0;
static volatile int32_t r71_x1=0,r71_y1=0,r71_x2=0,r71_y2=0;

/* R82: static screen/decoder isolation modes, no new frame buffers. */
static volatile unsigned r82_display_mode=0; /* 0 live, 1 quadrants, 2 one frame */
static unsigned r82_current_mode=0;
static lv_obj_t *r82_quad[4]={NULL,NULL,NULL,NULL};
static volatile uint32_t r82_static_enters=0,r82_mode_changes=0;
static uint8_t *raw_frame,*delta,*compressed,*frame_rgb;
esp_codec_dev_handle_t speaker;
bool speaking;
// R259: independent small speaking animation while the SD reader is paused.
static volatile bool r259_local_speaking_visual=false;
#ifdef DF_R225_LOCAL_OFFLINE
static volatile unsigned r225_requested_clip=0,r225_last_clip=0;
static volatile int r225_last_rc=-99;
// Read-only last SD attempt diagnostics; embedded fallback must not overwrite it.
static volatile int r228_sd_preload_rc=-99,r228_sd_stream_rc=-99;
static volatile unsigned r228_sd_stage=0; // 0 none,1 request,2 paused,3 read,4 played,5 fallback,6 busy,7 failed
#endif
volatile bool capturing;
// R268 transport is a *single* additional codec owner, never concurrent USB.
volatile bool r268_lan_busy=false;
static volatile bool r268_lan_touch_finish=false;
// R556: UI-only recording origin. Does not control actual mic/codec owner.
static volatile bool r268_lan_auto_wake=false;
#ifdef DF_R434_MAC_PREWAKE_ONLY
static volatile bool r434_prewake_active=false,r434_touch_pending=false;
static volatile bool r435_wave_cache_ready=false;
volatile bool r435_mouth_first_frame_ready=false;
// R436: cached R412 waveform should begin with the authentic local greeting,
// rather than waiting for full LAN microphone capture to be acknowledged.
// Only numeric flags cross tasks; no voice PCM, SD or UI object is shared.
static volatile bool r436_wake_ack_wave_active=false;
static volatile bool r436_wake_ack_first_frame_ready=false;
#endif
// R276: NVS/TLS pairing lookup must not run inside the LVGL tap callback.
// True only after verified boot-time NVS lookup or successful local USB pair.
// The WSS worker still validates the real credentials again before TLS.
static volatile bool r276_lan_paired_cached=false;
static volatile uint8_t r276_lan_start_error=0; // 1=busy,2=memory,3=task
volatile r268_lan_phase_t r268_current_phase=R268_LAN_IDLE;
// R279: LAN voice threads must NEVER wait on LVGL to report phases.
// Only the LVGL timer below touches status_label or draws the error.
static volatile r268_lan_phase_t r279_lan_ui_phase=R268_LAN_IDLE;
static volatile uint32_t r279_lan_ui_seq=0;
// UI-only latch for a user-initiated stop. WSS numeric reason stays intact.
static volatile bool r298_lan_cancelled=false;
// R441: local touch owns its display message for 1.5s even when a prior
// cancelled WSS turn left an old terminal error; numeric RTC evidence stays.
static TickType_t r441_touch_status_until=0;
// R303: independently recorded when authenticated WSS obtains DAC ownership.
// This is set only after speaker-open succeeds, not based on a guessed UI.
volatile bool r303_wss_audio_offered=false;
// Numeric only, carries no audio samples or character images.
#define R304_MOUTH_DIAG_MAGIC 0x304B7A15u
typedef struct {uint32_t magic,cycles;} r304_mouth_trace_t;
RTC_NOINIT_ATTR static volatile r304_mouth_trace_t r304_mouth_trace;
// Numeric-only, RTC-retained diagnostics. No image, PCM or private content.
#define R303_MOTION_MAGIC 0x52930317u
typedef struct {
 uint32_t magic, work_selected, work_failed, idle_restores;
} r303_work_trace_t;
RTC_NOINIT_ATTR static volatile r303_work_trace_t r303_trace;
// R332: authoritative *physical* LAN speaker->SD-motion reconciliation.
// Numeric-only persistent evidence; never stores audio, conversation or art.
#define R332_MOTION_MAGIC 0x52933242u
typedef struct {
 uint32_t magic, talk_starts, talk_attempts, talk_applied, talk_fail;
 uint32_t deferred_idle, mouth_render_frames, last_selected;
} r332_motion_trace_t;
RTC_NOINIT_ATTR static volatile r332_motion_trace_t r332_motion_trace;
static void r332_trace_init(void){
 if(r332_motion_trace.magic==R332_MOTION_MAGIC)return;
 r332_motion_trace.magic=R332_MOTION_MAGIC;
 r332_motion_trace.talk_starts=0;r332_motion_trace.talk_attempts=0;
 r332_motion_trace.talk_applied=0;r332_motion_trace.talk_fail=0;
 r332_motion_trace.deferred_idle=0;
 r332_motion_trace.mouth_render_frames=0;
 r332_motion_trace.last_selected=0;
}

// R281: tiny numeric RTC-only trace survives a USB reconnect/reset after the
// user tests battery WSS. Never contains PCM, transcriptions or credentials.
RTC_NOINIT_ATTR volatile r281_ui_audio_trace_t r281_trace;
// R296: distinct rendered content evidence (counts only, never pixels/audio).
#define R296_ANIM_TRACE_MAGIC 0x5296A11Au
typedef struct {
 uint32_t magic, frames, changed_frames, last_hash;
 uint32_t refr_ready, flush_wait_done;
} r296_anim_trace_t;
RTC_NOINIT_ATTR static volatile r296_anim_trace_t r296_trace;
static void r281_begin_trace(void){
 uint32_t sessions=r281_trace.magic==R281_DIAG_MAGIC?
                       r281_trace.sessions+1:1;
 r281_trace.magic=R281_DIAG_MAGIC;
 r281_trace.sessions=sessions;
 r281_trace.voice_phase_events=0;
 r281_trace.lvgl_ticks=0;
 r281_trace.status_commits=0;
 r281_trace.avatar_frames_during_wifi=0;
 r281_trace.speaker_blocks=0;
 r281_trace.slow_codec_blocks=0;
 r281_trace.max_codec_write_us=0;
 r281_trace.max_source_peak=0;
 r281_trace.clipped_source_samples=0;
 r296_trace.magic=R296_ANIM_TRACE_MAGIC;
 r296_trace.frames=0;
 r296_trace.changed_frames=0;
 r296_trace.last_hash=0;
 r296_trace.refr_ready=0;
 r296_trace.flush_wait_done=0;
}
// LVGL display events run in the LVGL worker; only numeric evidence.
static void r296_display_event_cb(lv_event_t *event){
 if(r296_trace.magic!=R296_ANIM_TRACE_MAGIC)return;
 const lv_event_code_t code=lv_event_get_code(event);
 if(code==LV_EVENT_REFR_READY)r296_trace.refr_ready++;
 else if(code==LV_EVENT_FLUSH_WAIT_FINISH)r296_trace.flush_wait_done++;
}
static volatile bool loopback_busy;
// USB Mac test must ACK readiness before any physical microphone stream.
static volatile bool mic_host_armed;
static volatile TickType_t mic_host_deadline;
// R232: Only a verified physical WakeNet event can authorize wake->Voice3.
// USB OFFLINE1 PLAY is an independent speaker test, never a wake origin.
static volatile bool r232_real_wake_greeting_pending=false;
// R302: visual-only wake greeting marker, never changes Voice3 audio owner.
static volatile bool r302_wake_greeting_visual=false;
#define HOST_ARM_TIMEOUT_MS (180 * 1000)
uint8_t volume=FIRST_VOL;
volatile bool h10_receiving;
static volatile bool r37_pcm2_active=false,r37_pcm2_abort=false;
static void h10_dynamic_cancel(void);
#ifdef DF_R33_BOARD_UI
// Device-side only, never inferred from a model reply. 480x480 AMOLED.
// The Mac owns histories, memories, agent tools and advanced settings.
// This tiny panel only exposes hardware-local settings and truthful ARM state.
static void ui_status(const char *s);
/* R251 RTC non-init, numeric-only wake crash evidence. No PCM/text.
 * The LAST active wake stage survives reset independently of USB logs.
 * An interrupted wake (100..899) is captured on first reboot only,
 * then preserved over a secondary USB reconnect/reset.
 */
typedef struct {
    uint32_t magic,last_step,crash_step,crash_reason,boots;
} r251_wake_trace_t;
RTC_NOINIT_ATTR static volatile r251_wake_trace_t r251_trace;
#define R251_WAKE_TRACE_MAGIC 0x2511ace9u
void r251_wake_mark(unsigned stage){
    if(r251_trace.magic!=R251_WAKE_TRACE_MAGIC)return;
    if(stage==101u){
        r251_trace.crash_step=0;r251_trace.crash_reason=0;
    }else if(stage<r251_trace.last_step){
        /* A concurrently scheduled greeting/voice worker may already be
         * farther ahead. Never rewind a crash breadcrumb. */
        return;
    }
    r251_trace.last_step=stage;
}
static void r251_boot_trace_start(void){
    uint32_t reset=(uint32_t)esp_reset_reason();
    if(r251_trace.magic!=R251_WAKE_TRACE_MAGIC){
        r251_trace.magic=R251_WAKE_TRACE_MAGIC;
        r251_trace.last_step=0;r251_trace.crash_step=0;
        r251_trace.crash_reason=0;r251_trace.boots=0;
    }else if(r251_trace.last_step>=100u &&
             r251_trace.last_step<900u && !r251_trace.crash_step){
        r251_trace.crash_step=r251_trace.last_step;
        r251_trace.crash_reason=reset;
    }
    r251_trace.last_step=0;
    r251_trace.boots++;
}

static lv_obj_t *r33_sheet=NULL;
lv_obj_t *r33_header=NULL;
lv_obj_t *r33_battery=NULL;
static lv_obj_t *r33_sheet_status=NULL;
// The original three-piece icon had alignment gaps; use one original
// transparent pictogram. No other R36 display objects are changed.
static lv_obj_t *r33_mic_button=NULL;
lv_obj_t *r33_mic_stop=NULL;
lv_obj_t *r46_mic_img=NULL;
static const lv_image_dsc_t r46_mic_dsc={
    .header={.magic=LV_IMAGE_HEADER_MAGIC,.cf=LV_COLOR_FORMAT_ARGB8888,
             .w=R42_MIC_W,.h=R42_MIC_W,.stride=R42_MIC_W*4},
    .data_size=sizeof(r42_mic_argb8888),.data=r42_mic_argb8888
};
static bool r33_is_status=false;
uint8_t r33_brightness=60;
static volatile TickType_t r33_error_since=0;
static i2c_master_dev_handle_t r34_pmu=NULL,r34_rtc=NULL;
static TickType_t r34_last_telemetry=0;
static bool r34_bat_present=false,r34_bat_valid=false,r34_rtc_valid=false;
// AXP2101 PMU: VBUS good=reg00 bit5; charge mode=reg01 bits2:0.
// Unknown/failed I2C must never be shown as active charging.
static bool r277_vbus_good=false,r277_charging_valid=false;
static bool r277_charging=false,r277_charge_done=false;
static unsigned r34_bat_percent=0,r34_hour=0,r34_minute=0;
static volatile bool r34_host_clock_valid=false;
static volatile unsigned r34_host_clock_minute=0;
static volatile TickType_t r34_host_clock_tick=0;
static volatile TickType_t r36_mac_seen_at=0;
// R268: a recent USB command cannot prove the Mac is still attached after
// moving to standalone 5V. IDF's SOF-based link monitor distinguishes a real
// USB host from a power bank; the long command freshness TTL remains intact.
bool r268_usb_host_alive(void){
    const TickType_t seen=r36_mac_seen_at;
    return usb_serial_jtag_is_connected() && seen!=0 &&
           (TickType_t)(xTaskGetTickCount()-seen)<pdMS_TO_TICKS(240000);
}
lv_obj_t *r36_mac_dot=NULL;
lv_obj_t *r36_clock_label=NULL;
lv_obj_t *r36_battery_shell=NULL;
static lv_obj_t *r36_battery_fill=NULL;
static lv_obj_t *r277_power_icon=NULL;
lv_obj_t *r36_brightness_slider=NULL;
lv_obj_t *r36_volume_slider=NULL;
lv_obj_t *r36_brightness_pct=NULL;
lv_obj_t *r36_volume_pct=NULL;
static bool r50_trace_open=false;
static volatile bool r51_stop_requested=false;
static bool r51_last_stopped=false;
static bool r50_dsh_seen=false;
static unsigned r50_progress=0;
static char r50_link_phase[25]="idle";
static char r50_link_error[20]="none";
static unsigned r36_real_turns=0;
bool r36_last_turn_ok=false;
static uint32_t r36_record_begin_tick=0;

// Two independent read-only devices share the board's existing BSP I2C bus;
// never deinit or reset that bus (touch and codecs already own it).
static void r34_init_telemetry(void){
    i2c_master_bus_handle_t bus=bsp_i2c_get_handle();
    if(!bus)return;
    i2c_device_config_t cfg={.dev_addr_length=I2C_ADDR_BIT_LEN_7,
                             .scl_speed_hz=100000,.device_address=0x34};
    if(i2c_master_bus_add_device(bus,&cfg,&r34_pmu)!=ESP_OK)r34_pmu=NULL;
    cfg.device_address=0x51;
    if(i2c_master_bus_add_device(bus,&cfg,&r34_rtc)!=ESP_OK)r34_rtc=NULL;
}
static bool r34_read(i2c_master_dev_handle_t dev,uint8_t reg,uint8_t *dst,size_t len){
    return dev && i2c_master_transmit_receive(dev,&reg,1,dst,len,75)==ESP_OK;
}
static bool r34_bcd(uint8_t v,unsigned limit,unsigned *value){
    unsigned a=(v>>4)*10u+(v&15u);
    if((v>>4)>9||(v&15)>9||a>limit)return false;
    *value=a;return true;
}
static void r34_telemetry(void){
    uint8_t pm=0,charge=0,percent=0,rtc[7]={0};
    r34_bat_valid=false;r34_bat_present=false;r34_rtc_valid=false;
    r277_vbus_good=false;r277_charging_valid=false;
    r277_charging=false;r277_charge_done=false;
    if(r34_read(r34_pmu,0x00,&pm,1)){
        r277_vbus_good=(pm&0x20)!=0;
        r34_bat_present=(pm&0x08)!=0;
        if(r34_read(r34_pmu,0x01,&charge,1)){
            const uint8_t mode=charge&0x07;
            const uint8_t direction=(charge>>5)&0x03;
            r277_charging_valid=true;
            r277_charging=r34_bat_present && r277_vbus_good &&
                (mode<=3u || direction==1u);
            r277_charge_done=r34_bat_present && r277_vbus_good && mode==4u;
        }
        if(r34_bat_present && r34_read(r34_pmu,0xA4,&percent,1) && percent<=100){
            r34_bat_valid=true;r34_bat_percent=percent;
        }
    }
    // PCF85063 seconds..year BCD. Oscillator-stop bit means time invalid.
    if(r34_read(r34_rtc,0x04,rtc,sizeof(rtc)) && !(rtc[0]&0x80)){
        unsigned sec=0,minute=0,hour=0,day=0,month=0,year=0;
        if(r34_bcd(rtc[0]&0x7F,59,&sec) && r34_bcd(rtc[1]&0x7F,59,&minute) &&
           r34_bcd(rtc[2]&0x3F,23,&hour) && r34_bcd(rtc[3]&0x3F,31,&day) &&
           r34_bcd(rtc[5]&0x1F,12,&month) && r34_bcd(rtc[6],99,&year) &&
           day>=1 && month>=1 && year>=26 && year<=80){
            r34_hour=hour;r34_minute=minute;r34_rtc_valid=true;
        }
    }
}
// R61: the board has a PCF85063ATL (0x51) local RTC. A validated and
// acknowledged Mac clock sync seeds it; thereafter the RTC keeps time
// independently of Mac, DSH, microphone ARM and USB link state.
// The 7 time registers start at 0x04, BCD seconds..year; do not modify the
// shared I2C bus, PMU, RTC control, alarms or battery settings.
static uint8_t r61_to_bcd(unsigned n){return (uint8_t)(((n/10u)<<4)|(n%10u));}
static bool r61_valid_date(unsigned y,unsigned m,unsigned d){
    if(y<26||y>80||m<1||m>12||d<1)return false;
    static const uint8_t days[]={0,31,28,31,30,31,30,31,31,30,31,30,31};
    unsigned max=days[m];
    if(m==2 && (y%4u)==0)max=29;
    return d<=max;
}
static bool r61_rtc_set_checked(unsigned y,unsigned mo,unsigned d,
                               unsigned h,unsigned mi,unsigned sec,unsigned weekday){
    if(!r61_valid_date(y,mo,d)||h>=24||mi>=60||sec>=60||weekday>=7||!r34_rtc)
        return false;
    uint8_t packet[]={0x04,r61_to_bcd(sec),r61_to_bcd(mi),
       r61_to_bcd(h),r61_to_bcd(d),r61_to_bcd(weekday),
       r61_to_bcd(mo),r61_to_bcd(y)};
    if(i2c_master_transmit(r34_rtc,packet,sizeof(packet),100)!=ESP_OK)
        return false;
    // Require an actual valid readback; never claim RTC persistence from
    // a successful I2C transmit alone. A rollover within one minute is OK.
    uint8_t check[7]={0};
    if(!r34_read(r34_rtc,0x04,check,sizeof(check))||(check[0]&0x80))
        return false;
    unsigned got_h=99,got_m=99,got_y=99,got_mo=99,got_d=99;
    if(!r34_bcd(check[2]&0x3F,23,&got_h)||
       !r34_bcd(check[1]&0x7F,59,&got_m)||
       !r34_bcd(check[6],99,&got_y)||
       !r34_bcd(check[5]&0x1F,12,&got_mo)||
       !r34_bcd(check[3]&0x3F,31,&got_d))return false;
    bool ok=got_h==h && got_m==mi && got_y==y && got_mo==mo && got_d==d;
    if(ok){r34_hour=got_h;r34_minute=got_m;r34_rtc_valid=true;}
    return ok;
}
static void r33_update_status(lv_timer_t *timer){
    (void)timer;
    TickType_t now=xTaskGetTickCount();
    // Physically unplugging USB instantly revokes the stale host ARM.
    bool usb_link=usb_serial_jtag_is_connected();
    if(!usb_link)mic_host_armed=false;
    bool armed=usb_link && mic_host_armed && (int32_t)(mic_host_deadline-now)>0;
    bool mac_online=r268_usb_host_alive();
    // "Mac voice link" and microphone hardware are different facts.
    // A plugged-in USB power cable alone is not an active DSH voice session.
    // R298: the header is exclusively connectivity; never a second
    // wireless voice progress bar. Voice stages stay in the bottom label.
    r62_wifi_state_t wifi={0};
    r62_wifi_snapshot(&wifi);
    const char *service=NULL;
    if(usb_link){
        service=mac_online?"Mac语音已连接":"USB 已连接";
    }else{
        service=wifi.has_ip?"Wi-Fi 已连接":"Wi-Fi 未连接";
    }
    if(r33_header && strcmp(lv_label_get_text(r33_header),service)!=0)
        lv_label_set_text(r33_header,service);
    if(r36_mac_dot){
        static int r280_old_link=-1;
        const int linked=usb_link?(mac_online?1:0):(wifi.has_ip?1:0);
        if(r280_old_link!=linked){
            lv_obj_set_style_bg_color(r36_mac_dot,
                lv_color_hex(linked?0x46AF91:0xB2BDC8),0);
            r280_old_link=linked;
        }
    }
    if(r33_mic_button){
        static int previous=-1;
        int current=capturing?1:0;
        if(previous!=current){
            previous=current;
            lv_obj_set_style_bg_color(r33_mic_button,
                current?lv_color_hex(0xD6F4EA):lv_color_hex(0xE8F2FF),0);
            lv_obj_set_style_border_color(r33_mic_button,
                current?lv_color_hex(0x7DC9B1):lv_color_hex(0xBCD9FD),0);
            if(r33_mic_stop)lv_obj_add_flag(r33_mic_stop,LV_OBJ_FLAG_HIDDEN);
            if(r46_mic_img){
                if(current)lv_obj_add_flag(r46_mic_img,LV_OBJ_FLAG_HIDDEN);
                else lv_obj_remove_flag(r46_mic_img,LV_OBJ_FLAG_HIDDEN);
            }
            ESP_LOGI(TAG,"R61_MIC_STATE_CHANGED recording=%d",current);
        }
    }
    if(r34_last_telemetry==0 || now-r34_last_telemetry>=pdMS_TO_TICKS(10000)){
        r34_last_telemetry=now;
        r34_telemetry();
    }
    // The original USB timer must not overwrite a WSS "无线录音中" label.
    if(capturing && r36_record_begin_tick && status_label && !r268_lan_busy){
        unsigned seconds=(unsigned)((now-r36_record_begin_tick)/pdMS_TO_TICKS(1000));
        lv_label_set_text_fmt(status_label,"录音中 %us / 20s · 再点结束",seconds);
    }
    if(r33_battery){
        char line[42],time_label[7]="--:--";
        if(r34_rtc_valid){
            snprintf(time_label,sizeof(time_label),"%02u:%02u",r34_hour,r34_minute);
        }else if(r34_host_clock_valid){
            unsigned min=(r34_host_clock_minute+
                         (unsigned)((now-r34_host_clock_tick)/pdMS_TO_TICKS(60000)))%(24*60);
            snprintf(time_label,sizeof(time_label),"%02u:%02u",min/60,min%60);
        }
        if(r36_clock_label && strcmp(lv_label_get_text(r36_clock_label),time_label))
            lv_label_set_text(r36_clock_label,time_label);
        if(r34_bat_valid)snprintf(line,sizeof(line),"%u%%",r34_bat_percent);
        else snprintf(line,sizeof(line),"--");
        if(strcmp(lv_label_get_text(r33_battery),line))
            lv_label_set_text(r33_battery,line);
        if(r36_battery_fill){
            const unsigned fill=r34_bat_valid?(r34_bat_percent*22u)/100u:0u;
            if((unsigned)lv_obj_get_width(r36_battery_fill)!=fill)
                lv_obj_set_width(r36_battery_fill,fill);
        }
        if(r277_power_icon){
            const bool external=r277_vbus_good && r277_charging_valid && r34_bat_present;
            const char *symbol=r277_charging?LV_SYMBOL_CHARGE:LV_SYMBOL_USB;
            if(external){
                if(strcmp(lv_label_get_text(r277_power_icon),symbol))
                    lv_label_set_text(r277_power_icon,symbol);
                if(lv_obj_has_flag(r277_power_icon,LV_OBJ_FLAG_HIDDEN))
                    lv_obj_remove_flag(r277_power_icon,LV_OBJ_FLAG_HIDDEN);
            }else if(!lv_obj_has_flag(r277_power_icon,LV_OBJ_FLAG_HIDDEN))
                lv_obj_add_flag(r277_power_icon,LV_OBJ_FLAG_HIDDEN);
        }
    }
    if(r50_trace_open && r33_sheet_status && !r268_lan_busy){
        const char *mac=r268_usb_host_alive()?"ONLINE":"离线";
        const char *mic=r50_progress>=2?"sent":capturing?"recording":"waiting";
        const char *stt=r50_progress>=3?"done":r50_progress==2?"running":"waiting";
        bool dsh_failed=r36_real_turns && !r36_last_turn_ok &&
            !r51_last_stopped && strcmp(r50_link_error,"DSH")==0;
        const char *dsh=dsh_failed?"FAILED":
            !r50_dsh_seen?(r50_progress>=4?"local reply":"not called"):
            r50_progress>=4?"answered":"working";
        const char *tts=dsh_failed?"skipped":r50_progress>=5?"streaming":r50_progress==4?"preparing":"waiting";
        const char *speaker=dsh_failed?"not played":r50_progress>=6?"completed":r50_progress==5?"started":"waiting";
        lv_label_set_text_fmt(r33_sheet_status,
          "Mac USB: %s\nMic -> Mac: %s\nLocal STT: %s\nDSH: %s\nQwen TTS: %s\nSpeaker: %s\nLast: %s (%s)",
          mac,mic,stt,dsh,tts,speaker,
          r36_real_turns?(r51_last_stopped?"STOPPED":r36_last_turn_ok?"OK":"FAILED"):"none",r50_link_error);
    }
    if(r33_is_status && r33_sheet_status && !r268_lan_busy){
        lv_label_set_text_fmt(r33_sheet_status,
          "Mac voice ARM: %s\nAudio: %s\nRTC: %s / Battery: %s\nUptime: %lu s",
          armed?"READY":"WAIT",capturing?"RECORDING":(speaking?"PLAYING":"IDLE"),
          r34_rtc_valid?"read":"unverified",r34_bat_valid?"read":"unverified",
          (unsigned long)(now*portTICK_PERIOD_MS/1000u));
    }
}
// R279 UI-owner handoff: only called from LVGL's task, never the WSS worker.
// An error is held after LAN worker returns (rather than flashing for <130ms).
static void r279_lan_ui_tick(lv_timer_t *timer){
    (void)timer;
    static uint32_t seen=0;
    const uint32_t seq=r279_lan_ui_seq;
    if(r268_lan_busy && r281_trace.magic==R281_DIAG_MAGIC)
        r281_trace.lvgl_ticks++;
    if(!status_label)return;
    // R441: a fresh local tap must not flash the old WSS "stop playback".
    // When this finite local lease ends, show idle rather than replaying
    // an obsolete error. A genuinely new WSS phase gets its own new seq.
    if(r441_touch_status_until){
        const TickType_t now=xTaskGetTickCount();
        if((int32_t)(now-r441_touch_status_until)<0){
            if(strcmp(lv_label_get_text(status_label),"正在播放互动动作"))
                lv_label_set_text(status_label,"正在播放互动动作");
            return;
        }
        r441_touch_status_until=0;
        if(!r268_lan_busy){
            if(strcmp(lv_label_get_text(status_label),"待机 · 点击互动"))
                lv_label_set_text(status_label,"待机 · 点击互动");
            seen=seq;return;
        }
    }
    // Previous implementation only refreshed when seq changed. If an old
    // USB/status callback overwrote the label mid-turn, it stayed stale until
    // the next phase. Reconcile the *actual* label on each tick while LAN
    // voice is active; after completion update once only.
    if(seq==seen && !r268_lan_busy)return;
    const r268_lan_phase_t phase=r279_lan_ui_phase;
    const char *text=NULL;
    char failure[70]={0};
    switch(phase){
        case R268_LAN_IDLE:text="待机 · 点击互动";break;
        case R268_LAN_CONNECTING:text="正在连接无线大肥鱼";break;
        case R268_LAN_LISTENING:text=r268_lan_auto_wake?
            "正在听你说话 · 无话会自动结束":"无线录音中 · 再点发送";break;
        case R268_LAN_THINKING:text="官方 DSH 正在回答";break;
        case R268_LAN_SPEAKING:text="大肥鱼无线语音播放中";break;
        case R268_LAN_FINISHED:text="无线对话完成";break;
        case R268_LAN_ERROR:{
            r277_lan_diag_t diag={0};
            if(r277_lan_diag_snapshot(&diag) && diag.failed_stage){
                snprintf(failure,sizeof(failure),"WSS stage %lu reason %lu",
                    (unsigned long)diag.failed_stage,(unsigned long)diag.exit_reason);
                text=r298_lan_cancelled?"已停止播音":failure;
            }else text=r298_lan_cancelled?"已停止播音":"无线链路失败 · 本地仍可用";
            break;
        }
        default:break;
    }
    if(text && strcmp(lv_label_get_text(status_label),text)){
        lv_label_set_text(status_label,text);
        if(r281_trace.magic==R281_DIAG_MAGIC && r268_lan_busy)
            r281_trace.status_commits++;
    }
    seen=seq;
}
static void r33_close(lv_event_t *event){
    (void)event;
    if(r33_sheet){lv_obj_delete_async(r33_sheet);r33_sheet=NULL;r33_sheet_status=NULL;
        r36_brightness_slider=NULL;r36_volume_slider=NULL;
        r36_brightness_pct=NULL;r36_volume_pct=NULL;r33_is_status=false;r50_trace_open=false;}
}
static lv_obj_t *r33_label(lv_obj_t *parent,const char *value,int y){
    lv_obj_t *label=lv_label_create(parent);
    lv_label_set_text(label,value);
    lv_obj_set_style_text_color(label,lv_color_hex(0x24465E),0);
    lv_obj_set_style_text_font(label,&lv_font_montserrat_16,0);
    lv_obj_align(label,LV_ALIGN_TOP_LEFT,16,y);
    return label;
}
static lv_obj_t *r33_panel_button(lv_obj_t *parent,const char *txt,int x,int y,
                                  int w,lv_event_cb_t cb){
    lv_obj_t *b=lv_button_create(parent);
    lv_obj_set_size(b,w,46);
    lv_obj_align(b,LV_ALIGN_TOP_LEFT,x,y);
    lv_obj_set_style_bg_color(b,lv_color_hex(0xE1F2F9),0);
    lv_obj_set_style_radius(b,12,0);
    lv_obj_add_event_cb(b,cb,LV_EVENT_CLICKED,NULL);
    lv_obj_t *t=lv_label_create(b);
    lv_label_set_text(t,txt);
    lv_obj_set_style_text_color(t,lv_color_hex(0x225C79),0);
    lv_obj_center(t);
    return b;
}
static void r33_brighter(lv_event_t *event){
    (void)event;
    if(capturing||speaking||h10_receiving)return;
    uint8_t next=r33_brightness>=90?30:r33_brightness+30;
    if(bsp_display_brightness_set(next)==ESP_OK){
        r33_brightness=next;
        lv_label_set_text(status_label,"亮度调整成功");
        if(r33_sheet_status)lv_label_set_text_fmt(r33_sheet_status,
            "Display brightness: %u%%\nHardware applied",r33_brightness);
    }else lv_label_set_text(status_label,"亮度调整失败");
}
static void r33_volume_step(lv_event_t *event){
    (void)event;
    if(capturing||speaking||h10_receiving)return;
    uint8_t next=volume>=90?50:(volume==50?70:90);
    volume=next; // the codec picks this up at the next verified playback open
    lv_label_set_text(status_label,"已设置下次播放音量");
    if(r33_sheet_status)lv_label_set_text_fmt(r33_sheet_status,
       "Speaker volume: %u%%\nNext codec playback uses this level",volume);
}
static void r33_open_settings(lv_event_t *event);
static void r33_open_status(lv_event_t *event);
static void r33_base_panel(const char *heading){
    if(r33_sheet)r33_close(NULL);
    r33_sheet=lv_obj_create(lv_screen_active());
    lv_obj_set_size(r33_sheet,410,308);
    lv_obj_center(r33_sheet);
    lv_obj_set_style_bg_color(r33_sheet,lv_color_hex(0xFFFFFF),0);
    lv_obj_set_style_bg_opa(r33_sheet,LV_OPA_COVER,0);
    lv_obj_set_style_radius(r33_sheet,22,0);
    lv_obj_set_style_shadow_width(r33_sheet,10,0);
    lv_obj_set_style_pad_all(r33_sheet,0,0);
    lv_obj_remove_flag(r33_sheet,LV_OBJ_FLAG_SCROLLABLE);
    r33_label(r33_sheet,heading,18);
    r33_panel_button(r33_sheet,"X",344,10,48,r33_close);
}
void r36_brightness_changed(lv_event_t *event){
    (void)event;
    if(capturing||speaking||h10_receiving)return;
    int requested=lv_slider_get_value(r36_brightness_slider);
    if(requested<10)requested=10;
    if(requested>100)requested=100;
    if(bsp_display_brightness_set(requested)==ESP_OK){
        r33_brightness=(uint8_t)requested;
        if(r36_brightness_pct)lv_label_set_text_fmt(r36_brightness_pct,"%u%%",r33_brightness);
    }else if(r36_brightness_slider){
        // A failed BSP set must not leave the slider at a false brightness.
        // LV_ANIM_OFF does not emit another value-changed event.
        lv_slider_set_value(r36_brightness_slider,r33_brightness,LV_ANIM_OFF);
    }
}
void r36_volume_changed(lv_event_t *event){
    (void)event;
    if(capturing||speaking||h10_receiving)return;
    int requested=lv_slider_get_value(r36_volume_slider);
    if(requested<20)requested=20;
    if(requested>95)requested=95;
    volume=(uint8_t)requested;
    if(r36_volume_pct)lv_label_set_text_fmt(r36_volume_pct,"%u%%",volume);
}
static void r33_open_settings(lv_event_t *event){
    (void)event;
    r33_base_panel("DEVICE SETTINGS");
    r33_is_status=false;
    r33_label(r33_sheet,"Display brightness",65);
    r36_brightness_pct=r33_label(r33_sheet,"60%",65);
    lv_obj_align(r36_brightness_pct,LV_ALIGN_TOP_RIGHT,-19,65);
    lv_label_set_text_fmt(r36_brightness_pct,"%u%%",r33_brightness);
    r36_brightness_slider=lv_slider_create(r33_sheet);
    lv_obj_set_size(r36_brightness_slider,340,16);
    lv_obj_align(r36_brightness_slider,LV_ALIGN_TOP_LEFT,31,110);
    lv_slider_set_range(r36_brightness_slider,10,100);
    lv_slider_set_value(r36_brightness_slider,r33_brightness,LV_ANIM_OFF);
    lv_obj_add_event_cb(r36_brightness_slider,r36_brightness_changed,LV_EVENT_VALUE_CHANGED,NULL);
    r33_label(r33_sheet,"Speaker volume (next reply)",155);
    r36_volume_pct=r33_label(r33_sheet,"88%",155);
    lv_obj_align(r36_volume_pct,LV_ALIGN_TOP_RIGHT,-19,155);
    lv_label_set_text_fmt(r36_volume_pct,"%u%%",volume);
    r36_volume_slider=lv_slider_create(r33_sheet);
    lv_obj_set_size(r36_volume_slider,340,16);
    lv_obj_align(r36_volume_slider,LV_ALIGN_TOP_LEFT,31,205);
    lv_slider_set_range(r36_volume_slider,20,95);
    lv_slider_set_value(r36_volume_slider,volume,LV_ANIM_OFF);
    lv_obj_add_event_cb(r36_volume_slider,r36_volume_changed,LV_EVENT_VALUE_CHANGED,NULL);
    r33_sheet_status=r33_label(r33_sheet,"Local controls only  /  2-tap voice",253);
}
static void r33_open_status(lv_event_t *event){
    (void)event;
    r33_base_panel("DEVICE STATUS");
    r33_is_status=true;
    r33_sheet_status=r33_label(r33_sheet,"Reading actual device state...",72);
    r33_update_status(NULL);
}
void r51_stop_audio(lv_event_t *event){
    (void)event;
    // STOP stays explicit during THINKING/SPEAKING; repeated MIC taps are
    // ignored instead, so touch lag cannot silently cancel D10 synthesis.
    if(r268_lan_busy && r268_current_phase!=R268_LAN_LISTENING){
        r51_stop_requested=true;
        lv_label_set_text(status_label,"正在停止无线语音");return;
    }
    if(r37_pcm2_active){r51_stop_requested=true;r37_pcm2_abort=true;
        lv_label_set_text(status_label,"正在停止语音");return;}
    if(h10_receiving){
        h10_dynamic_cancel();
        static const char stopped[]="@@DFPCM1 USER_STOPPED\n";
        (void)h9_send_line(stopped,sizeof(stopped)-1);
        lv_label_set_text(status_label,"语音传输已停止");return;
    }
    if(speaking){r51_stop_requested=true;
        lv_label_set_text(status_label,"正在停止语音");return;}
    lv_label_set_text(status_label,"当前没有语音播放");
}
static void r36_open_last_turn(lv_event_t *event){
    (void)event;
    r33_base_panel("VOICE LINK TRACE");
    r33_is_status=false;
    r50_trace_open=true;
    r33_sheet_status=r33_label(r33_sheet,"Reading verified stages...",55);
    lv_obj_set_width(r33_sheet_status,376);
    r33_panel_button(r33_sheet,"SETTINGS",20,247,118,r33_open_settings);
    r33_update_status(NULL);
}

static void r36_select_reaction(lv_event_t *event){
    uintptr_t id=(uintptr_t)lv_event_get_user_data(event);
    if(capturing||speaking||h10_receiving)return;
    // Bounded local action only. This cannot be mistaken for DSH work.
    if(id<4){
        h28_tap_count=(uint32_t)id;
        h28_touch_requested=true;
        r33_close(NULL);
    }
}
static void r36_open_reactions(lv_event_t *event){
    (void)event;
    r33_base_panel("LOCAL REACTIONS");
    r33_is_status=false;
    static const char *names[]={"Hello","Happy","Shy","Surprised"};
    for(unsigned i=0;i<4;i++){
        lv_obj_t *b=r33_panel_button(r33_sheet,names[i],20,58+(int)i*59,360,
                                    r36_select_reaction);
        lv_obj_remove_event_cb_with_user_data(b,r36_select_reaction,NULL);
        lv_obj_add_event_cb(b,r36_select_reaction,LV_EVENT_CLICKED,(void*)(uintptr_t)i);
    }
}
static void r33_local_reaction(lv_event_t *event){
    (void)event;
    if(capturing||speaking||h10_receiving||h28_mic_press_session)return;
    h28_touch_requested=true;
    h30_touch_requested_at=xTaskGetTickCount();
    lv_label_set_text(status_label,"已选择互动动作");
}
static void r33_rail_button(lv_obj_t *screen,int y,const char *symbol,lv_event_cb_t callback){
    lv_obj_t *b=lv_button_create(screen);
    lv_obj_set_size(b,58,58);
    lv_obj_align(b,LV_ALIGN_TOP_RIGHT,-16,y);
    lv_obj_set_style_radius(b,16,0);
    lv_obj_set_style_bg_color(b,lv_color_hex(0xFFFFFF),0);
    lv_obj_set_style_border_color(b,lv_color_hex(0xC9E3EF),0);
    lv_obj_set_style_border_width(b,1,0);
    lv_obj_set_style_shadow_width(b,0,0);
    lv_obj_add_event_cb(b,callback,LV_EVENT_CLICKED,NULL);
    lv_obj_t *t=lv_label_create(b);
    lv_label_set_text(t,symbol);
    lv_obj_set_style_text_color(t,lv_color_hex(0x437C9B),0);
    lv_obj_set_style_text_font(t,&lv_font_montserrat_20,0);
    lv_obj_center(t);
}
#if defined(DF_R225_LOCAL_OFFLINE) && defined(DF_R185_WN9)
bool r257_local_voice_from_touch(unsigned clip);
#endif
#endif

// H10 full-reply stream is buffered in PSRAM for uninterrupted ES8311
// playback. The USB host sends 960-sample (40ms) blocks with per-block ACK;
 // no PCM is stored to flash, SD or the model's conversation log.
#define H10_MAX_REPLY_SAMPLES (RATE * 12u)
#define H10_CHUNK_SAMPLES 960u
#define H10_CHUNK_BYTES (H10_CHUNK_SAMPLES * 2u)
#ifdef DF_H13_SD_UPLOAD
#define H10_COMMAND_LIMIT 14000u  // 8192 bytes encoded as B64, fixed selected IDs only
#else
#define H10_COMMAND_LIMIT 2800u
#endif
static int16_t *h10_dynamic_pcm;
static uint32_t h10_expected;
static uint32_t h10_received;
static uint32_t h10_seq;
static TickType_t h10_rx_deadline;
// PCM2: only newly added capability over user-verified R46-A; R36 UI
// untouched. Bounded 3-second PSRAM ring and 0.7 s prebuffer. Begin
// blocked when free PSRAM is insufficient to preserve LCD and sprite.
// 40ms framed producer ACK only after exact bytes accepted, no SD writes.
// Playback starts while chunks are still arriving; END only after LAST PCM.
#ifdef DF_R46_PCM2_ONLY
// PCM2 producer worker precedes the legacy USB helper definition.
#define R37_RING_BYTES (24000u*2u*5u) // R150: 5s ring; +96KiB PSRAM for long TTS gaps
#define R37_PACKET_BYTES (960u*2u)
static StaticStreamBuffer_t r37_stream_ctl;
static uint8_t *r37_stream_bytes=NULL;
static StreamBufferHandle_t r37_stream=NULL;
static volatile bool r37_pcm2_end=false;
static volatile bool r37_pcm2_worker_running=false,r37_pcm2_play_begin=false;
static unsigned r37_pcm2_seq=0;
static uint32_t r37_pcm2_bytes=0,r37_pcm2_underruns=0;
#define R50_PCM2_RX_TIMEOUT_MS 14000u
static volatile TickType_t r50_last_pcm2_rx=0;
static bool r50_pcm2_source_timed_out(void){
    return !r37_pcm2_end &&
      ((uint32_t)(xTaskGetTickCount()-r50_last_pcm2_rx)>=pdMS_TO_TICKS(R50_PCM2_RX_TIMEOUT_MS));
}
#ifdef DF_R47_PCM2_DIAGNOSTIC
// Only physical PCM2 transitions are eligible. The actual SD renderer owns
// sprite changes (never issue USB motion requests mid-audio).
volatile uint8_t r47_audio_motion=0; // 1 priming m024, 2 audible m030, 3 return m000
volatile uint32_t r47_motion_epoch=0;
static uint32_t r47_short_waits=0,r47_max_wait_ms=0,r47_low_queue=0;
#endif
static void r37_pcm2_worker(void *arg){
    (void)arg;
    r37_pcm2_worker_running=true;
    bool opened=false,played=false,failed=false;
    uint32_t pcm2_lease=0;
    if(!r224_audio_claim(R224_MEDIA_PCM2,&pcm2_lease)){
        failed=true;goto end;
    }
    if(!speaker)speaker=bsp_audio_codec_speaker_init();
    if(!speaker){failed=true;goto end;}
    esp_codec_dev_sample_info_t info={.sample_rate=RATE,.channel=1,.bits_per_sample=16};
    if(esp_codec_dev_open(speaker,&info)!=ESP_CODEC_DEV_OK){failed=true;goto end;}
    opened=true;
    if(esp_codec_dev_set_out_vol(speaker,volume)!=ESP_CODEC_DEV_OK){failed=true;goto end;}
    int16_t samples[480]; // 20ms 24kHz mono, aligned 16-bit PCM.
    uint8_t *bytes=(uint8_t *)samples;
    // Qwen generation is only ~1.01x real time. A larger initial cushion
    // prevents short mid-sentence I2S starvation from USB/SD scheduling.
    while(!r37_pcm2_abort && !r37_pcm2_end &&
          xStreamBufferBytesAvailable(r37_stream)<24000u*2u*2u){
        if(r50_pcm2_source_timed_out()){
            ESP_LOGE(TAG,"R50_PCM2_SOURCE_TIMEOUT stage=prebuffer");
            failed=true;r37_pcm2_abort=true;goto end;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    while(!r37_pcm2_abort){
        if(r50_pcm2_source_timed_out()){
            ESP_LOGE(TAG,"R50_PCM2_SOURCE_TIMEOUT stage=playback");
            failed=true;r37_pcm2_abort=true;break;
        }
        size_t got=0;
#ifdef DF_R47_PCM2_DIAGNOSTIC
        if(played && !r37_pcm2_end &&
           xStreamBufferBytesAvailable(r37_stream)<24000u*2u/10u)r47_low_queue++;
#endif
        while(got<sizeof(samples) && !r37_pcm2_abort){
            if(r50_pcm2_source_timed_out()){
                ESP_LOGE(TAG,"R50_PCM2_SOURCE_TIMEOUT stage=read");
                failed=true;r37_pcm2_abort=true;break;
            }
#ifdef DF_R47_PCM2_DIAGNOSTIC
            TickType_t wait_start=xTaskGetTickCount();
#endif
            size_t n=xStreamBufferReceive(r37_stream,bytes+got,sizeof(samples)-got,
                                           pdMS_TO_TICKS(150));
#ifdef DF_R47_PCM2_DIAGNOSTIC
            uint32_t waited=(uint32_t)((xTaskGetTickCount()-wait_start)*portTICK_PERIOD_MS);
            // An empty receive *after END* waits 150ms by design; never
            // mistake terminal ring drain for an audible mid-speech gap.
            if(played && waited>=10u &&
               (n>0 || !r37_pcm2_end)){
                r47_short_waits++;
                if(waited>r47_max_wait_ms)r47_max_wait_ms=waited;
            }
#endif
            got+=n;
            if(n==0){
                if(r37_pcm2_end && xStreamBufferBytesAvailable(r37_stream)==0)break;
                // True underrun: do not synthesize words or imply sound was played.
                if(played)r37_pcm2_underruns++;
            }
        }
        if(r37_pcm2_abort)break;
        if(got==0 && r37_pcm2_end)break;
        if(got!=sizeof(samples)){
            if(r37_pcm2_end){failed=true;break;}
            continue;
        }
#ifdef DF_R47_PCM2_DIAGNOSTIC
        // -2.5dB constant digital headroom keeps short high peaks out of the
        // tiny ES8311 speaker's nonlinear range; volume slider still controls
        // the actual codec volume. No extra TTS requests or altered text.
        for(unsigned i=0;i<480;i++)
            samples[i]=(int16_t)(((int32_t)samples[i]*3)/4);
#endif
        // R140: only real codec entry/exit receive an 8ms PCM taper.
        // Never fade at intermediate Qwen segmentation boundaries.
        const bool r140_last=(r37_pcm2_end &&
             xStreamBufferBytesAvailable(r37_stream)==0);
        r140_apply_pcm_edges(samples,480,!played,r140_last);
        if(!played)ESP_LOGI(TAG,"R140_PCM_BEGIN_EDGE fade_ms=8");
        if(r140_last)ESP_LOGI(TAG,"R140_PCM_END_EDGE fade_ms=8");
        if(esp_codec_dev_write(speaker,bytes,sizeof(samples))!=ESP_CODEC_DEV_OK){
            failed=true;break;
        }
        if(!played){
            played=true;r37_pcm2_play_begin=true;
#ifdef DF_R47_PCM2_DIAGNOSTIC
            r47_audio_motion=2;r47_motion_epoch++;
#endif
            ESP_LOGI(TAG,"R37_PCM2_CODEC_PLAY_BEGIN");
            static const char begin[]="@@DFPCM2 STARTED\n";
            (void)h9_send_line(begin,sizeof(begin)-1);
        }
    }
end:
    if(opened)esp_codec_dev_close(speaker);
    if(pcm2_lease)r224_audio_release(R224_MEDIA_PCM2,pcm2_lease);
    if(played && !failed && !r37_pcm2_abort){
        ESP_LOGI(TAG,"R37_PCM2_PLAY_DONE pcm_bytes=%lu underrun_count=%lu",
                 (unsigned long)r37_pcm2_bytes,(unsigned long)r37_pcm2_underruns);
        char receipt[94];
        int n=snprintf(receipt,sizeof(receipt),
            "@@DFPCM2 PLAYED underruns=%lu bytes=%lu\n",
            (unsigned long)r37_pcm2_underruns,(unsigned long)r37_pcm2_bytes);
        if(n>0 && n<(int)sizeof(receipt))(void)h9_send_line(receipt,(size_t)n);
    }else if(r51_stop_requested){
        static const char stopped[]="@@DFPCM2 USER_STOPPED\n";
        (void)h9_send_line(stopped,sizeof(stopped)-1);
        r51_stop_requested=false;
        ESP_LOGI(TAG,"R51_USER_STOPPED_PCM2");
    }else{
        ESP_LOGE(TAG,"R37_PCM2_PLAY_FAILED abort=%u",r37_pcm2_abort);
        static const char receipt[]="@@DFPCM2 FAILED\n";
        (void)h9_send_line(receipt,sizeof(receipt)-1);
    }
#ifdef DF_R47_PCM2_DIAGNOSTIC
    r47_audio_motion=3;r47_motion_epoch++;
    ESP_LOGI(TAG,"R47_PCM2_SHORT_GAP_DIAG waits_ge_10ms=%lu max_wait_ms=%lu low_queue_100ms=%lu",
        (unsigned long)r47_short_waits,(unsigned long)r47_max_wait_ms,
        (unsigned long)r47_low_queue);
#endif
    speaking=false;
    r37_pcm2_active=false;
    r37_pcm2_worker_running=false;
#ifdef DF_H11_PREVIEW_STATES
    // R238: verified finished codec playback is a physical terminal
    // transition. Do not keep WakeNet blocked by a stale Mac display phase
    // if an optional STATE1 idle/motion ACK was missed.
    if(played && !failed && !r37_pcm2_abort &&
       !capturing && !h10_receiving &&
       strcmp(h11_current_state.phase,"speaking")==0){
        snprintf(h11_current_state.phase,sizeof(h11_current_state.phase),"idle");
        ESP_LOGI(TAG,"R238_PCM2_FINISHED_BOARD_IDLE_REARM");
    }
#endif
#ifdef DF_R185_WN9
    r185_wake_resume();
#endif
    vTaskDelete(NULL);
}
static void r37_pcm2_control(const char *line){
#ifdef DF_R47_PCM2_DIAGNOSTIC
    if(strcmp(line,"@@DFPCM2 STATS")==0){
        char diag[128];
        int n=snprintf(diag,sizeof(diag),
             "@@DFPCM2 STATS waits=%lu max_wait_ms=%lu low_100ms=%lu ring_bytes=%u\n",
             (unsigned long)r47_short_waits,(unsigned long)r47_max_wait_ms,
             (unsigned long)r47_low_queue,(unsigned)R37_RING_BYTES);
        if(n>0 && n<(int)sizeof(diag))(void)h9_send_line(diag,(size_t)n);
        return;
    }
#endif
    if(strcmp(line,"@@DFPCM2 CAPS")==0){
        static const char caps[]="@@DFPCM2 READY rate=24000 block=960 mode=ring\n";
        (void)h9_send_line(caps,sizeof(caps)-1);return;
    }
    // Read-only numeric physical media ownership. ACK from CAPS alone is
    // insufficient to demonstrate that an earlier PCM2 worker exited.
    if(strcmp(line,"@@DFPCM2 STATE")==0){
        char state[145];
        int n=snprintf(state,sizeof(state),
            "@@DFPCM2 STATE active=%u worker=%u speak=%u capture=%u h10=%u\n",
            (unsigned)r37_pcm2_active,(unsigned)r37_pcm2_worker_running,
            (unsigned)speaking,(unsigned)capturing,(unsigned)h10_receiving);
        if(n>0&&n<(int)sizeof(state))h9_send_line(state,(size_t)n);
        return;
    }
    if(strcmp(line,"@@DFPCM2 BEGIN")==0){
        if(r37_pcm2_active||r37_pcm2_worker_running||h10_receiving ||
           speaking||capturing||loopback_busy||r268_lan_busy){
            static const char busy[]="@@DFPCM2 NACK busy\n";
            (void)h9_send_line(busy,sizeof(busy)-1);return;
        }
        if(!r37_stream_bytes){
            size_t free_psram=heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
            if(free_psram<R37_RING_BYTES+380000u){
                ESP_LOGW(TAG,"R44_PCM2_PSRAM_RESERVE_DENIED free=%lu need=%lu",
                    (unsigned long)free_psram,
                    (unsigned long)(R37_RING_BYTES+380000u));
                static const char fail[]="@@DFPCM2 NACK no_psram\n";
                (void)h9_send_line(fail,sizeof(fail)-1);return;
            }
            r37_stream_bytes=heap_caps_malloc(R37_RING_BYTES+1,
                    MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
        }
        if(!r37_stream_bytes){
            static const char fail[]="@@DFPCM2 NACK no_psram\n";
            (void)h9_send_line(fail,sizeof(fail)-1);return;
        }
        r37_stream=xStreamBufferCreateStatic(R37_RING_BYTES+1,1,
                                             r37_stream_bytes,&r37_stream_ctl);
        if(!r37_stream){
            static const char fail[]="@@DFPCM2 NACK ring\n";
            (void)h9_send_line(fail,sizeof(fail)-1);return;
        }
#ifdef DF_R185_WN9
        // The WakeNet task holds the mic + codec lease while idle. Do not
        // spawn priority-5 PCM2 worker until the priority-3 mic task has
        // physically closed it; otherwise new lease immediately fails.
        if(!r185_wake_wait_released(2300)){
            r185_wake_resume();
            static const char mic_busy[]="@@DFPCM2 NACK mic_handoff\n";
            (void)h9_send_line(mic_busy,sizeof(mic_busy)-1);return;
        }
#endif
        r37_pcm2_seq=0;r37_pcm2_bytes=0;r37_pcm2_underruns=0;
        r37_pcm2_end=false;r37_pcm2_abort=false;
        r37_pcm2_play_begin=false;r37_pcm2_active=true;speaking=true;
        r50_last_pcm2_rx=xTaskGetTickCount();
#ifdef DF_R47_PCM2_DIAGNOSTIC
        r47_short_waits=0;r47_max_wait_ms=0;r47_low_queue=0;
        r47_audio_motion=1;r47_motion_epoch++;
#endif
        if(xTaskCreate(r37_pcm2_worker,"pcm2_play",VOICE_TASK_STACK_BYTES,
                       NULL,5,NULL)!=pdPASS){
            r37_pcm2_active=false;speaking=false;
#ifdef DF_R185_WN9
            r185_wake_resume();
#endif
#ifdef DF_R47_PCM2_DIAGNOSTIC
            r47_audio_motion=3;r47_motion_epoch++;
#endif
            static const char fail[]="@@DFPCM2 NACK worker\n";
            (void)h9_send_line(fail,sizeof(fail)-1);return;
        }
        static const char yes[]="@@DFPCM2 ACCEPTED\n";
        (void)h9_send_line(yes,sizeof(yes)-1);return;
    }
    if(strcmp(line,"@@DFPCM2 CANCEL")==0){
        if(r37_pcm2_active)r37_pcm2_abort=true;
        static const char yes[]="@@DFPCM2 CANCELLED\n";
        (void)h9_send_line(yes,sizeof(yes)-1);return;
    }
    if(!r37_pcm2_active || r37_pcm2_end){
        static const char fail[]="@@DFPCM2 NACK not_active\n";
        (void)h9_send_line(fail,sizeof(fail)-1);return;
    }
    if(strcmp(line,"@@DFPCM2 END")==0){
        if(r37_pcm2_seq==0){
            r37_pcm2_abort=true;
            static const char fail[]="@@DFPCM2 NACK empty\n";
            (void)h9_send_line(fail,sizeof(fail)-1);return;
        }
        r37_pcm2_end=true;
        static const char yes[]="@@DFPCM2 DRAINING\n";
        (void)h9_send_line(yes,sizeof(yes)-1);return;
    }
    if(strncmp(line,"@@DFPCM2 CHUNK ",15)==0){
        unsigned seq=0;int used=0;size_t n=0;
        uint8_t bytes[R37_PACKET_BYTES];
        if(sscanf(line,"@@DFPCM2 CHUNK %u %n",&seq,&used)!=1 ||
           used<=0 || seq!=r37_pcm2_seq ||
           mbedtls_base64_decode(bytes,sizeof(bytes),&n,
                 (const uint8_t*)(line+used),strlen(line+used))!=0 ||
           n==0 || n%2 || n>R37_PACKET_BYTES ||
           r37_pcm2_bytes+n>24000u*2u*180u){
            r37_pcm2_abort=true;
            static const char fail[]="@@DFPCM2 NACK chunk\n";
            (void)h9_send_line(fail,sizeof(fail)-1);return;
        }
        size_t pushed=xStreamBufferSend(r37_stream,bytes,n,pdMS_TO_TICKS(5000));
        if(pushed!=n){
            r37_pcm2_abort=true;
            static const char fail[]="@@DFPCM2 NACK ring_overrun\n";
            (void)h9_send_line(fail,sizeof(fail)-1);return;
        }
        r50_last_pcm2_rx=xTaskGetTickCount();
        r37_pcm2_bytes+=(uint32_t)n;r37_pcm2_seq++;
        char ack[65];
        int len=snprintf(ack,sizeof(ack),"@@DFPCM2 ACK %u\n",seq);
        if(len>0 && len<(int)sizeof(ack))(void)h9_send_line(ack,(size_t)len);
    }
}
#endif

static void h10_dynamic_cancel(void){
    h10_receiving=false;
    if(h10_dynamic_pcm)heap_caps_free(h10_dynamic_pcm);
    h10_dynamic_pcm=NULL;
    h10_expected=0;h10_received=0;h10_seq=0;
}
static int16_t h10_soft_peak(int16_t sample, uint32_t position, uint32_t total){
    int32_t x=sample,mag=x<0?-x:x;
    // Former 12k:4 compressor made already-quiet Qwen speech even quieter.
    // Smooth-knee 18k:2 keeps transients below 25.4k, no hard clipping.
    if(mag>18000)mag=18000+(mag-18000)/2;
    // 10ms cosine-like linear gain ramps eliminate DAC edge discontinuity.
    if(position<240)mag=(mag*(int32_t)position)/240;
    if(total-position<240)mag=(mag*(int32_t)(total-position))/240;
    return (int16_t)(x<0?-mag:mag);
}

#ifdef DF_H28_HOLD_MIC
// All 35 DFSP clips are genuine 240x240, 8fps. Their opaque character
// occupies differing vertical pixels. Measured from the first 8 decoded
// approved frames; a bounded render-only adjustment normalizes main poses
// without rewriting SD media or clipping the feet during close-ups.
static uint16_t h29_motion_scale(unsigned id){
    switch(id){
    case 0:return 231; case 1:return 260; case 2:return 233;
    case 3:return 232; case 8:return 274; case 10:return 233;
    case 11:return 251; case 13:return 242; case 14:return 230;
    case 15:return 268; case 16:return 232; case 18:return 259;
    case 19:return 247; case 20:return 232; case 23:return 235;
    case 24:return 272; case 25:return 240; case 26:return 230;
    case 27:return 265; case 28:return 274; case 30:return 232;
    case 61:return 239; case 62:return 255; case 67:return 274;
    case 70:return 274; case 71:return 234; case 72:return 233;
    case 73:return 234; case 75:return 240; case 80:return 274;
    case 81:return 233; case 83:return 274; case 97:return 268;
    case 99:return 274; case 105:return 271;
    default:return 256;
    }
}
static const char *h28_ui_phase_text(const char *phase);
#endif
static size_t sprite_read(void *unused, size_t off, uint8_t *dst, size_t count){
    (void)unused;
#ifdef DF_H12_SD_ANIM
    if(h12_use_sd)return h12_sd_read_motion(off,dst,count);
#endif
    size_t len=(size_t)(anim_end-anim_start);
    if(off>len||count>len-off)return 0;
    memcpy(dst,anim_start+off,count);return count;
}
static void ui_status(const char *s){
    if(esp_lv_adapter_lock(1000)!=ESP_OK)return;
    lv_label_set_text(status_label,r59_local_status(s));
    esp_lv_adapter_unlock();
}
static int reset_decoder(dfsp_decoder *dec){
    size_t cap=SPRITE_W*SPRITE_W*3u;
    size_t bytes=(size_t)(anim_end-anim_start);
#ifdef DF_H12_SD_ANIM
    if(h12_use_sd)bytes=h12_sd_motion_size();
#endif
    int rc=dfsp_open_reader(dec,sprite_read,NULL,bytes,
         raw_frame,cap,delta,cap,compressed,R71_DFSP_COMPRESSED_MAX);
    if(rc==DFSP_OK && (dec->width!=SPRITE_W ||dec->height!=SPRITE_W||
                      dec->fps!=8))return DFSP_ERR_HEADER;
    return rc;
}
static void animation_worker(void *unused){
    (void)unused;
    dfsp_decoder dec={0};
    int rc=reset_decoder(&dec);
    ESP_LOGI(TAG,"ANIM_TASK_STARTED stack_alloc=%u watermark=%u free_internal=%u free_psram=%u",
             (unsigned)ANIMATION_TASK_STACK_BYTES,
             (unsigned)uxTaskGetStackHighWaterMark(NULL),
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT),
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
    unsigned loops=0;
#ifdef DF_H28_HOLD_MIC
    unsigned h29_active_motion_id=0;
    unsigned h29_display_motion_id=999;
#endif
    TickType_t tick=xTaskGetTickCount();
    bool was_capture_paused=false;
    // R401: a local SD greeting releases playback_file; the in-flight DFSP
    // decoder becomes stale and must NEVER read through sprite_read afterward.
    bool r401_reader_needs_rebind=false;
    r302_breath_state_t r302_breath={0};
    // R407 original-image animation cache: 16 genuine m000 composited RGB565
    // frames, copied once during idle; recording uses NO SD or DFSP read.
    enum { R407_RECORD_FRAMES=16, R407_FRAME_BYTES=SPRITE_W*SPRITE_W*2 };
    uint8_t *r407_cache=NULL;
    unsigned r407_cached=0,r407_play_index=0,r407_cache_copies=0;
    unsigned r407_lock_misses=0,r407_record_draws=0;
    bool r407_no_memory_logged=false;
    // R510: the identical background/shadow was being recomputed and
    // blended from scratch on every 240x240 frame. Prepare it once in
    // PSRAM; insufficient memory falls back to R509 pixel-exact behavior.
    // This does not change SD/DFSP bytes, image identity or LVGL pointers.
    uint8_t *r510_stage=heap_caps_malloc(R407_FRAME_BYTES,
                                        MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if(r510_stage){
        dfsp_stage_background(r510_stage,SPRITE_W,SPRITE_W);
        dfsp_stage_soft_shadow(r510_stage,SPRITE_W,SPRITE_W,120,216,78,14);
        r510_stage_ready=1;
        ESP_LOGI(TAG,"R510_STAGE_STATIC_CACHE_READY bytes=%u",
                 (unsigned)R407_FRAME_BYTES);
    }else{
        ESP_LOGW(TAG,"R510_STAGE_STATIC_CACHE_FALLBACK");
    }
    TickType_t r407_last_show=0;
    // The SD audio owns the file reader, not the LVGL canvas. Restore the
    // original scale as soon as the local audio lease is released.
    bool r259_pulse_active=false;
    unsigned r259_pulse_tick=0;
    int32_t r259_rest_scale=256;
    static uint32_t r222_slow_samples=0;
    for(;;){
        r322_anim_heartbeat++;
        r322_anim_last_tick=(uint32_t)xTaskGetTickCount();
        r322_anim_hold=0;
        // Diagnostic-only candidate, microsecond monotonic profiling.
        // No extra display redraw, SD read, USB command or task priority.
        const int64_t r222_frame_begin_us=esp_timer_get_time();
        r83_animation_sd_quiescent_boundary();
        // R280 real-user regression: freezing the whole avatar during a LAN
        // turn made both the whale and touch-menu redraw visibly worse.
        // Restore the original animated compositor, with a slower 250ms
        // cadence during TLS/DSH/PCM to yield display time to LVGL.
        // No R42 second image descriptor or PSRAM frame-buffer swap.
#ifdef DF_H13_SD_UPLOAD
        if(r154_sd_upload_pause_requested){
            r322_anim_hold=1;
            // Physical Hi-Lexin greeting plays from SD; keep the existing
            // static DFSP source and pulse its complete image very slowly.
            r302_breathe_complete_image(&r302_breath,
                 r302_wake_greeting_visual && speaking &&
                 !r259_local_speaking_visual,true,picture);
            if(!r154_sd_upload_paused){
                h12_sd_clear_motion();
                h12_use_sd=false;
                h13_sd_release_selected();
                // Do not permit stale decoder's SD offsets to target embedded
                // art while WSS is busy and boot-idle rebind is deferred.
                r401_reader_needs_rebind=true;
                r154_sd_upload_paused=true;
                ESP_LOGI(TAG,"R401_SD_DECODER_INVALIDATED_BY_WAKE_PAUSE");
            }
            // The animation reader must stay quiescent for the SD WAV,
            // but the LCD itself can still visibly animate in RAM without
            // ever touching FatFs or the Mac. Move the existing avatar by a
            // few pixels in a safe gentle speaking pulse; restore afterward.
            if(r259_local_speaking_visual && speaking){
                if(esp_lv_adapter_lock(35)==ESP_OK){
                    if(picture){
                        if(!r259_pulse_active){
                            r259_rest_scale=(int32_t)lv_image_get_scale(picture);
                            r259_pulse_active=true;
                        }
                        const int8_t step[]={0,2,5,3,0,-2};
                        lv_image_set_scale(picture,(uint32_t)(r259_rest_scale+
                                 step[(r259_pulse_tick++)%6]));
                        lv_obj_invalidate(picture);
                    }
                    esp_lv_adapter_unlock();
                }
            }else if(r259_pulse_active){
                if(esp_lv_adapter_lock(35)==ESP_OK){
                    if(picture){lv_image_set_scale(picture,(uint32_t)r259_rest_scale);
                        lv_obj_invalidate(picture);}
                    r259_pulse_active=false;
                    esp_lv_adapter_unlock();
                }
            }
            vTaskDelay(pdMS_TO_TICKS(80));
            continue;
        }
#endif
        if(r259_pulse_active){
            if(esp_lv_adapter_lock(35)==ESP_OK){
                if(picture){
                    lv_image_set_scale(picture,(uint32_t)r259_rest_scale);
                    lv_obj_invalidate(picture);
                }
                r259_pulse_active=false;
                esp_lv_adapter_unlock();
            }
        }
        if(r83_transfer_active()){
            r322_anim_hold=2;
            vTaskDelay(pdMS_TO_TICKS(70));
            continue;
        }
        static bool r103_prompt_visible=false;
        if(r83_arm_pending()&&!r103_prompt_visible){
            ui_status("Tap avatar to authorize SD upload");
            r103_prompt_visible=true;
        }else if(!r83_arm_pending()){r103_prompt_visible=false;}
        /* R82 static panel: no decoder writes, no full-frame dynamic image.
           Test ONLY after physical supervised upgrade. */
        unsigned requested=r82_display_mode;
        if(requested!=r82_current_mode){
            if(esp_lv_adapter_lock(1000)==ESP_OK){
                for(unsigned idx=0;idx<4;idx++){
                    if(r82_quad[idx]){lv_obj_delete(r82_quad[idx]);r82_quad[idx]=NULL;}
                }
                if(requested==1u){
                    static const uint32_t colors[4]={0xff0000,0x00ff00,0x0000ff,0xffffff};
                    lv_obj_t *canvas=lv_screen_active();
                    for(unsigned idx=0;idx<4;idx++){
                        r82_quad[idx]=lv_obj_create(canvas);
                        lv_obj_remove_style_all(r82_quad[idx]);
                        lv_obj_set_size(r82_quad[idx],240,240);
                        lv_obj_set_pos(r82_quad[idx],(idx%2u)*240,(idx/2u)*240);
                        lv_obj_set_style_bg_color(r82_quad[idx],lv_color_hex(colors[idx]),0);
                        lv_obj_set_style_bg_opa(r82_quad[idx],LV_OPA_COVER,0);
                        lv_obj_remove_flag(r82_quad[idx],LV_OBJ_FLAG_CLICKABLE);
                        lv_obj_move_foreground(r82_quad[idx]);
                    }
                    r82_static_enters++;
                }
                if(requested==2u)r82_static_enters=0;
                r82_current_mode=requested;
                r82_mode_changes++;
                esp_lv_adapter_unlock();
                ESP_LOGI(TAG,"R82_MODE mode=%u internal=%lu largest=%lu psram=%lu",
                  requested,
                  (unsigned long)heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
                  (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
                  (unsigned long)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
            }
        }
        if(r82_current_mode==1u ||
           (r82_current_mode==2u && r82_static_enters>0u)){
            r322_anim_hold=3;
            vTaskDelay(pdMS_TO_TICKS(90));
            continue;
        }
#ifdef DF_R33_BOARD_UI
#ifdef DF_H11_PREVIEW_STATES
        if(r33_error_since &&
            (int32_t)(xTaskGetTickCount()-r33_error_since)>=pdMS_TO_TICKS(6000) &&
            !capturing && !speaking && !h10_receiving &&
            h12_req_seq==h12_done_seq){
            // Local display recovery only; no forged DSH reply or ACK.
            r33_error_since=0;
            snprintf(h11_current_state.phase,sizeof(h11_current_state.phase),"idle");
            if(h12_sd_choose_motion(0)==0){
                h12_use_sd=true;
                dfsp_decoder rest={0};
                if(reset_decoder(&rest)==DFSP_OK){
                    dec=rest;rc=DFSP_OK;loops=0;
                    h28_touch_return_idle=false;
                    h29_active_motion_id=0;
                    h28_last_idle_stage_tick=(uint32_t)xTaskGetTickCount();
                    ui_status("Ready - previous request failed");
                    ESP_LOGI(TAG,"R34_ERROR_AUTO_IDLE local_display_only");
                }
            }
        }
#endif
#endif
        // The mic/USB worker has higher priority and can block for several
        // seconds. Hold the last COMPLETE frame instead of partially mutating
        // the sole LVGL image buffer and allowing delayed-frame bursts.
#ifdef DF_R434_MAC_PREWAKE_ONLY
        const bool r436_ack_visual=r436_wake_ack_wave_active;
        if(capturing || r436_ack_visual){
#else
        if(capturing){
#endif
            r322_anim_hold=4;
            // Cancel any historic R302 scale pulse. No geometric bounce.
            r302_breathe_complete_image(&r302_breath,false,false,picture);
            if(!was_capture_paused){
                r407_play_index=0;
                r407_last_show=0;
                r407_record_draws=0;
                r407_lock_misses=0;
                ESP_LOGI(TAG,"R412_LISTEN_START dedicated_waveform_cached=%u frame=%u",
                         r407_cached,(unsigned)dec.frame_index);
#ifdef DF_R434_MAC_PREWAKE_ONLY
                if(r436_ack_visual)
                    ESP_LOGI(TAG,"R436_ACK_WAVE_START cached=%u",(unsigned)r407_cached);
#endif
                was_capture_paused=true;
            }
            // Never read FAT/SDMMC or decode DFSP during microphone capture.
            // Preserve original LVGL picture/data pointer and 240x240 frame.
            TickType_t r407_now=xTaskGetTickCount();
            if(r407_cached==R407_RECORD_FRAMES &&
               (!r407_last_show ||
                (r407_now-r407_last_show)>=pdMS_TO_TICKS(125))){
                if(esp_lv_adapter_lock(25)==ESP_OK){
                    if(picture && image_desc.data==frame_rgb){
                        memcpy(frame_rgb,r407_cache+
                               (r407_play_index%R407_RECORD_FRAMES)*R407_FRAME_BYTES,
                               R407_FRAME_BYTES);
                        lv_obj_invalidate(picture);
                        r407_play_index++;
                        r407_record_draws++;
                        r407_last_show=r407_now;
#ifdef DF_R434_MAC_PREWAKE_ONLY
                        if(r436_ack_visual && !r436_wake_ack_first_frame_ready){
                            r436_wake_ack_first_frame_ready=true;
                            ESP_LOGI(TAG,"R436_ACK_WAVE_FIRST_FRAME drawn=1");
                        }
#endif
                    }
                    esp_lv_adapter_unlock();
                }else{
                    r407_lock_misses++;
                }
            }
            // R436: the same no-SD cached path remains active from local
            // greeting through 650ms handoff and authenticated mic capture.
            // Do not reset r407_play_index when capturing becomes true.
            // Failure to build the cache means hold the last genuine frame,
            // never synthesize an animation or risk sampling interruptions.
            tick=xTaskGetTickCount();
            vTaskDelay(pdMS_TO_TICKS(35));
            continue;
        }
        r302_breathe_complete_image(&r302_breath,false,false,picture);
        if(was_capture_paused){
            // R408: numeric evidence only, never sample or record voice data.
            ESP_LOGI(TAG,"@@DFLISTEN1 DIAG cached=%u copies=%u draws=%u lock_miss=%u psram_free=%lu",
                     r407_cached,r407_cache_copies,r407_record_draws,r407_lock_misses,
                     (unsigned long)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
            ESP_LOGI(TAG,"H8_ANIMATION_RESUME_AFTER_MIC frame=%u",dec.frame_index);
            was_capture_paused=false;
            tick=xTaskGetTickCount();
        }
#if defined(DF_R47_PCM2_DIAGNOSTIC) && defined(DF_H12_SD_ANIM)
        // Safe local animation swap at a verified PCM2 lifecycle event.
        // No USB command/ACK contention with the streaming audio producer.
        // This branch does not run for R36/R46-A or normal idle animations.
        static uint32_t r47_seen_epoch=0;
        // The LAN phase and real DAC ownership outlive a single r47 epoch.
        // R323 consumed the epoch even if a verified SD motion was briefly
        // unavailable or replaced by the pending boot-idle selection.
        static bool r332_previous_talking=false;
        static TickType_t r332_last_try=0;
        static unsigned r332_talk_tries=0;
        r332_trace_init();
        const bool r332_talking=
             r268_lan_busy && r268_current_phase==R268_LAN_SPEAKING &&
             speaking && r47_audio_motion==2;
        if(r332_talking && !r332_previous_talking){
            r332_talk_tries=0;r332_last_try=0;
            r332_motion_trace.talk_starts++;
#ifdef DF_H13_SD_UPLOAD
            if(h13_boot_idle_pending)r332_motion_trace.deferred_idle++;
#endif
        }
        if(!r332_talking && r332_previous_talking){
            r332_talk_tries=0;r332_last_try=0;
        }
        r332_previous_talking=r332_talking;
        const TickType_t r332_now=xTaskGetTickCount();
        const bool r332_reconcile=r332_talking &&
            (h29_active_motion_id!=30u || !h12_use_sd) &&
            r332_talk_tries<4u &&
            (r332_last_try==0 ||
             r332_now-r332_last_try>=pdMS_TO_TICKS(1800));
        uint32_t epoch=r47_motion_epoch;
        if((epoch!=r47_seen_epoch || r332_reconcile) &&
           !capturing && h12_req_seq==h12_done_seq){
            uint8_t desired_state=r332_reconcile?2:r47_audio_motion;
            if(r332_talking && desired_state==2){
                r332_last_try=r332_now;
                r332_talk_tries++;
                r332_motion_trace.talk_attempts++;
            }
            unsigned desired_id=desired_state==1?24u:desired_state==2?30u:0u;
            const TickType_t r140_switch_began=xTaskGetTickCount();
            if(h12_sd_choose_motion(desired_id)==0){
                h12_use_sd=true;
                dfsp_decoder swap={0};
                if(reset_decoder(&swap)==DFSP_OK){
                    dec=swap;rc=DFSP_OK;loops=0;
                    h29_active_motion_id=desired_id;
                    h28_touch_return_idle=false;
                    r47_seen_epoch=epoch;
                    if(r332_talking && desired_id==30u){
                        r332_motion_trace.talk_applied++;
                        r332_motion_trace.last_selected=30u;
                    }
                    ESP_LOGI(TAG,"R47_REAL_PCM2_MOTION state=%u id=m%03u",desired_state,desired_id);
                    if(r332_talking && desired_id==30u)
                        ESP_LOGI(TAG,"R332_LAN_MOUTH_SELECTED retry=%u",r332_talk_tries);
                }else{
                    h12_sd_clear_motion();h12_use_sd=false;rc=reset_decoder(&dec);
                    r47_seen_epoch=epoch;
                    ESP_LOGW(TAG,"R47_PCM2_MOTION_UNAVAILABLE state=%u",desired_state);
                    if(r332_talking && desired_id==30u)r332_motion_trace.talk_fail++;
                }
            }else{
                r47_seen_epoch=epoch;
                ESP_LOGW(TAG,"R47_PCM2_MOTION_NOT_SELECTED id=%u",desired_id);
                if(r332_talking && desired_id==30u)r332_motion_trace.talk_fail++;
            }
            const uint32_t r140_switch_ms=(uint32_t)(
                (xTaskGetTickCount()-r140_switch_began)*portTICK_PERIOD_MS);
            ESP_LOGI(TAG,"R140_AUDIO_MOTION_TRANSITION state=%u id=%u elapsed_ms=%lu frame=%u",
                desired_state,desired_id,(unsigned long)r140_switch_ms,
                (unsigned)dec.frame_index);
        }
#endif
#if defined(DF_H13_SD_UPLOAD) && defined(DF_H12_SD_ANIM)
        // Only after the 35-file user-selected collection is verified may
        // the idle sprite replace the built-in rice fallback at boot.
        // This autonomous boot choice does NOT consume host seq=1 or claim
        // a received USB APPLIED receipt, and no microphone is opened.
        // The boot/SD-release idle request is lower priority than a real
        // authenticated WSS turn. Otherwise m000 can overwrite m030 just
        // after R47 marks the speaker transition as handled.
        if(h13_boot_idle_pending && !r268_lan_busy &&
           !capturing && !speaking && !h10_receiving){
            h13_boot_idle_pending=false;
            if(h12_sd_choose_motion(0)==0){
                h12_use_sd=true;
                dfsp_decoder idle={0};
                int ready=reset_decoder(&idle);
                if(ready==DFSP_OK){
                    dec=idle;rc=ready;loops=0;
#ifdef DF_H28_HOLD_MIC
                    h29_active_motion_id=0;
#endif
                    ESP_LOGI(TAG,"H13_BOOT_SELECTED_IDLE m000 approved35=1");
                }else{
                    h12_sd_clear_motion();h12_use_sd=false;
                    rc=reset_decoder(&dec);
                    ESP_LOGW(TAG,"H13_BOOT_IDLE_DECODE_FAILED embedded_fallback");
                }
            }
        }
#endif
#ifdef DF_H12_SD_ANIM
        // The animation worker is the only thread that reads the SD card.
        // Only signal actual completion after the first DFSP frame is decoded.
#ifdef DF_H28_HOLD_MIC
        if(h28_touch_requested && h12_req_seq==h12_done_seq && !capturing){
            h28_touch_requested=false;
            // Four clearly different approved classic touch reactions.
            static const unsigned touch_ids[]={13,14,15,16};
            unsigned round=h28_tap_count++;
            bool dragged=r133_drag_requested;
            r133_drag_requested=false;
            unsigned selected=r57_local_motion_request?
                         r57_local_motion_request-1:
                         r150_rules_pick(dragged?5:1,round,touch_ids[round%4]);
            r57_local_motion_request=0;
            h28_last_idle_stage_tick=(uint32_t)xTaskGetTickCount();
            // R109 diagnostics only: preserve ALL original SD touch paths,
            // sprites and status messages. No interaction is removed.
            TickType_t select_start=xTaskGetTickCount();
            ESP_LOGI(TAG,"R109_TOUCH_SD_SELECT_BEGIN id=%u",selected);
            int select_ok=h12_sd_choose_motion(selected);
            ESP_LOGI(TAG,"R109_TOUCH_SD_SELECT_END id=%u result=%d ms=%lu",
                selected,select_ok,(unsigned long)((xTaskGetTickCount()-select_start)*portTICK_PERIOD_MS));
            if(select_ok==0){
                h12_use_sd=true;
                dfsp_decoder touch={0};
                ESP_LOGI(TAG,"R109_TOUCH_DFSP_RESET_BEGIN id=%u",selected);
                int load=reset_decoder(&touch);
                ESP_LOGI(TAG,"R109_TOUCH_DFSP_RESET_END id=%u result=%d",selected,load);
                if(load==DFSP_OK){
                    dec=touch;rc=load;loops=0;h28_touch_return_idle=true;
                    h28_local_frame_id=selected;h28_local_frame_kind=1;
                    h29_active_motion_id=selected;
                }
                else{h12_sd_clear_motion();h12_use_sd=false;rc=reset_decoder(&dec);}
            }
        }
#endif
#ifdef DF_H28_HOLD_MIC
        // Only a *genuinely idle* hardware companion may play low-frequency
        // approved extras. No DSH model call, no mic activation, no invented
        // successful tool action. Mac state commands always take precedence.
        uint32_t idle_tick=(uint32_t)xTaskGetTickCount();
        // R392: only reset idle timing around true mic/PCM/WSS activity.
        // Prevent a >90s DSH or TTS run from triggering a pending bonus/idle
        // action immediately after speaking; never truncate full SD m000.
        static bool r392_had_real_activity=false;
        const bool r392_real_activity=r268_lan_busy || capturing ||
                                      speaking || h10_receiving;
        if(r392_real_activity)r392_had_real_activity=true;
        else if(r392_had_real_activity){
            h28_last_idle_stage_tick=idle_tick;
            r392_had_real_activity=false;
            ESP_LOGI(TAG,"R392_IDLE_TIMER_RESET_AFTER_WSS_OR_PCM");
        }
        bool is_idle=true;
#ifdef DF_H11_PREVIEW_STATES
        is_idle=strcmp(h11_current_state.phase,"idle")==0;
#endif
        if(is_idle && !r268_lan_busy &&
           !h28_touch_return_idle && !h28_touch_requested &&
           !capturing && !speaking && !h10_receiving &&
           h12_req_seq==h12_done_seq &&
           idle_tick-h28_last_idle_stage_tick>=pdMS_TO_TICKS(600000)){
            static const unsigned everyday[]={2,3,10,11};
            static const unsigned bonus[]={61,62,67,83,97,99,105};
            unsigned selected;
            if(idle_tick-h28_last_bonus_tick>=pdMS_TO_TICKS(900000)){
                unsigned round=h28_bonus_count++;
                selected=r150_rules_pick(3,round,bonus[round%7]);
                h28_last_bonus_tick=idle_tick;
                ESP_LOGI(TAG,"H28_VERIFIED_IDLE_EASTER_EGG id=%u",selected);
            }else{
                unsigned round=h28_ordinary_count++;
                selected=r150_rules_pick(2,round,everyday[round%4]);
                ESP_LOGI(TAG,"H28_VERIFIED_IDLE_VARIATION id=%u",selected);
            }
            h28_last_idle_stage_tick=idle_tick;
            if(h12_sd_choose_motion(selected)==0){
                h12_use_sd=true;
                dfsp_decoder extra={0};
                int loaded=reset_decoder(&extra);
                if(loaded==DFSP_OK){
                    dec=extra;rc=loaded;loops=0;h28_touch_return_idle=true;
                    h28_local_frame_id=selected;h28_local_frame_kind=2;
                    h29_active_motion_id=selected;
                }
                else{h12_sd_clear_motion();h12_use_sd=false;rc=reset_decoder(&dec);}
            }
        }
#endif
#if defined(DF_H12_SD_ANIM) && defined(DF_H28_HOLD_MIC)
        // R303: the wireless WSS worker owns the phase. The old R36 work
        // mapping below reads USB/DSH state and stays idle on a battery LAN
        // turn. Show a real verified m024 SD work animation *after* the mic
        // finishes, without decoding or writing PSRAM during capture.
        // Never override R47's real m024 -> m030 -> m000 speaker lifecycle.
        static bool r303_work_motion_owned=false;
        static TickType_t r303_last_attempt=0;
        static TickType_t r303_last_switch=0;
        static uint32_t r304_work_round=0;
        static const unsigned r304_work_ids[]={24u,26u};
        const TickType_t r303_now=xTaskGetTickCount();
        // R587: after a physically played Pinky announcement the same
        // authenticated WSS turn can go silent for tool work. The audio
        // offer remains true, but the phase now truthfully returns to
        // THINKING. Show audited m024/m026 while lips are closed.
        // R614: the prior work clip no longer owns the display as soon as
        // real PCM is playing. The next silent interval may select a work
        // clip immediately, without a stale 12-second rotation cooldown.
        if(r268_lan_busy && r268_current_phase==R268_LAN_SPEAKING &&
           speaking && r303_work_motion_owned)
            r303_work_motion_owned=false;
        const bool r303_wifi_wait=
            r268_lan_busy && r268_current_phase==R268_LAN_THINKING;
        if(r303_trace.magic!=R303_MOTION_MAGIC){
            r303_trace.magic=R303_MOTION_MAGIC;
            r303_trace.work_selected=0;
            r303_trace.work_failed=0;
            r303_trace.idle_restores=0;
        }
        if(r303_wifi_wait &&
           (!r303_work_motion_owned ||
             r303_now-r303_last_switch>=pdMS_TO_TICKS(12000)) &&
           !capturing && !speaking && !h10_receiving &&
           h12_req_seq==h12_done_seq &&
           (r303_last_attempt==0 ||
            r303_now-r303_last_attempt>=pdMS_TO_TICKS(3000))){
            r303_last_attempt=r303_now;
            // Only audited, context-appropriate work clips m024/m026.
            // m025 resembles a cross and m027 a premature celebration.
            unsigned r304_id=r304_work_ids[r304_work_round%2u];
            if(h12_sd_choose_motion(r304_id)==0){
                h12_use_sd=true;
                dfsp_decoder work={0};
                if(reset_decoder(&work)==DFSP_OK){
                    dec=work;rc=DFSP_OK;loops=0;
                    h29_active_motion_id=r304_id;
                    h28_touch_return_idle=false;
                    h28_local_frame_kind=0;
                    r303_work_motion_owned=true;
                    r303_last_switch=r303_now;
                    r304_work_round++;
                    r303_trace.work_selected++;
                    ESP_LOGI(TAG,"R304_REAL_WIFI_WORK_MOTION id=m%03u",
                             r304_id);
                }else{
                    h12_sd_clear_motion();h12_use_sd=false;
                    rc=reset_decoder(&dec);
                    r303_trace.work_failed++;
                }
            }else r303_trace.work_failed++;
        }
        // If a short/error turn never opened a speaker, return to m000.
        // An actual speaker owns its own R47 transition and cannot be
        // superseded by this fallback.
        if(r303_work_motion_owned && !r268_lan_busy &&
           !capturing && !speaking && !h10_receiving &&
           h12_req_seq==h12_done_seq){
            if(h29_active_motion_id==0){
                r303_work_motion_owned=false;
                r303_trace.idle_restores++;
            }else if(h12_sd_choose_motion(0)==0){
                h12_use_sd=true;
                dfsp_decoder idle={0};
                if(reset_decoder(&idle)==DFSP_OK){
                    dec=idle;rc=DFSP_OK;loops=0;
                    h29_active_motion_id=0;
                    h28_touch_return_idle=false;
                    r303_work_motion_owned=false;
                    r303_trace.idle_restores++;
                    ESP_LOGI(TAG,"R303_WIFI_WORK_RECOVERED_IDLE m000");
                }else{
                    h12_sd_clear_motion();h12_use_sd=false;
                    rc=reset_decoder(&dec);
                }
            }
        }
#endif
#ifdef DF_R33_BOARD_UI
#ifdef DF_H11_PREVIEW_STATES
        // A long pending DSH/TTS phase should not look like a frozen still.
        // Uses only locally verified assets and never claims a tool result.
        static TickType_t r36_last_work_switch=0;
        bool work_phase=strcmp(h11_current_state.phase,"thinking")==0 ||
            strcmp(h11_current_state.phase,"tool_pending")==0 ||
            strcmp(h11_current_state.phase,"voice_generating")==0 ||
            strcmp(h11_current_state.phase,"transcribing")==0;
        if(!r268_lan_busy && work_phase &&
           !capturing && !speaking && !h10_receiving &&
           h12_req_seq==h12_done_seq && !h28_touch_return_idle &&
           xTaskGetTickCount()-r36_last_work_switch>=pdMS_TO_TICKS(9000)){
            static const unsigned verified_work[]={24,25,26,27};
            unsigned work_round=(unsigned)(xTaskGetTickCount()/pdMS_TO_TICKS(9000));
            unsigned selected=r150_rules_pick(4,work_round,verified_work[work_round%4]);
            if(h12_sd_choose_motion(selected)==0){
                dfsp_decoder work={0};
                if(reset_decoder(&work)==DFSP_OK){
                    dec=work;rc=DFSP_OK;loops=0;
                    h29_active_motion_id=selected;
                }
            }
            r36_last_work_switch=xTaskGetTickCount();
        }
#endif
#endif
        uint32_t desired=h12_req_seq;
        if(desired && desired!=h12_done_seq){
#ifdef DF_H28_HOLD_MIC
            // An authenticated Mac/DSH state supersedes a local tap easter egg.
            h28_touch_return_idle=false;
            h28_local_frame_kind=0;
#endif
            unsigned id=h12_req_id;
            h12_done_seq=desired;
            if(h12_sd_choose_motion(id)==0){
                h12_use_sd=true;
                dfsp_decoder candidate={0};
                int next=reset_decoder(&candidate);
                if(next==DFSP_OK){
                    dec=candidate;rc=next;h12_actual_seq=desired;
                    h12_actual_id=id;loops=0;
#ifdef DF_H28_HOLD_MIC
                    h29_active_motion_id=id;
#endif
                }else{
                    // Fail closed: corrupted DFSP never supplants embedded art.
                    h12_sd_clear_motion();h12_use_sd=false;
                    rc=reset_decoder(&dec);
                    ESP_LOGE(TAG,"H12_SD_ANIMATION_BAD_HEADER id=%u",id);
                    static const char bad[]="@@DFMOTION1 UNAVAILABLE reason=bad_dfsp\n";
                    (void)h9_send_line(bad,sizeof(bad)-1);
                }
            }else{
                static const char unavailable[]="@@DFMOTION1 UNAVAILABLE reason=missing_selected_motion\n";
                (void)h9_send_line(unavailable,sizeof(unavailable)-1);
            }
        }
#endif
#ifdef DF_H28_HOLD_MIC
        // R401: local wake greetings temporarily relinquish the SD reader.
        // WSS can already be LISTENING/THINKING by the time it returns, so
        // the old boot-only idle rebind is intentionally deferred. Re-open a
        // verified original DFSP before the next dfsp_next() in ALL phases.
        if(r401_reader_needs_rebind){
            if(h12_use_sd && h12_sd_motion_size()>0 && rc==DFSP_OK){
                r401_reader_needs_rebind=false;
                ESP_LOGI(TAG,"R401_SD_REBIND_COMPLETED_BY_ROLE_SWITCH");
            }else{
                unsigned rebind_id=0u;
                if(r268_lan_busy && r268_current_phase==R268_LAN_THINKING)
                    rebind_id=24u;
                else if(r268_lan_busy &&
                        r268_current_phase==R268_LAN_SPEAKING)
                    rebind_id=30u;
                if(h12_sd_choose_motion(rebind_id)==0){
                    h12_use_sd=true;
                    dfsp_decoder resumed={0};
                    if(reset_decoder(&resumed)==DFSP_OK){
                        dec=resumed;rc=DFSP_OK;loops=0;
                        h29_active_motion_id=rebind_id;
                        h28_touch_return_idle=false;
                        r401_reader_needs_rebind=false;
                        h13_boot_idle_pending=false;
                        ESP_LOGI(TAG,"R401_SD_REBIND_OK id=m%03u",rebind_id);
                    }else{
                        h12_sd_clear_motion();h12_use_sd=false;
                        ESP_LOGW(TAG,"R401_SD_REBIND_DECODE_RETRY id=m%03u",rebind_id);
                    }
                }else{
                    ESP_LOGW(TAG,"R401_SD_REBIND_SELECT_RETRY id=m%03u",rebind_id);
                }
                if(r401_reader_needs_rebind){
                    // Never pass stale decoder offsets to embedded source.
                    // Bound failed card retries; UI/WSS/DAC remain responsive.
                    tick=xTaskGetTickCount();
                    vTaskDelay(pdMS_TO_TICKS(1800));
                    continue;
                }
            }
        }
        if(rc==DFSP_OK && r268_lan_busy &&
           r268_current_phase==R268_LAN_SPEAKING &&
           speaking && h29_active_motion_id==30u)
            r332_motion_trace.mouth_render_frames++;
        // R415: original m030 frames 17..80 tilt the head and close the mouth.
        // Use the same trusted first-16 lip-sync loop for *actual* audible
        // PCM2 on USB and Wi-Fi; R304 only protected Wi-Fi SPEAKING.
        // PCM2's audible state is set on real codec playback, not while
        // buffering, listening, thinking, or during a local greeting.
        // The only SD decoder is reset at frame 16; no SD or art is edited.
        const bool r415_pcm_mouth16=
            speaking && r47_audio_motion==2u &&
            h12_use_sd && h29_active_motion_id==30u;
        if(rc==DFSP_OK && r415_pcm_mouth16 &&
           dec.frame_index>=16u){
            rc=DFSP_END;
            ESP_LOGI(TAG,"R415_PCM2_MOUTH16_LOOP usb=%u wifi=%u",
                     (unsigned)!r268_lan_busy,
                     (unsigned)(r268_lan_busy &&
                           r268_current_phase==R268_LAN_SPEAKING));
            if(r304_mouth_trace.magic!=R304_MOUTH_DIAG_MAGIC){
                r304_mouth_trace.magic=R304_MOUTH_DIAG_MAGIC;
                r304_mouth_trace.cycles=0;
            }
            r304_mouth_trace.cycles++;
        }
#endif
        if(rc==DFSP_END){
#ifdef DF_H28_HOLD_MIC
            if(h28_touch_return_idle && h12_req_seq==h12_done_seq){
                h28_touch_return_idle=false;
                if(h12_sd_choose_motion(0)==0){
                    h12_use_sd=true;
                    dfsp_decoder idle={0};
                    if(reset_decoder(&idle)==DFSP_OK){
                        dec=idle;rc=DFSP_OK;loops=0;
                        h28_local_frame_id=0;h28_local_frame_kind=2;
                        h29_active_motion_id=0;
                    }
                }
            }
#endif
            loops++;
            if(loops==1)ESP_LOGI(TAG,"AVATAR_ANIM_LOOP_OK frames=%u watermark=%u",dec.frame_count,
                                (unsigned)uxTaskGetStackHighWaterMark(NULL));
            rc=reset_decoder(&dec);
        }
        if(rc!=DFSP_OK){
            ESP_LOGE(TAG,"AVATAR_ANIM_FAILED code=%d frame=%u",rc,dec.frame_index);
            r322_anim_hold=5;r322_anim_failures++;
#ifdef DF_H12_SD_ANIM
            // An SD read/decoder error previously deleted the sole animation
            // worker forever. Drop only the failed SD clip and recover using
            // the immutable embedded avatar. No SD writes or auto reboot.
            if(h12_use_sd){
                h12_sd_clear_motion();h12_use_sd=false;
                dfsp_decoder fallback={0};
                const int fallback_rc=reset_decoder(&fallback);
                if(fallback_rc==DFSP_OK){
                    dec=fallback;rc=DFSP_OK;loops=0;
#ifdef DF_H28_HOLD_MIC
                    h29_active_motion_id=0;
                    h28_touch_return_idle=false;
#endif
                    ESP_LOGW(TAG,"R322_SD_ANIM_RECOVERED_EMBEDDED");
                    tick=xTaskGetTickCount();
                    vTaskDelay(pdMS_TO_TICKS(125));
                    continue;
                }
            }
#endif
            // R401: do not permanently delete h5_anim after a transient SD/
            // decoder failure. A later verified rebind can restore touch,
            // work and idle without power cycling the ESP32.
            ui_status("Animation decode retry");
            h12_sd_clear_motion();h12_use_sd=false;
            r401_reader_needs_rebind=true;
            tick=xTaskGetTickCount();
            vTaskDelay(pdMS_TO_TICKS(2500));
            continue;
        }
        TickType_t r70_frame_start=xTaskGetTickCount();
        const int64_t r222_decode_begin_us=esp_timer_get_time();
        rc=dfsp_next(&dec);
        const int64_t r222_decode_done_us=esp_timer_get_time();
        if(rc==DFSP_OK && (r70_frames%16u)==0u){
            // Frame alpha coverage is a useful decoder/content invariant.
            // Full sprite is typically 25–27k opaque pixels. A missing body
            // is detected before claiming success; LCD hardware must still
            // be inspected by a human for real panel clipping.
            uint32_t opaque=0;
            for(size_t px=0;px<(size_t)SPRITE_W*SPRITE_W;px++)
                if(raw_frame[3u*px+2u]>16u)opaque++;
            r70_opaque_last=opaque;
            // Some fully valid M080 frames contain only 6.3k visible
            // pixels, so 10k was an incorrect anomaly threshold.
            if(opaque<2500u)r70_opaque_invalid++;
        }
        if(rc!=DFSP_OK && rc!=DFSP_END)r70_decoding_errors++;
        const int64_t r222_lock_begin_us=esp_timer_get_time();
        int64_t r222_lock_acquired_us=0,r222_draw_done_us=0;
        if(rc==DFSP_OK && esp_lv_adapter_lock(1000)==ESP_OK){
            r222_lock_acquired_us=esp_timer_get_time();
            // Transparent art must share the *same* RGB565 backing as LVGL.
            // Old 0xE71F left a visible lavender square around the whale.
            if(r510_stage){
                memcpy(frame_rgb,r510_stage,R407_FRAME_BYTES);
            }else{
                dfsp_stage_background(frame_rgb,SPRITE_W,SPRITE_W);
                // The shadow belongs UNDER the feet, behind the real sprite.
                dfsp_stage_soft_shadow(frame_rgb,SPRITE_W,SPRITE_W,120,216,78,14);
            }
            if(dfsp_blit_rgb565a8(raw_frame,SPRITE_W,SPRITE_W,frame_rgb,
                                  SPRITE_W,SPRITE_W,0,0,0)<0){
                ESP_LOGE(TAG,"AVATAR_BLEND_FAILED");rc=DFSP_ERR_STATE;
            }else{
                // R407: collect exactly the first 16 FULLY composited original
                // m000 frames before a recording starts; allocation is only
                // after model ready and with an additional 2 MiB PSRAM reserve.
                if(h12_use_sd && h29_active_motion_id==0u &&
                   !capturing && !speaking && !r268_lan_busy &&
#ifndef DF_R434_MAC_PREWAKE_ONLY
                   r185_wake_ready() &&
#endif
                   dec.frame_index>=1u && dec.frame_index<=R407_RECORD_FRAMES){
                    if(!r407_cache && !r407_no_memory_logged){
                        const size_t need=(size_t)R407_RECORD_FRAMES*R407_FRAME_BYTES;
                        if(heap_caps_get_free_size(MALLOC_CAP_SPIRAM)>need+2097152u &&
                           heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM)>=need){
                            r407_cache=heap_caps_malloc(need,
                                       MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
                        }
                        if(!r407_cache){
                            r407_no_memory_logged=true;
                            ESP_LOGW(TAG,"R407_NO_PSRAM record_anim_hold_only");
                        }
                    }
                    if(r407_cache && r407_cached<R407_RECORD_FRAMES &&
                       dec.frame_index==r407_cached+1u){
                        memcpy(r407_cache+(size_t)r407_cached*R407_FRAME_BYTES,
                               frame_rgb,R407_FRAME_BYTES);
                        // Only cached copied pixels are decorated; idle
                        // remains original m000 and recording remains SD-free.
                        r412_listen_render(r407_cache+
                               (size_t)r407_cached*R407_FRAME_BYTES,r407_cached);
                        r407_cached++;
                        r407_cache_copies++;
                        if(r407_cached==R407_RECORD_FRAMES){
#ifdef DF_R434_MAC_PREWAKE_ONLY
                            r435_wave_cache_ready=true;
#endif
                        }
                        if(r407_cached==R407_RECORD_FRAMES)
                            ESP_LOGI(TAG,"R412_LISTEN_WAVEFORM_16_READY bytes=%u",
                                     (unsigned)(R407_RECORD_FRAMES*R407_FRAME_BYTES));
                    }
                }
                // The descriptor and PSRAM pointer never change. LVGL 9.6
                // cache size is zero: setting the same source every frame
                // invalidates twice and repeats decoder/geometry work while
                // QSPI/voice compete. One invalidation below redraws pixels.
                if(r268_lan_busy && r296_trace.magic==R296_ANIM_TRACE_MAGIC){
                    // Sample 80 widely spaced RGB565 pixels; no private image
                    // content/CRC leaves the board, only change counts.
                    uint32_t hash=2166136261u;
                    const uint16_t *pixels=(const uint16_t *)frame_rgb;
                    for(size_t at=0;at<(size_t)SPRITE_W*SPRITE_W;at+=719u)
                        hash=(hash^(uint32_t)pixels[at])*16777619u;
                    if(r296_trace.frames && hash!=r296_trace.last_hash)
                        r296_trace.changed_frames++;
                    r296_trace.last_hash=hash;
                    r296_trace.frames++;
                }
#ifdef DF_H28_HOLD_MIC
                if(h29_display_motion_id!=h29_active_motion_id){
                    lv_image_set_scale(picture,h29_motion_scale(h29_active_motion_id));
                    h29_display_motion_id=h29_active_motion_id;
                }
#endif
                // Record geometry while holding the single LVGL lock.
                // User's "only feet" LCD photo could represent a hidden or
                // offscreen object despite a valid DFSP/USB frame receipt.
                r71_drawn_frames++;
                if(r268_lan_busy && r281_trace.magic==R281_DIAG_MAGIC)
                    r281_trace.avatar_frames_during_wifi++;
                if(r82_current_mode==2u)r82_static_enters++;
                if(!lv_obj_is_visible(picture))r71_hidden++;
                if(image_desc.data!=frame_rgb ||
                   image_desc.data_size!=(size_t)SPRITE_W*SPRITE_W*2u)
                    r71_bad_descriptor++;
                lv_area_t area={0};
                lv_obj_get_coords(picture,&area);
                r71_x1=area.x1;r71_x2=area.x2;
                r71_y1=area.y1;r71_y2=area.y2;
                if(area.x2<0||area.x1>=480||area.y2<0||area.y1>=480)
                    r71_offscreen++;
#ifdef DF_R33_BOARD_UI
                if(r57_page==0 && r57_root!=NULL)r71_overlay_conflict++;
#endif
                lv_obj_invalidate(picture);
#ifdef DF_R434_MAC_PREWAKE_ONLY
                if(h12_use_sd && h29_active_motion_id==30u &&
                   r47_audio_motion==2u && dec.frame_index==1u)
                    r435_mouth_first_frame_ready=true;
#endif
            }
            esp_lv_adapter_unlock();
            r222_draw_done_us=esp_timer_get_time();
#ifdef DF_H28_HOLD_MIC
            if(dec.frame_index==1 && h28_local_frame_kind){
                if(h28_local_frame_kind==1 && h30_touch_requested_at){
                    uint32_t elapsed=(uint32_t)(xTaskGetTickCount()-h30_touch_requested_at);
                    ESP_LOGI(TAG,"H30_TOUCH_TO_FRAME_MS %lu",(unsigned long)(elapsed*portTICK_PERIOD_MS));
                    h30_touch_requested_at=0;
                    /* No temporary blue square around the character. */
                }
                char local_receipt[75];
                const unsigned kind=h28_local_frame_kind;
                const unsigned id=h28_local_frame_id;
                int n=snprintf(local_receipt,sizeof(local_receipt),
                    "@@DF%s1 APPLIED id=m%03u frame=1\n",
                    kind==1?"TOUCH":"IDLE",id);
                if(n>0 && n<(int)sizeof(local_receipt) &&
                   h9_send_line(local_receipt,(size_t)n)){
                    h28_local_frame_kind=0;
                }
            }
#endif
            if(dec.frame_index==1)ESP_LOGI(TAG,"AVATAR_FRAME_READY native240 watermark=%u",
                (unsigned)uxTaskGetStackHighWaterMark(NULL));
#ifdef DF_H12_SD_ANIM
            if(dec.frame_index==1 && h12_actual_seq){
                char applied[96];
                int n=snprintf(applied,sizeof(applied),
                   "@@DFMOTION1 APPLIED seq=%lu id=m%03u frame=1\n",
                   (unsigned long)h12_actual_seq,h12_actual_id);
                h12_rendered_seq=h12_actual_seq;
                h12_rendered_id=h12_actual_id;
                if(n>0 && n<(int)sizeof(applied))
                    (void)h9_send_line(applied,(size_t)n);
                h12_actual_seq=0;
            }
#endif
        }
        if(rc==DFSP_OK && !r222_lock_acquired_us)r322_anim_hold=6;
        if(rc==DFSP_OK){
            const int64_t r222_frame_end_us=esp_timer_get_time();
            const uint32_t r222_total_us=(uint32_t)(r222_frame_end_us-r222_frame_begin_us);
            const uint32_t r222_load_us=(uint32_t)(r222_decode_begin_us-r222_frame_begin_us);
            const uint32_t r222_decode_us=(uint32_t)(r222_decode_done_us-r222_decode_begin_us);
            const uint32_t r222_wait_us=r222_lock_acquired_us
               ? (uint32_t)(r222_lock_acquired_us-r222_lock_begin_us) : 0;
            const uint32_t r222_draw_us=r222_draw_done_us
               ? (uint32_t)(r222_draw_done_us-r222_lock_acquired_us) : 0;
            // A cheap 8-frame moving average makes decode-vs-draw
            // bottlenecks visible through one read-only physical receipt.
            // Initial slow SD handoff samples age out; no periodic UART spam.
            if(!r510_perf_frames){
                r510_avg_load_us=r222_load_us;
                r510_avg_decode_us=r222_decode_us;
                r510_avg_lock_us=r222_wait_us;
                r510_avg_draw_us=r222_draw_us;
            }else{
                r510_avg_load_us=(7u*r510_avg_load_us+r222_load_us+4u)/8u;
                r510_avg_decode_us=(7u*r510_avg_decode_us+r222_decode_us+4u)/8u;
                r510_avg_lock_us=(7u*r510_avg_lock_us+r222_wait_us+4u)/8u;
                r510_avg_draw_us=(7u*r510_avg_draw_us+r222_draw_us+4u)/8u;
            }
            r510_perf_frames++;
            // Up to 4 initial slow warnings, then one per 64 slow frames.
            // Do not flood UART and accidentally create new slow frames.
            if(r222_total_us>=160000u){
                r222_slow_samples++;
                if(r222_slow_samples<=4u || r222_slow_samples%64u==0u)
                    ESP_LOGW(TAG,
                      "R222_FRAME_PROFILE total_us=%lu load_us=%lu decode_us=%lu lock_us=%lu draw_us=%lu slow=%lu",
                      (unsigned long)r222_total_us,(unsigned long)r222_load_us,
                      (unsigned long)r222_decode_us,(unsigned long)r222_wait_us,
                      (unsigned long)r222_draw_us,(unsigned long)r222_slow_samples);
            }
            TickType_t now=xTaskGetTickCount();
            uint32_t cost=(uint32_t)(now-r70_frame_start)*portTICK_PERIOD_MS;
            r70_frame_last_ms=cost;
            if(cost>r70_frame_max_ms)r70_frame_max_ms=cost;
            if(cost>125)r70_frame_long++;
            if(r70_last_frame_tick){
                uint32_t gap=(uint32_t)(now-r70_last_frame_tick)*portTICK_PERIOD_MS;
                if(gap>r70_gap_max_ms)r70_gap_max_ms=gap;
            }
            r70_last_frame_tick=now;
            r70_frames++;
        }
        // R121: Loading a newly SHA-approved SD sprite can cost >1.6 s.
        // vTaskDelayUntil() otherwise repays EVERY missed 125 ms interval
        // immediately, running many frames back-to-back at priority 4 and
        // starving the LVGL/touch task. Drop stale scheduler debt without
        // dropping an animation or relaxing the SHA verification contract.
        const TickType_t frame_period=pdMS_TO_TICKS(125);
        TickType_t now_tick=xTaskGetTickCount();
        TickType_t late=(TickType_t)(now_tick-tick);
        if(late>2u*frame_period){
            static unsigned skipped_debt=0;
            skipped_debt++;
            if(skipped_debt<=4 || (skipped_debt%32u)==0u)
                ESP_LOGW(TAG,"R121_FRAME_DEBT_RESYNC count=%u lag_ms=%lu",
                    skipped_debt,(unsigned long)(late*portTICK_PERIOD_MS));
            tick=now_tick;
        }
        vTaskDelayUntil(&tick,frame_period);
    }
    vTaskDelete(NULL);
}
static void voice_worker(void *unused){
    (void)unused;
    uint32_t local_lease=0;
#ifdef DF_R185_WN9
    if(!r185_wake_wait_released(2300))goto done;
#endif
    if(!r224_audio_claim(R224_MEDIA_LOCAL_CLIP,&local_lease))goto done;
    const uint8_t *pcm;
    size_t n;
    if(!sample_asset(&pcm,&n)){
        ESP_LOGE(TAG,"VOICE_ASSET_INVALID");ui_status("Voice file failed");goto done;
    }
    if(!speaker)speaker=bsp_audio_codec_speaker_init();
    if(!speaker){
        ESP_LOGE(TAG,"VOICE_CODEC_INIT_FAIL");ui_status("Speaker unavailable");goto done;
    }
    esp_codec_dev_sample_info_t info={.sample_rate=RATE,.channel=1,.bits_per_sample=16};
    if(esp_codec_dev_open(speaker,&info)!=ESP_CODEC_DEV_OK){
        ESP_LOGE(TAG,"VOICE_CODEC_OPEN_FAIL");ui_status("Voice codec error");goto done;
    }
    uint8_t vol=volume;
    if(esp_codec_dev_set_out_vol(speaker,vol)!=ESP_CODEC_DEV_OK){
        ESP_LOGE(TAG,"VOICE_SET_VOLUME_FAIL");esp_codec_dev_close(speaker);goto done;
    }
    ESP_LOGI(TAG,"VOICE_PLAY_BEGIN samples=%u volume=%u limit=%u",
             (unsigned)n,vol,MAX_PEAK);
    ui_status("Speaking: local Qwen3 sample");
    bool ok=true;
    for(size_t offset=0;offset<n;offset+=480){
        int16_t block[480]={0};
        size_t count=n-offset;if(count>480)count=480;
        for(size_t i=0;i<count;i++){
            size_t b=(offset+i)*2u;
            int16_t s=(int16_t)((uint16_t)pcm[b]|((uint16_t)pcm[b+1u]<<8));
            block[i]=h10_soft_peak(s,(uint32_t)(offset+i),(uint32_t)n);
        }
        if(esp_codec_dev_write(speaker,block,sizeof(block))!=ESP_CODEC_DEV_OK){
            ok=false;break;
        }
    }
    esp_codec_dev_close(speaker);
    if(ok){
        ESP_LOGI(TAG,"VOICE_PCM_WRITTEN samples=%u vol=%u needs_human_listen",
                 (unsigned)n,vol);
        ui_status("Finished - tap VOICE to replay");
        // No surprise 90->95->100 escalation; user heard distorted followups.
    }else{
        ESP_LOGE(TAG,"VOICE_WRITE_FAILED");
        ui_status("Playback failed");
    }
done:
    if(local_lease)r224_audio_release(R224_MEDIA_LOCAL_CLIP,local_lease);
    speaking=false;
#ifdef DF_R185_WN9
    r185_wake_resume();
#endif
    vTaskDelete(NULL);
}

static void h10_dynamic_voice_worker(void *unused){
    (void)unused;
    int16_t *owned=h10_dynamic_pcm;
    uint32_t n=h10_expected;
    h10_dynamic_pcm=NULL;
    bool opened=false,ok=false;
    uint32_t pcm1_lease=0;
#ifdef DF_R185_WN9
    if(!r185_wake_wait_released(2300))goto done;
#endif
    if(!r224_audio_claim(R224_MEDIA_PCM1,&pcm1_lease))goto done;
    if(!owned || n==0){ESP_LOGE(TAG,"H10_DYN_INVALID");goto done;}
    if(!speaker)speaker=bsp_audio_codec_speaker_init();
    if(!speaker){ESP_LOGE(TAG,"H10_DYN_CODEC_MISSING");goto done;}
    esp_codec_dev_sample_info_t info={.sample_rate=RATE,.channel=1,.bits_per_sample=16};
    if(esp_codec_dev_open(speaker,&info)!=ESP_CODEC_DEV_OK){
        ESP_LOGE(TAG,"H10_DYN_CODEC_OPEN_FAIL");goto done;
    }
    opened=true;
    #ifdef DF_R33_BOARD_UI
    if(esp_codec_dev_set_out_vol(speaker,volume)!=ESP_CODEC_DEV_OK){
#else
    if(esp_codec_dev_set_out_vol(speaker,FIRST_VOL)!=ESP_CODEC_DEV_OK){
#endif
        ESP_LOGE(TAG,"H10_DYN_CODEC_VOLUME_FAIL");goto done;
    }
    // Only report playback start AFTER the first PCM block really reached
    // the codec; TTS-ready or pre-upload MUST NOT activate speaking lips.
    ui_status("Speaking: verified Mac reply");
    ok=true;
    for(uint32_t k=0;k<n;k+=480){
        if(r51_stop_requested){ok=false;break;}
        int16_t block[480]={0};
        uint32_t count=n-k;if(count>480)count=480;
        for(uint32_t j=0;j<count;j++)
            block[j]=h10_soft_peak(owned[k+j],k+j,n);
        if(esp_codec_dev_write(speaker,block,sizeof(block))!=ESP_CODEC_DEV_OK){
            ok=false;break;
        }
        if(k==0)ESP_LOGI(TAG,"H10_DYNAMIC_PLAY_BEGIN samples=%u vol=%u",(unsigned)n,FIRST_VOL);
    }
done:
    if(opened)esp_codec_dev_close(speaker);
    if(pcm1_lease)r224_audio_release(R224_MEDIA_PCM1,pcm1_lease);
    if(owned)heap_caps_free(owned);
    h10_expected=0;h10_received=0;h10_seq=0;
    // The Mac may send its next segment immediately upon PCM_WRITTEN.
    // Clear busy BEFORE publishing that receipt; old H10 did the reverse,
    // allowing a fast second BEGIN to be rejected as still speaking.
    speaking=false;
#ifdef DF_R185_WN9
    r185_wake_resume();
#endif
    if(r51_stop_requested){
        static const char stopped[]="@@DFPCM1 USER_STOPPED\n";
        (void)h9_send_line(stopped,sizeof(stopped)-1);
        r51_stop_requested=false;
    }else if(ok)ESP_LOGI(TAG,"H10_DYNAMIC_PCM_WRITTEN");
    else ESP_LOGE(TAG,"H10_DYNAMIC_WRITE_FAILED");
    ui_status(ok?"Reply played":"Reply playback error");
    vTaskDelete(NULL);
}
static void h10_dynamic_command(char *line){
    if(strcmp(line,"@@DFPCM1 VERSION")==0){
        static const char version[]="@@DFPCM1 VERSION=1 H10\n";
        (void)h9_send_line(version,sizeof(version)-1);
        return;
    }
    if(strcmp(line,"@@DFPCM1 CANCEL")==0){
        if(h10_receiving)h10_dynamic_cancel();
        static const char answer[]="@@DFPCM1 CANCELLED\n";
        (void)h9_send_line(answer,sizeof(answer)-1);
        return;
    }
    if(strncmp(line,"@@DFPCM1 BEGIN samples=",23)==0){
        unsigned total=0;char garbage=0;
        if(sscanf(line,"@@DFPCM1 BEGIN samples=%u%c",&total,&garbage)!=1 ||
           !total || total>H10_MAX_REPLY_SAMPLES ||
           speaking || capturing || loopback_busy || h10_receiving){
            static const char bad[]="@@DFPCM1 NACK begin\n";
            (void)h9_send_line(bad,sizeof(bad)-1);return;
        }
        int16_t *mem=heap_caps_malloc(total*2u,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
        if(!mem){
            static const char bad[]="@@DFPCM1 NACK memory\n";
            (void)h9_send_line(bad,sizeof(bad)-1);return;
        }
        h10_dynamic_pcm=mem;
        h10_expected=total;h10_received=0;h10_seq=0;h10_receiving=true;
        h10_rx_deadline=xTaskGetTickCount()+pdMS_TO_TICKS(45*1000);
        static const char ack[]="@@DFPCM1 READY\n";
        (void)h9_send_line(ack,sizeof(ack)-1);
        return;
    }
    if(!h10_receiving)return;
    if(strncmp(line,"@@DFPCM1 CHUNK ",15)==0){
        unsigned number=0;int consumed=0;
        if(sscanf(line,"@@DFPCM1 CHUNK %u %n",&number,&consumed)!=1 ||
           consumed<=0 || number!=h10_seq){
            h10_dynamic_cancel();
            static const char nack[]="@@DFPCM1 NACK sequence\n";
            (void)h9_send_line(nack,sizeof(nack)-1);return;
        }
        const char *data=line+consumed;
        size_t got=0;
        uint8_t pcm[H10_CHUNK_BYTES]={0};
        size_t encoded=strlen(data);
        if(encoded<4 || encoded>2600 ||
           mbedtls_base64_decode(pcm,sizeof(pcm),&got,(const unsigned char *)data,encoded)!=0 ||
           !got || got%2 || got>H10_CHUNK_BYTES ||
           h10_received+got/2>h10_expected){
            h10_dynamic_cancel();
            static const char nack[]="@@DFPCM1 NACK audio\n";
            (void)h9_send_line(nack,sizeof(nack)-1);return;
        }
        memcpy(h10_dynamic_pcm+h10_received,pcm,got);
        h10_received+=(uint32_t)(got/2);
        h10_seq++;
        h10_rx_deadline=xTaskGetTickCount()+pdMS_TO_TICKS(45*1000);
        char ack[64];
        int len=snprintf(ack,sizeof(ack),"@@DFPCM1 ACK %u\n",number);
        if(len>0)(void)h9_send_line(ack,(size_t)len);
        return;
    }
    if(strcmp(line,"@@DFPCM1 END")==0 && h10_received==h10_expected){
        h10_receiving=false;
        speaking=true;
        static const char ack[]="@@DFPCM1 RECEIVED\n";
        (void)h9_send_line(ack,sizeof(ack)-1);
        if(xTaskCreate(h10_dynamic_voice_worker,"h10_play",VOICE_TASK_STACK_BYTES,
                       NULL,5,NULL)!=pdPASS){
            speaking=false;h10_dynamic_cancel();
            ESP_LOGE(TAG,"H10_DYN_TASK_FAILED");
        }
        return;
    }
    h10_dynamic_cancel();
    static const char nack[]="@@DFPCM1 NACK incomplete\n";
    (void)h9_send_line(nack,sizeof(nack)-1);
}
static void h9_usb_loopback(void *unused){
    (void)unused;
    // No ambient mic capture, no model, no audio output, no personal data.
    // Deterministic 150-frame transport challenge, exclusively on host request.
    static const char BEGIN[]="@@DFVOICE1 TEST_BEGIN frames=150\n";
    static const char END[]="@@DFVOICE1 TEST_END frames=150\n";
    bool ok=h9_send_line(BEGIN,sizeof(BEGIN)-1);
    for(unsigned i=0;ok && i<MIC_FRAMES;i++){
        int16_t sample[MIC_BLOCK];
        for(unsigned j=0;j<MIC_BLOCK;j++)sample[j]=(int16_t)(i*7u+j);
        ok=h9_send_audio_frame(i,sample,true,MIC_BLOCK);
    }
    if(ok)ok=h9_send_line(END,sizeof(END)-1);
    if(!ok)ESP_LOGE(TAG,"H9_USB_TRANSPORT_LOOPBACK_FAILED");
    else ESP_LOGI(TAG,"H9_USB_TRANSPORT_LOOPBACK_DONE frames=%u",MIC_FRAMES);
    loopback_busy=false;
    vTaskDelete(NULL);
}
// Privacy: only a real long-press captures exactly three seconds. No passive
// microphone, no persistent PCM, no memory harvesting, no Wi-Fi, no paid calls.
// Host must be connected to the authorized USB port and must opt into capture.
// R268: one native Wi-Fi worker owns WSS+MIC+DAC in sequence.
// No Mac USB voice process, offline MN5 engine, SD or animation is rewritten.
static bool r268_audio_stop(void *unused){
    (void)unused;
    return r51_stop_requested ||
        (r268_current_phase==R268_LAN_LISTENING&&r268_lan_touch_finish);
}
static void r268_audio_phase(void *unused,r268_lan_phase_t next){
    (void)unused;
    if(next==R268_LAN_ERROR)
        r298_lan_cancelled=r51_stop_requested;
    r268_current_phase=next;
    if(r281_trace.magic==R281_DIAG_MAGIC)
        r281_trace.voice_phase_events++;
    capturing=next==R268_LAN_LISTENING;
#ifdef DF_R434_MAC_PREWAKE_ONLY
    // Preserve continuous cached frames when switching to real microphone:
    // set capturing first, then release the greeting visual override.
    if(next==R268_LAN_LISTENING){
        r436_wake_ack_wave_active=false;
        ESP_LOGI(TAG,"R436_ACK_TO_LISTEN_WAVE_CONTINUOUS");
    }
#endif
    speaking=next==R268_LAN_SPEAKING;
    if(next!=R268_LAN_LISTENING)r268_lan_touch_finish=false;
    // The WSS worker updates only two simple integers; LVGL draws shortly
    // after without a 1000ms mutex acquisition or UI thread starvation.
    r279_lan_ui_phase=next;
    r279_lan_ui_seq++;
}
static void r268_lan_voice_worker(void *arg){
    const bool wake=(uintptr_t)arg==1u;
    r268_lan_auto_wake=wake;
    r281_begin_trace();
    // WLAN TLS handshake needs contiguous internal memory that the idle
    // WakeNet AFE still occupies. Hand off the shared codec BEFORE WSS.
#ifdef DF_R185_WN9
    if(!r185_wake_wait_released(2300)){
        ui_status("无线语音：麦克风资源未释放");
        r268_lan_auto_wake=false;
        capturing=false;speaking=false;r268_lan_busy=false;
        r268_current_phase=R268_LAN_IDLE;
        r185_wake_resume();vTaskDelete(NULL);return;
    }
#endif
    const r268_lan_codec_t bridge={
       .ctx=NULL,.mic_open=r268_audio_mic_open,.mic_read=r268_audio_mic_read,
       .mic_close=r268_audio_mic_close,.speaker_open=r268_audio_speaker_open,
       .speaker_write=r268_audio_speaker_write,.speaker_close=r268_audio_speaker_close,
       .stop_requested=r268_audio_stop,.phase=r268_audio_phase
    };
    (void)r268_lan_run(&bridge,wake);
    capturing=false;speaking=false;r268_lan_touch_finish=false;
    r268_lan_auto_wake=false;
    r268_lan_busy=false;r268_current_phase=R268_LAN_IDLE;
    r51_stop_requested=false;
#ifdef DF_R185_WN9
    r185_wake_resume();
#endif
    vTaskDelete(NULL);
}
static bool r268_lan_available(void){
    r62_wifi_state_t wifi={0};r62_wifi_snapshot(&wifi);
    // Touch must never block on NVS/flash reads. Cached bit is updated
    // only from a verified boot-time pairing or explicit physical USB pair.
    // Real TLS authentication/peer NVS read is still enforced in LAN worker.
    return !r268_usb_host_alive()&&wifi.has_ip&&r276_lan_paired_cached;
}
static bool r268_lan_start(bool wake){
    r276_lan_start_error=0;
    if(r268_lan_busy||capturing||speaking||h10_receiving||r37_pcm2_active||
       r83_transfer_active()||!r268_lan_available()){
        r276_lan_start_error=1;return false;
    }
    // R276 hard preflight: physical R273 after DHCP had only 12,288 bytes
    // contiguous internal heap, less than the 14KiB FreeRTOS WSS stack.
    // Never launch half a TLS worker that starves the LVGL frame/USB path.
    // The 24KiB animation stack was calibrated against a 78s on-board
    // minimum high-water receipt of 20,444 free bytes at the old 32KiB size.
    const size_t free_internal=heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT);
    const size_t largest=heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT);
    if(free_internal<42*1024 || largest<18*1024){
        r276_lan_start_error=2;
        ESP_LOGW(TAG,"R276_LAN_PREFLIGHT_MEMORY free=%lu largest=%lu",
                 (unsigned long)free_internal,(unsigned long)largest);
        return false;
    }
    r268_lan_busy=true;r268_lan_touch_finish=false;r51_stop_requested=false;
    r268_lan_auto_wake=wake;
    r303_wss_audio_offered=false;
    r298_lan_cancelled=false;
    // Equal priority with animation/WN9: TLS crypto must not monopolize UI.
    if(xTaskCreate(r268_lan_voice_worker,"r268_wss_voice",
                   14*1024,(void*)(uintptr_t)(wake?1:0),4,NULL)!=pdPASS){
        r276_lan_start_error=3;r268_lan_busy=false;r268_lan_auto_wake=false;
        ESP_LOGW(TAG,"R276_LAN_TASK_CREATE_FAILED free=%lu largest=%lu",
                 (unsigned long)free_internal,(unsigned long)largest);
        return false;
    }
    return true;
}

#ifdef DF_R434_MAC_PREWAKE_ONLY
/* R435: reuse the embedded 1.6s "我在呢" asset after Mac KWS auth.
 * This is the same fixed local clip that the original wake worker can fall
 * back to, with the original single codec owner; no SD or DSH is involved.
 * The Mac one-use wake ticket is valid for 12s, so never retry this clip.
 */
static bool r435_embedded_wake_ack(void){
#ifndef DF_R185_WN9
    return false;
#else
    const uint8_t *wav=r185_greeting_start;
    size_t n=(size_t)(r185_greeting_end-r185_greeting_start);
    if(n<=44u || n>=100000u || memcmp(wav,"RIFF",4)!=0 ||
       memcmp(wav+8,"WAVE",4)!=0 || memcmp(wav+36,"data",4)!=0 ||
       wav[20]!=1 || wav[22]!=1 || wav[24]!=0xC0 || wav[25]!=0x5D ||
       wav[34]!=16 || ((n-44u)%2u)!=0)return false;
    uint32_t lease=0;
    if(!r224_audio_claim(R224_MEDIA_LOCAL_CLIP,&lease))return false;
    bool done=false,opened=false;
    if(!speaker)speaker=bsp_audio_codec_speaker_init();
    if(speaker){
        esp_codec_dev_sample_info_t fmt={.sample_rate=24000,.channel=1,.bits_per_sample=16};
        if(esp_codec_dev_open(speaker,&fmt)==ESP_CODEC_DEV_OK){
            opened=true;
            if(esp_codec_dev_set_out_vol(speaker,volume>80?80:volume)==ESP_CODEC_DEV_OK){
                // R436: first visual frame precedes the first local greeting
                // PCM write, bounded at 250 ms to protect the 12s wake ticket.
                r436_wake_ack_first_frame_ready=false;
                // If the boot cache missed its 8-second warm-up, play the
                // greeting normally instead of freezing the idle artwork.
                if(r435_wave_cache_ready){
                    r436_wake_ack_wave_active=true;
                    for(unsigned warm=0;warm<10u &&
                        !r436_wake_ack_first_frame_ready;warm++)
                        vTaskDelay(pdMS_TO_TICKS(25));
                    ESP_LOGI(TAG,"R436_ACK_WAVE_PREFRAME ready=%u",
                             (unsigned)r436_wake_ack_first_frame_ready);
                }else{
                    ESP_LOGW(TAG,"R436_ACK_WAVE_SKIP_CACHE_NOT_READY");
                }
                size_t total=(n-44u)/2u;
                done=true;
                for(size_t at=0;at<total;at+=480u){
                    int16_t block[480]={0};
                    for(size_t i=0;i<480u && at+i<total;i++){
                        size_t x=44u+(at+i)*2u;
                        block[i]=(int16_t)((unsigned)wav[x]|((unsigned)wav[x+1]<<8));
                    }
                    if(esp_codec_dev_write(speaker,block,sizeof(block))!=ESP_CODEC_DEV_OK){
                        done=false;break;
                    }
                }
            }
        }
    }
    if(opened && esp_codec_dev_close(speaker)!=ESP_CODEC_DEV_OK)done=false;
    r224_audio_release(R224_MEDIA_LOCAL_CLIP,lease);
    if(!done)r436_wake_ack_wave_active=false;
    ESP_LOGI(TAG,"R435_AUTH_WAKE_ACK_PLAYED ok=%u",(unsigned)done);
    return done;
#endif
}
// The greeting plays with the existing local codec lease, *after* Mac
// WSS capture START ACK and *before* the one microphone is claimed.
static bool r441_wake_ack_after_start(void *ctx){
    (void)ctx;return r435_embedded_wake_ack();
}
/* Only a single R268 codec & WSS worker exists at a time. No MN5 AFE
 * model task is created. Listen on trusted Wi-Fi, then use the original
 * R268 authenticated full duplex voice worker for ASR/DSH/TTS.
 * Physical touch preempts prewake and retains the original v2 touch path.
 */
static void r434_mac_prewake_worker(void *unused){
 (void)unused;
 const r268_lan_codec_t bridge={
  .ctx=NULL,.mic_open=r268_audio_mic_open,.mic_read=r268_audio_mic_read,
  .mic_close=r268_audio_mic_close,.speaker_open=r268_audio_speaker_open,
  .speaker_write=r268_audio_speaker_write,.speaker_close=r268_audio_speaker_close,
  .wake_ack=r441_wake_ack_after_start,
  .stop_requested=r268_audio_stop,.phase=r268_audio_phase
 };
 // Warm the R412 waveform using real idle SD frames before the continuous
 // WSS microphone lease. Bound the wait; no extra microphone/SD reader.
 for(unsigned warm=0;warm<320u && !r435_wave_cache_ready;warm++)
     vTaskDelay(pdMS_TO_TICKS(25));
 ESP_LOGI(TAG,"R435_WAVE_CACHE_PREFLIGHT ready=%u",
          (unsigned)r435_wave_cache_ready);
 for(;;){
  if(!r268_lan_busy&&!capturing&&!speaking&&!h10_receiving&&
      !r37_pcm2_active&&!r83_transfer_active()&&r268_lan_available()){
   size_t free_internal=heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT);
   size_t largest=heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT);
   if(free_internal>=42*1024&&largest>=18*1024){
    r268_lan_busy=true;r434_prewake_active=true;
    r51_stop_requested=false;r434_touch_pending=false;
    bool hit=r268_lan_prewake_listen(&bridge);
    r434_prewake_active=false;
    bool touch=r434_touch_pending;
    r434_touch_pending=false;
    r51_stop_requested=false;
    if(hit){
     r268_lan_auto_wake=true;
     // R441: Preserve the 650ms *prewake owner release* before new TLS,
     // so the Mac does not reject a still-busy KWS connection. Unlike
     // R436 this occurs BEFORE "我在呢": authenticated listening START
     // ACK precedes the greeting, followed immediately by mic_open.
     // Speech after hearing the greeting no longer falls into a blind
     // 650ms delay + WSS handshake. Keep one codec / one DSH owner.
     vTaskDelay(pdMS_TO_TICKS(650));
     (void)r268_lan_run(&bridge,true);
     // No waveform is left latched across completed or failed voice turns.
     r436_wake_ack_wave_active=false;
     r436_wake_ack_first_frame_ready=false;
    }else if(touch){
     r268_lan_auto_wake=false;
     (void)r268_lan_run(&bridge,false);
    }
    capturing=false;speaking=false;r268_lan_touch_finish=false;
    r268_lan_auto_wake=false;
    r268_lan_busy=false;r268_current_phase=R268_LAN_IDLE;
    r51_stop_requested=false;
   }
  }
  vTaskDelay(pdMS_TO_TICKS(850));
 }
}
#endif
static void mic_worker(void *unused){
    (void)unused;
    uint32_t mic_lease=0;
#ifdef DF_R185_WN9
    const bool physical_auto_r251=r185_auto_capture;
    if(physical_auto_r251)r251_wake_mark(500);
#endif
#ifdef DF_R185_WN9
    if(!r185_wake_wait_released(1800)){
        ESP_LOGE(TAG,"R185_MIC_HANDOFF_FAILED_PRESERVE_TOUCH");
        static const char cancel[]="@@DFVOICE3 CANCEL\n";
        (void)h9_send_line(cancel,sizeof(cancel)-1);
        capturing=false;h28_mic_press_session=false;
        h28_mic_button_pressed=false;
        r185_auto_capture=false;
        vTaskDelete(NULL);return;
    }
#endif
    if(speaking){
        capturing=false;
#ifdef DF_H28_HOLD_MIC
        h28_mic_press_session=false;h28_mic_button_pressed=false;
#endif
        vTaskDelete(NULL);return;
    }
    if(!r224_audio_claim(R224_MEDIA_CAPTURE,&mic_lease)){
        ESP_LOGW(TAG,"R229_MIC_AUDIO_OWNER_BUSY");
        static const char cancel[]="@@DFVOICE3 CANCEL\n";
        (void)h9_send_line(cancel,sizeof(cancel)-1);
        goto end;
    }
    ESP_LOGI(TAG,"H8_MIC_INIT_BEGIN free_internal=%u free_psram=%u stack=%u",
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM),
             (unsigned)uxTaskGetStackHighWaterMark(NULL));
    if(!microphone)microphone=r248_microphone_init_with_gain();
    if(!microphone){ESP_LOGE(TAG,"H7_MIC_INIT_FAILED");goto end;}
    esp_codec_dev_sample_info_t format={
        .sample_rate=MIC_RATE,.channel=1,.bits_per_sample=16,
    };
#ifdef DF_R185_WN9
    // The SD/ES8311 greeting has just finished; let I2S output settle
    // before opening the single board microphone, avoiding wake-word echo.
    if(r185_auto_capture)vTaskDelay(pdMS_TO_TICKS(350));
#endif
#ifdef DF_R185_WN9
    if(physical_auto_r251)r251_wake_mark(501);
#endif
    if(esp_codec_dev_open(microphone,&format)!=ESP_CODEC_DEV_OK){
        ESP_LOGE(TAG,"H7_MIC_OPEN_FAILED");goto end;
    }
    ESP_LOGI(TAG,"H8_MIC_CODEC_READY 16000hz single_channel");
#ifdef DF_R30_TOGGLE_MIC
    ui_status("Recording... tap STOP to send");
#else
    ui_status("Listening / release to send");
#endif
#ifdef DF_H28_HOLD_MIC
    // Board emits no PCM until a true press, not a Mac or DSH text event.
    if(!h28_mic_press_session){
        esp_codec_dev_close(microphone);
        ESP_LOGI(TAG,"H28_MIC_TOUCH_RELEASED_BEFORE_READY");
        goto end;
    }
    static const char BEGIN_MSG[]="@@DFVOICE3 BEGIN rate=16000 max_frames=1000\n";
#else
    static const char BEGIN_MSG[]="@@DFVOICE1 BEGIN rate=16000 samples=48000\n";
#endif
#ifdef DF_R185_WN9
    if(physical_auto_r251)r251_wake_mark(502);
#endif
    if(!h9_send_line(BEGIN_MSG,sizeof(BEGIN_MSG)-1)){
        ESP_LOGE(TAG,"H9_PCM_BEGIN_TX_FAILED");esp_codec_dev_close(microphone);goto end;
    }
    bool ok=true;
    unsigned captured=0;
#ifdef DF_H28_HOLD_MIC
    unsigned limit=MIC_HOLD_MAX_FRAMES;
#else
    unsigned limit=MIC_FRAMES;
#endif
    unsigned frames=0;
#ifdef DF_R185_WN9
    bool wake_heard=false;unsigned wake_silent=0;
#endif
    for(;frames<limit;frames++){
#ifdef DF_H28_HOLD_MIC
        // Release ends capture at the next 20ms packet boundary.
        if(!h28_mic_button_pressed)break;
#endif
        int16_t samples[MIC_BLOCK]={0};
        if(esp_codec_dev_read(microphone,samples,sizeof(samples))!=ESP_CODEC_DEV_OK ||
#ifdef DF_H28_HOLD_MIC
           !h28_send_mic_frame(frames,samples,MIC_BLOCK)){
#else
           !h9_send_audio_frame(frames,samples,false,MIC_BLOCK)){
#endif
            ok=false;break;
        }
        captured+=MIC_BLOCK;
#ifdef DF_R185_WN9
        if(r185_auto_capture){
            uint32_t absmean=0;
            for(unsigned j=0;j<MIC_BLOCK;j++){
                int sample=samples[j];if(sample<0)sample=-sample;
                absmean+=(uint32_t)sample;
            }
            if(absmean/MIC_BLOCK>180u){wake_heard=true;wake_silent=0;}
            else if(wake_heard)wake_silent++;
            if(r237_should_close_wake(wake_heard,frames+1,wake_silent))
                h28_mic_button_pressed=false;
        }
#endif
        if(frames==0 || frames%250==249)
            ESP_LOGI(TAG,"H28_OR_H8_MIC_CAPTURE_PROGRESS frames=%u samples=%u",frames+1,captured);
    }
    esp_codec_dev_close(microphone);
#ifdef DF_R185_WN9
    // If the microphone never detected even rudimentary speech energy,
    // CANCEL instead of forwarding 10s of silence into Whisper/DSH.
    if(r185_auto_capture && !wake_heard){
        ESP_LOGI(TAG,"R237_WAKE_NO_SPEECH_CANCEL frames=%u",frames);
        ok=false;
    }
#endif
#ifdef DF_H28_HOLD_MIC
    if(ok && frames>=MIC_HOLD_MIN_FRAMES && captured==frames*MIC_BLOCK){
        char end_msg[116];
        int n=snprintf(end_msg,sizeof(end_msg),
                "@@DFVOICE3 END frames=%u samples=%u reason=%s\n",
                frames,captured,frames==limit?"limit":
#ifdef DF_R30_TOGGLE_MIC
                "toggled"
#else
                "released"
#endif
                );
        if(n>0&&n<(int)sizeof(end_msg)&&h9_send_line(end_msg,(size_t)n)){
            ESP_LOGI(TAG,"H28_MIC_RELEASED_USB_OK frames=%u",frames);
            ui_status("Sent to Mac / processing");
        }else{ESP_LOGE(TAG,"H28_MIC_END_TX_FAILED");ui_status("Mic USB failed");}
    }else{
        static const char cancelled[]="@@DFVOICE3 CANCEL\n";
        (void)h9_send_line(cancelled,sizeof(cancelled)-1);
        ESP_LOGW(TAG,"H28_MIC_CANCEL short_or_failed frames=%u",frames);
        ui_status("Hold mic and speak");
    }
    h28_mic_press_session=false;
#ifdef DF_R185_WN9
    r185_auto_capture=false;
#endif
#else
    if(ok && captured==MIC_FRAMES*MIC_BLOCK){
        static const char END_MSG[]="@@DFVOICE1 END samples=48000\n";
        if(!h9_send_line(END_MSG,sizeof(END_MSG)-1))
            ESP_LOGE(TAG,"H9_MIC_END_TX_FAILED");
        else ESP_LOGI(TAG,"H9_MIC_SENT samples=%u (private USB, host decides STT)",captured);
        ui_status("Voice sent / waiting Mac");
    }else{
        static const char FAIL_MSG[]="@@DFVOICE1 FAIL\n";
        (void)h9_send_line(FAIL_MSG,sizeof(FAIL_MSG)-1);
        ESP_LOGE(TAG,"H8_MIC_FAILED samples=%u",captured);
        ui_status("Microphone capture error");
    }
#endif

end:
    if(mic_lease)r224_audio_release(R224_MEDIA_CAPTURE,mic_lease);
#ifdef DF_H28_HOLD_MIC
    h28_mic_press_session=false;
    h28_mic_button_pressed=false;
#endif
    capturing=false;
#ifdef DF_R185_WN9
    r185_auto_capture=false;
    r185_wake_resume();
    if(physical_auto_r251)r251_wake_mark(899);
#endif
#ifdef DF_R33_BOARD_UI
    r36_record_begin_tick=0;
#endif
    vTaskDelete(NULL);
}
#ifdef DF_H28_HOLD_MIC
#ifdef DF_R185_WN9
#ifdef DF_R225_LOCAL_OFFLINE
static bool r225_audio_owner(void){
 return speaking && !r51_stop_requested && !capturing && !h10_receiving && !r37_pcm2_active
     && !loopback_busy && !r225_voice_upload_active();
}
#endif
// Dedicated WakeNet9 model is "Hi 乐鑫" ONLY, not the user's
// intended "嘿，你好大肥鱼"; do not imply an untrained keyword works.
static bool r185_can_listen(void){
    bool idle=!capturing && !speaking && !h10_receiving && !loopback_busy
        && !r37_pcm2_active && !h28_mic_press_session
        && !r83_transfer_active();
#ifdef DF_H11_PREVIEW_STATES
    idle=idle && strcmp(h11_current_state.phase,"idle")==0;
#endif
    return idle;
}
static void r266_local_listening_ready(void){
    ui_status("请说本地指令");
    static const char ready[]="@@DFMN1 LISTEN_READY source=esp32_mic window_ms=8000\n";
    (void)h9_send_line(ready,sizeof(ready)-1);
}
static void r185_wake_greeting_worker(void *unused){
    (void)unused;
    // Single speaker worker consumes one origin decision at entry.
    const bool physical_wake_origin=r232_real_wake_greeting_pending;
    r232_real_wake_greeting_pending=false;
    if(physical_wake_origin)r251_wake_mark(301);
    bool played=false,from_sd=false;
    uint32_t local_lease=0;
    if(physical_wake_origin)r251_wake_mark(302);
    if(!r224_audio_claim(R224_MEDIA_LOCAL_CLIP,&local_lease)){
        ESP_LOGW(TAG,"R229_GREETING_CODEC_OWNER_BUSY");
#ifdef DF_R225_LOCAL_OFFLINE
        r225_last_clip=r225_requested_clip;
        r225_last_rc=-21;
        char failed[100];
        int failed_len=snprintf(failed,sizeof(failed),
            "@@DFOFFLINE1 FAILED id=%u source=none\n",r225_requested_clip);
        if(failed_len>0&&failed_len<(int)sizeof(failed))
            (void)h9_send_line(failed,(size_t)failed_len);
#endif
        speaking=false;r185_wake_resume();vTaskDelete(NULL);return;
    }
#ifdef DF_R225_LOCAL_OFFLINE
    const unsigned clip=r225_requested_clip;
    if(physical_wake_origin)r251_wake_mark(303);
    r228_sd_preload_rc=-99;r228_sd_stream_rc=-99;r228_sd_stage=0;
    // A cache hit needs no SD reader. A cache MISS must wait until the
    // animation reader releases the card, never preload in app_main.
    if(clip==0 && r226_sd_wake_cached() &&
       !r225_voice_upload_active() && !r154_sd_upload_pause_requested){
        if(!speaker)speaker=bsp_audio_codec_speaker_init();
        if(speaker && r226_play_cached_wake(speaker,r225_audio_owner,
                              volume>80?80:volume)==0){
            played=true;from_sd=true;r225_last_rc=0;r228_sd_stage=4;
        }
    }
    bool has_reader=false;
    uint32_t local_sd_lease=0;
    if(!played && !r154_sd_upload_pause_requested && !h13_sd_usb_active() &&
       !r225_voice_upload_active() && !r83_transfer_active() &&
       r224_sd_claim(R224_SD_LOCAL,&local_sd_lease)){
        r228_sd_stage=1;
        r154_sd_upload_pause_requested=true;
        for(unsigned tries=0;tries<80 && !r154_sd_upload_paused;tries++)
            vTaskDelay(pdMS_TO_TICKS(20));
        has_reader=r154_sd_upload_paused && !h12_use_sd;
        r228_sd_stage=has_reader?2:6;
    }
    if(!played && has_reader){
        if(!speaker)speaker=bsp_audio_codec_speaker_init();
        if(speaker){
            // Only first real SD reader ownership may fill the SHA-verified
            // PSRAM cache. On any failed preload/play use the old SD reader.
            if(clip==0){
                r228_sd_stage=3;
                r228_sd_preload_rc=r226_preload_sd_wake();
                if(r228_sd_preload_rc==0 &&
                   r226_play_cached_wake(speaker,r225_audio_owner,
                                         volume>80?80:volume)==0){
                    played=true;from_sd=true;r225_last_rc=0;r228_sd_stage=4;
                }
            }
            if(!played){
                r228_sd_stage=3;
                r259_local_speaking_visual=(clip!=0);
                r228_sd_stream_rc=r224_play_onboard_sd((r224_clip_t)clip,speaker,
                                 r225_audio_owner,volume>80?80:volume);
                r259_local_speaking_visual=false;
                r225_last_rc=r228_sd_stream_rc;
                from_sd=(r225_last_rc==0);
                played=from_sd;
                r228_sd_stage=played?4:7;
            }
        }
        if(r224_sd_owned(R224_SD_LOCAL,local_sd_lease)){
            r154_sd_upload_pause_requested=false;
            r154_sd_upload_paused=false;
            h13_boot_idle_pending=true;
            r224_sd_release(R224_SD_LOCAL,local_sd_lease);
            local_sd_lease=0;
        }
    }
    else if(local_sd_lease){
        // Only the requesting task may clear a timed-out SD pause.
        if(r224_sd_owned(R224_SD_LOCAL,local_sd_lease)){
            r154_sd_upload_pause_requested=false;
            r154_sd_upload_paused=false;
            r224_sd_release(R224_SD_LOCAL,local_sd_lease);
        }
    }
#else
    const unsigned clip=0;
#endif
    const uint8_t *wav=r185_greeting_start;
    size_t n=(size_t)(r185_greeting_end-r185_greeting_start);
    // Embedded greeting fallback preserves voice when SD is not provisioned.
    // It never rewrites the separate SD read/preload error telemetry.
    if(!played && clip==0 && r228_sd_stage==0)r228_sd_stage=5;
    // Other requested clips MUST NOT silently play a different sentence.
    if(!played && clip==0 && n>44 && n<100000 && memcmp(wav,"RIFF",4)==0 &&
       memcmp(wav+8,"WAVE",4)==0 && memcmp(wav+36,"data",4)==0 &&
       wav[20]==1 && wav[22]==1 && wav[24]==0xC0 && wav[25]==0x5D &&
       wav[34]==16 && ((n-44u)%2u)==0){
        if(!speaker)speaker=bsp_audio_codec_speaker_init();
        if(speaker){
            esp_codec_dev_sample_info_t fmt={
                .sample_rate=24000,.channel=1,.bits_per_sample=16
            };
            if(esp_codec_dev_open(speaker,&fmt)==ESP_CODEC_DEV_OK){
                (void)esp_codec_dev_set_out_vol(speaker,volume>80?80:volume);
                size_t total=(n-44u)/2u;
                played=true;
                for(size_t offset=0;offset<total;offset+=480u){
                    int16_t packet[480]={0};
                    for(size_t k=0;k<480u && offset+k<total;k++){
                        size_t x=44u+(offset+k)*2u;
                        packet[k]=(int16_t)((unsigned)wav[x] |
                                            ((unsigned)wav[x+1]<<8));
                    }
                    if(esp_codec_dev_write(speaker,packet,sizeof(packet))!=ESP_CODEC_DEV_OK){
                        played=false;break;
                    }
                }
                if(esp_codec_dev_close(speaker)!=ESP_CODEC_DEV_OK)played=false;
            }
        }
    }
#ifdef DF_R225_LOCAL_OFFLINE
    r225_last_clip=clip;
    r225_last_rc=played?0:r225_last_rc;
    char done[120];
    int done_len=snprintf(done,sizeof(done),
        "@@DFOFFLINE1 %s id=%u source=%s\n",
        played?"PLAYED":"FAILED",clip,from_sd?"sd":"embedded");
    if(done_len>0 && done_len<(int)sizeof(done))
        (void)h9_send_line(done,(size_t)done_len);
    if(!played){
        char diag[184];
        int m=snprintf(diag,sizeof(diag),
            "@@DFOFFLINE1 FAILURE_DETAIL id=%u stage=%u last_rc=%d preload_rc=%d stream_rc=%d\n",
            clip,r228_sd_stage,r225_last_rc,r228_sd_preload_rc,r228_sd_stream_rc);
        if(m>0 && m<(int)sizeof(diag))(void)h9_send_line(diag,(size_t)m);
    }
#endif
    if(physical_wake_origin)r251_wake_mark(350);
    r224_audio_release(R224_MEDIA_LOCAL_CLIP,local_lease);
    r302_wake_greeting_visual=false;
    speaking=false;
    // Local clip STOP must not poison subsequent WakeNet greetings.
    r51_stop_requested=false;
    // Auto capture only if Mac actually armed the official Voice3 session.
    TickType_t now=xTaskGetTickCount();
    bool authorized=usb_serial_jtag_is_connected()&&
        r232_should_auto_capture(physical_wake_origin,
        mic_host_armed,(int32_t)(mic_host_deadline-now));
    ESP_LOGI(TAG,"R232_GREETING completed=%u physical_wake=%u voice3_armed=%u",
             (unsigned)played,(unsigned)physical_wake_origin,
             (unsigned)authorized);
    if(physical_wake_origin)r251_wake_mark(360);
bool r265_offline_attempted=false;
int r265_offline_rc=0;
#if defined(DF_R225_LOCAL_OFFLINE) && defined(DF_R185_WN9)
    // R268: prefer the paired local-network official DSH voice path after
    // a physical WakeNet hit. If no DHCP/pairing, preserve original MN5/SD.
    if(physical_wake_origin && !authorized && played && r268_lan_start(true)){
        r232_real_wake_greeting_pending=false;
        ESP_LOGI(TAG,"R268_REAL_WAKE_TO_WIFI_SHARES_DSH");
        vTaskDelete(NULL);return;
    }
    if(physical_wake_origin && !authorized && played){
        ui_status("离线识别准备中");
        r265_offline_attempted=true;
        int real_cmd=r265_direct_mn5_command(microphone,8000u,
                                             r266_local_listening_ready);
        r265_offline_rc=real_cmd;
        unsigned diag_tries=0,diag_hits=0,diag_int=0,diag_psram=0;
        int diag_id=0,diag_err=0;
        r259_read_diagnostics(&diag_tries,&diag_hits,&diag_id,&diag_err,&diag_int,&diag_psram);
        char r265_event[175];
        int r265_n=snprintf(r265_event,sizeof(r265_event),
            "@@DFMN1 EVENT source=real_esp32_mic tries=%u hits=%u id=%d error=%d internal=%u psram=%u\n",
            diag_tries,diag_hits,diag_id,diag_err,diag_int,diag_psram);
        if(r265_n>0 && r265_n<(int)sizeof(r265_event))
            (void)h9_send_line(r265_event,(size_t)r265_n);
        if(real_cmd>0){
            for(size_t i=0;i<R259_COMMAND_COUNT;i++){
                if(R259_COMMANDS[i].command_id!=real_cmd)continue;
                r225_requested_clip=(unsigned)R259_COMMANDS[i].clip_id;
                r232_real_wake_greeting_pending=false;
                r51_stop_requested=false;
                speaking=true;
                ui_status("正在播放本地回复");
                if(xTaskCreate(r185_wake_greeting_worker,"r259_mn_reply",8192,
                               NULL,5,NULL)==pdPASS){
                    ESP_LOGI(TAG,"R259_REAL_MODEL_TO_SD id=%d clip=%d",
                             real_cmd,R259_COMMANDS[i].clip_id);
                    vTaskDelete(NULL);return;
                }
                speaking=false;
                break;
            }
        }
        ui_status(real_cmd==0?"本地指令未识别":
                  real_cmd<0?"离线识别不可用":"本地回复未播放");
    }
#endif
    if(authorized && played){
        mic_host_armed=false;
        h28_mic_button_pressed=true;
        h28_mic_press_session=true;
        r185_auto_capture=true;
        capturing=true;
        r36_record_begin_tick=now;
        ui_status("我在呢，请说话");
        if(physical_wake_origin)r251_wake_mark(361);
        if(xTaskCreate(mic_worker,"r185_auto_voice",MIC_STACK_BYTES,NULL,5,NULL)!=pdPASS){
            capturing=false;
            r185_auto_capture=false;
            h28_mic_press_session=false;
            h28_mic_button_pressed=false;
            r185_wake_resume();
        }
    } else {
        if(physical_wake_origin && r265_offline_attempted)
            ui_status(r265_offline_rc==0?"本地指令未识别":"离线识别不可用");
        else if(physical_wake_origin)
            ui_status(played?"语音唤醒成功 · Mac未就绪":"语音唤醒成功 · 提示音未播放");
        else if(played)
            ui_status("本地语音播放完成");
        else {
            char label[56];
            snprintf(label,sizeof(label),"本地播放失败 · 阶段%u",r228_sd_stage);
            ui_status(label);
        }
        r185_wake_resume();
        if(physical_wake_origin)r251_wake_mark(899);
    }
    vTaskDelete(NULL);
}
#if defined(DF_R225_LOCAL_OFFLINE) && defined(DF_R185_WN9)
// On-board touch playback reuses the verified offline SD speaker/lease.
// This worker never reads the Mac, invokes DSH or alters the model partition.
static void r257_local_touch_worker(void *unused){
    (void)unused;
    if(!r185_wake_wait_released(2300)){
        ESP_LOGW(TAG,"R257_LOCAL_WAKE_MIC_RELEASE_TIMEOUT");
        r51_stop_requested=false;
        speaking=false;
        r185_wake_resume();
        vTaskDelete(NULL);return;
    }
    r185_wake_greeting_worker(NULL); // self-deletes and releases audio lease
}
bool r257_local_voice_from_touch(unsigned clip){
    // Fixed IDs correspond to already installed R224 SD voice assets.
    if(!(clip==1 || clip==2 || clip==3 || clip==4 || clip==8))return false;
    if(speaking || capturing || h10_receiving || r37_pcm2_active ||
       loopback_busy || h28_mic_press_session || r83_transfer_active() ||
       r154_sd_upload_pause_requested || r225_voice_upload_active())return false;
    r225_requested_clip=clip;
    r232_real_wake_greeting_pending=false;
    r51_stop_requested=false;
    speaking=true;
    if(xTaskCreate(r257_local_touch_worker,"r257_sd_voice",8192,
                   NULL,5,NULL)!=pdPASS){
        speaking=false;r185_wake_resume();return false;
    }
    ESP_LOGI(TAG,"R257_ONBOARD_TOUCH_VOICE_ACCEPTED clip=%u",clip);
    return true;
}
#endif
static void r185_wake_detected(void){
    if(r268_lan_busy)return; // one physical wake/DSH turn at a time
    r251_wake_mark(200);
    if(!r185_wake_ready() || !r185_can_listen()) {
        r185_wake_resume();return;
    }
    static unsigned events=0;
#ifdef DF_R225_LOCAL_OFFLINE
    r225_requested_clip=0;
#endif
    ESP_LOGI(TAG,"R185_PHYSICAL_WAKE_DETECTED model=%s count=%u",
             r185_wake_active_model(),(unsigned)++events);
    r232_real_wake_greeting_pending=true;
    r302_wake_greeting_visual=true;
    // Boot/seq are correlation metadata only; they cannot authorize a model
    // request without valid ARM + completed Voice3 PCM. Sequence is real.
    uint32_t seq=++r228_wake_seq;
    if(seq==0){r228_wake_seq=1;seq=1;}
    char msg[172];
    int n=snprintf(msg,sizeof(msg),
        "@@DFWAKE3 DETECTED model=%s source=esp32_mic boot=%016llx seq=%lu\n",
        r185_wake_active_model(),
        (unsigned long long)r228_wake_boot_epoch,(unsigned long)seq);
    r251_wake_mark(201);
    if(n>0 && n<(int)sizeof(msg))(void)h9_send_line(msg,(size_t)n);
    r251_wake_mark(202);
    speaking=true;
    ui_status("我在呢");
    r251_wake_mark(203);
    r251_wake_mark(204);
    if(xTaskCreate(r185_wake_greeting_worker,
         "r185_greet",8192,NULL,5,NULL)!=pdPASS){
        r232_real_wake_greeting_pending=false;
        r302_wake_greeting_visual=false;
        speaking=false;r185_wake_resume();
    }
    r251_wake_mark(205);
}
#endif
static bool h28_microphone_ready(void){
    const TickType_t now=xTaskGetTickCount();
    if(!mic_host_armed||(int32_t)(now-mic_host_deadline)>=0){
        mic_host_armed=false;return false;
    }
    return !speaking&&!capturing&&!loopback_busy&&!h10_receiving;
}
static void h28_on_mic_button(lv_event_t *event){
    const lv_event_code_t code=lv_event_get_code(event);
    if(code==LV_EVENT_RELEASED||code==LV_EVENT_PRESS_LOST){
#ifndef DF_R30_TOGGLE_MIC
        h28_mic_button_pressed=false;
#endif
        return;
    }
    if(code!=LV_EVENT_PRESSED)return;
    // Explicit physical touch can start the paired LAN route when USB DSH
    // is absent. Second tap ends the MIC capture; no passive network audio.
    if(r268_lan_busy){
#ifdef DF_R434_MAC_PREWAKE_ONLY
        if(r434_prewake_active){
            r434_touch_pending=true;
            r51_stop_requested=true; /* prewake will close mic and TLS */
            lv_label_set_text(status_label,"正在切换触摸无线录音");
            return;
        }
#endif
        if(r268_current_phase==R268_LAN_LISTENING){
            r268_lan_touch_finish=true;
            lv_label_set_text(status_label,"无线录音发送中");
        }
        // Once FINISH is submitted, the mic is not a STOP control.
        // Accidental duplicate touch during TTS must not close WSS early.
        return;
    }
    if(!usb_serial_jtag_is_connected()){
        // All expensive pairing NVS/TLS checks happen outside LVGL. A failed
        // allocation never changes the capture/animation state or blocks UI.
        if(r268_lan_start(false)){
            // Touch event is already inside the LVGL task. Immediate visual
            // confirmation must not depend on a background timer getting CPU.
            lv_label_set_text(status_label,"正在连接无线大肥鱼");
            return;
        }
        lv_label_set_text(status_label,r276_lan_start_error==2?
            "Wi-Fi voice: low memory":"无线音频暂不可用");
        return;
    }
#ifdef DF_R30_TOGGLE_MIC
    if(h28_mic_press_session && capturing){
        h28_mic_button_pressed=false; // the SECOND tap ends the recording
#ifdef DF_R33_BOARD_UI
        r33_update_status(NULL);
#endif
        lv_label_set_text(status_label,"正在发送给 Mac");
        return;
    }
#endif
    if(!h28_microphone_ready()){
        lv_label_set_text(status_label,"Mac语音服务未就绪；本地触控可用");
        return;
    }
    mic_host_armed=false;
    h28_mic_button_pressed=true;
    h28_mic_press_session=true;
    capturing=true;
    r133_screen_abort_requested();
#ifdef DF_R33_BOARD_UI
    r36_record_begin_tick=xTaskGetTickCount();
#endif
#ifdef DF_R33_BOARD_UI
    r33_update_status(NULL);
#endif
    lv_label_set_text(status_label,
#ifdef DF_R30_TOGGLE_MIC
        "录音中 · 再点发送"
#else
        "录音中 · 松开发送"
#endif
    );
    if(xTaskCreate(mic_worker,"h28_push_to_talk",MIC_STACK_BYTES,NULL,5,NULL)!=pdPASS){
        h28_mic_button_pressed=false;
        h28_mic_press_session=false;
        capturing=false;
        lv_label_set_text(status_label,"麦克风不可用");
    }
}
static void r133_on_avatar_drag(lv_event_t *event){
    static lv_point_t origin={0};static bool down=false,moved=false;
    const lv_event_code_t code=lv_event_get_code(event);
    lv_indev_t *dev=lv_indev_active();lv_point_t pt={0};
    if(dev)lv_indev_get_point(dev,&pt);
    if(code==LV_EVENT_PRESSED){origin=pt;down=true;moved=false;return;}
    if(code==LV_EVENT_PRESSING && down){
        if(abs((int)(pt.x-origin.x))>=26 || abs((int)(pt.y-origin.y))>=26)
            moved=true;
        return;
    }
    if(code==LV_EVENT_RELEASED || code==LV_EVENT_PRESS_LOST){
        if(down && moved && !capturing && !speaking && !h10_receiving){
            r133_drag_requested=true;
            h28_touch_requested=true;
            h30_touch_requested_at=xTaskGetTickCount();
            r133_drag_count++;
            ESP_LOGI(TAG,"R133_HARDWARE_DRAG count=%lu dx=%ld dy=%ld",
                (unsigned long)r133_drag_count,(long)(pt.x-origin.x),
                (long)(pt.y-origin.y));
        }
        down=false;moved=false;
    }
}
static void h28_on_avatar_tap(lv_event_t *event){
    if(lv_event_get_code(event)!=LV_EVENT_SHORT_CLICKED)return;
    if(r133_drag_requested)return;
    if(capturing||speaking||h10_receiving||h28_mic_press_session)return;
#ifdef DF_H11_PREVIEW_STATES
    if(strcmp(h11_current_state.phase,"idle")!=0)return;
#endif
    if(r133_rules_arm_tap()){
        lv_label_set_text(status_label,"规则修改已获现场授权");return;
    }
    if(r150_rules_arm_tap()){
        lv_label_set_text(status_label,"106条规则修改已获现场授权");return;
    }
    if(r83_arm_touch()){
        lv_label_set_text(status_label,"SD upload authorized - return to Mac");
        return;
    }
    // Tapping the character is a visible, free, local touch reaction only.
    // It never triggers recording/DSH and has no synthetic host motion ACK.
    h28_touch_requested=true;
    // R461: reset an obsolete completed stop marker on an explicit fresh
    // local touch. The authenticated WSS numeric trace remains untouched.
    // Do not alter a currently active wireless playback/turn.
    if(!r268_lan_busy && r298_lan_cancelled){
        r298_lan_cancelled=false;
        r279_lan_ui_phase=R268_LAN_IDLE;
        r279_lan_ui_seq++;
    }
    // A small immediate visual ACK while the real SD first frame loads.
    h30_touch_requested_at=xTaskGetTickCount();
    r441_touch_status_until=xTaskGetTickCount()+pdMS_TO_TICKS(1500);
    lv_label_set_text(status_label,"正在播放互动动作");
}
#endif
// Incoming USB control commands must match a fixed allow-list. No generic
// shell, no arbitrary model tools, and no automatic microphone activation.
static void usb_control_worker(void *unused){
    (void)unused;
    usb_serial_jtag_driver_config_t cfg={
        .tx_buffer_size=4096,.rx_buffer_size=8192,
    };
    const esp_err_t rc=usb_serial_jtag_driver_install(&cfg);
    if(rc!=ESP_OK){
        ESP_LOGW(TAG,"H9_USB_CONTROL_DRIVER_UNAVAILABLE err=%d",rc);
        vTaskDelete(NULL);return;
    }
    // Route legacy console prints through same interrupt-backed ring buffer;
    // the raw PCM sender uses driver TX lock for its complete packet.
    usb_serial_jtag_vfs_use_driver();
    ESP_LOGI(TAG,"H9_USB_VFS_DRIVER_SERIALISED");
    static char command[H10_COMMAND_LIMIT]={0};
    size_t at=0;
    ESP_LOGI(TAG,"H9_USB_CONTROL_READY");
    for(;;){
        r83_usb_housekeeping(capturing||speaking||h10_receiving||r37_pcm2_active);
        // Receive up to one full USB-JTAG driver buffer per SDK call.
        // The former single-byte reads were correct but capped SD transfer
        // at an unnecessarily slow rate for 96 MiB of user-selected art.
        char incoming[512];
        int n=usb_serial_jtag_read_bytes(incoming,sizeof(incoming),pdMS_TO_TICKS(1000));
        if(n<1){
            r133_screen_tick(capturing||speaking||h10_receiving||r37_pcm2_active);
            if(h10_receiving && (int32_t)(xTaskGetTickCount()-h10_rx_deadline)>0){
                h10_dynamic_cancel();
                ESP_LOGE(TAG,"H10_DYN_RX_TIMEOUT");
            }
            continue;
        }
        for(int byte_i=0;byte_i<n;byte_i++){
        char ch=incoming[byte_i];
        if(ch=='\r')continue;
        if(ch!='\n'){
            if(at<sizeof(command)-1)command[at++]=ch;
            else at=0;
            continue;
        }
        command[at]='\0';
        // R268: local USB-only pairing. Never echo a bearer token, TLS
        // certificate bytes, SSID or password through the device console.
        // R283: allow the exact read-only UI/audio trace command into this
        // dispatcher. R281 placed its handler under a DF-LAN-only prefix,
        // making @@DFUI2 DIAG unreachable despite being compiled and flashed.
        if(strncmp(command,"@@DFLAN2 ",9)==0 ||
           strcmp(command,"@@DFUI2 DIAG")==0 ||
           strcmp(command,"@@DFUI3 DIAG")==0 ||
           strcmp(command,"@@DFUI4 DIAG")==0 ||
           strcmp(command,"@@DFMOTION4 DIAG")==0 ||
           strcmp(command,"@@DFMOTION5 DIAG")==0){
            bool idle=!capturing&&!speaking&&!r268_lan_busy&&
                       !r37_pcm2_active&&!h10_receiving&&
                       !r83_transfer_active();
            const char *reply="@@DFLAN2 NACK busy_or_invalid\n";
            if(strcmp(command,"@@DFLAN2 STATUS")==0){
                char status[100];
                r62_wifi_state_t wifi={0};r62_wifi_snapshot(&wifi);
                int count=snprintf(status,sizeof(status),
                    "@@DFLAN2 STATUS paired=%u wifi_ip=%u voice_busy=%u\n",
                    (unsigned)r268_lan_paired(),(unsigned)wifi.has_ip,
                    (unsigned)r268_lan_busy);
                if(count>0&&count<(int)sizeof(status))
                    (void)h9_send_line(status,(size_t)count);
                at=0;continue;
            }
            // R276: numerical RAM/boot preflight, no microphone, no TLS
            // exchange, no passwords or nearby SSIDs in the serial reply.
            // R281: numeric-only post-battery voice/UI/codec evidence.
            // RTC_NOINIT preserves the just-finished turn over USB reset.
            // No PCM, transcript, token, nearby SSID or caller identity.
            if(strcmp(command,"@@DFUI2 DIAG")==0){
                char line[225];
                const unsigned known=r281_trace.magic==R281_DIAG_MAGIC;
                int n=snprintf(line,sizeof(line),
                  "@@DFUI2 DIAG known=%u sessions=%lu phases=%lu "
                  "lvgl=%lu labels=%lu avatar=%lu spkblocks=%lu "
                  "slow=%lu maxwrite_us=%lu peak=%lu clips=%lu\n",
                  known,
                  (unsigned long)(known?r281_trace.sessions:0),
                  (unsigned long)(known?r281_trace.voice_phase_events:0),
                  (unsigned long)(known?r281_trace.lvgl_ticks:0),
                  (unsigned long)(known?r281_trace.status_commits:0),
                  (unsigned long)(known?r281_trace.avatar_frames_during_wifi:0),
                  (unsigned long)(known?r281_trace.speaker_blocks:0),
                  (unsigned long)(known?r281_trace.slow_codec_blocks:0),
                  (unsigned long)(known?r281_trace.max_codec_write_us:0),
                  (unsigned long)(known?r281_trace.max_source_peak:0),
                  (unsigned long)(known?r281_trace.clipped_source_samples:0));
                if(n>0 && n<(int)sizeof(line))(void)h9_send_line(line,(size_t)n);
                at=0;continue;
            }
            if(strcmp(command,"@@DFUI3 DIAG")==0){
                char info[140];
                const bool known=r296_trace.magic==R296_ANIM_TRACE_MAGIC;
                int len=snprintf(info,sizeof(info),
                   "@@DFUI3 DIAG known=%u frames=%lu changed=%lu "
                   "refr_ready=%lu flushed=%lu\n",
                   (unsigned)known,
                   (unsigned long)(known?r296_trace.frames:0),
                   (unsigned long)(known?r296_trace.changed_frames:0),
                   (unsigned long)(known?r296_trace.refr_ready:0),
                   (unsigned long)(known?r296_trace.flush_wait_done:0));
                if(len>0 && len<(int)sizeof(info))
                    (void)h9_send_line(info,(size_t)len);
                at=0;continue;
            }
            if(strcmp(command,"@@DFUI4 DIAG")==0){
                char info[180];
                const bool known=r302_trace.magic==R302_BREATH_MAGIC;
                int len=snprintf(info,sizeof(info),
                   "@@DFUI4 DIAG known=%u pulses=%lu wake=%lu mic=%lu "
                   "lockmiss=%lu restores=%lu\n",
                   (unsigned)known,
                   (unsigned long)(known?r302_trace.pulses:0),
                   (unsigned long)(known?r302_trace.wake_pulses:0),
                   (unsigned long)(known?r302_trace.mic_pulses:0),
                   (unsigned long)(known?r302_trace.lock_misses:0),
                   (unsigned long)(known?r302_trace.restores:0));
                if(len>0 && len<(int)sizeof(info))
                    (void)h9_send_line(info,(size_t)len);
                at=0;continue;
            }
            if(strcmp(command,"@@DFMOTION6 DIAG")==0){
                char info[186];
                r332_trace_init();
                int len=snprintf(info,sizeof(info),
                    "@@DFMOTION6 DIAG talks=%lu tries=%lu applied=%lu "
                    "failed=%lu deferred=%lu mouthframes=%lu lastid=%lu\n",
                    (unsigned long)r332_motion_trace.talk_starts,
                    (unsigned long)r332_motion_trace.talk_attempts,
                    (unsigned long)r332_motion_trace.talk_applied,
                    (unsigned long)r332_motion_trace.talk_fail,
                    (unsigned long)r332_motion_trace.deferred_idle,
                    (unsigned long)r332_motion_trace.mouth_render_frames,
                    (unsigned long)r332_motion_trace.last_selected);
                if(len>0&&len<(int)sizeof(info))
                    (void)h9_send_line(info,(size_t)len);
                at=0;continue;
            }
            if(strcmp(command,"@@DFMOTION5 DIAG")==0){
                char info[85];
                int len=snprintf(info,sizeof(info),
                    "@@DFMOTION5 DIAG talkloops=%lu\n",
                    (unsigned long)(r304_mouth_trace.magic==
                          R304_MOUTH_DIAG_MAGIC?r304_mouth_trace.cycles:0));
                if(len>0 && len<(int)sizeof(info))
                    (void)h9_send_line(info,(size_t)len);
                at=0;continue;
            }
            if(strcmp(command,"@@DFMOTION4 DIAG")==0){
                char info[150];
                const bool known=r303_trace.magic==R303_MOTION_MAGIC;
                int len=snprintf(info,sizeof(info),
                    "@@DFMOTION4 DIAG known=%u work=%lu fail=%lu idle=%lu\n",
                    (unsigned)known,
                    (unsigned long)(known?r303_trace.work_selected:0),
                    (unsigned long)(known?r303_trace.work_failed:0),
                    (unsigned long)(known?r303_trace.idle_restores:0));
                if(len>0 && len<(int)sizeof(info))
                    (void)h9_send_line(info,(size_t)len);
                at=0;continue;
            }
            if(strcmp(command,"@@DFLAN2 DETAIL")==0){
                r277_lan_diag_t diag={0};
                const bool known=r277_lan_diag_snapshot(&diag);
                char info[135];
                int len=snprintf(info,sizeof(info),
                   "@@DFLAN2 DETAIL known=%u sub=%lu opcode=%lu bytes=%lu\n",
                   (unsigned)known,
                   (unsigned long)(known?diag.protocol_detail:0),
                   (unsigned long)(known?diag.protocol_opcode:0),
                   (unsigned long)(known?diag.protocol_bytes:0));
                if(len>0 && len<(int)sizeof(info))
                    (void)h9_send_line(info,(size_t)len);
                at=0;continue;
            }
            if(strcmp(command,"@@DFLAN2 DIAG")==0){
                r277_lan_diag_t diag={0};
                const bool known=r277_lan_diag_snapshot(&diag);
                char response[190];
                int n=snprintf(response,sizeof(response),
                    "@@DFLAN2 DIAG known=%u stage=%lu failed=%lu errno=%ld "
                    "free=%lu largest=%lu elapsed=%lu success=%u reason=%lu\n",
                    (unsigned)known,(unsigned long)diag.stage,
                    (unsigned long)diag.failed_stage,(long)diag.socket_errno,
                    (unsigned long)diag.internal_free,
                    (unsigned long)diag.internal_largest,
                    (unsigned long)diag.elapsed_ms,
                    (unsigned)diag.result,
                    (unsigned long)diag.exit_reason);
                if(n>0 && n<(int)sizeof(response))
                    (void)h9_send_line(response,(size_t)n);
                at=0;continue;
            }
            if(strcmp(command,"@@DFLAN2 AUDIO")==0){
                // R441: read-only RTC playback telemetry; never opens audio,
                // resets the device, reads NVS, or stores human speech.
                r277_lan_diag_t diag={0};
                const bool known=r277_lan_diag_snapshot(&diag);
                char response[190];
                int n=snprintf(response,sizeof(response),
                    "@@DFLAN2 AUDIO known=%u ring_empty=%lu recv_max_ms=%lu "
                    "recv_slow=%lu codec_max_ms=%lu codec_slow=%lu\n",
                    (unsigned)known,
                    (unsigned long)(known?diag.playback_ring_empty_events:0),
                    (unsigned long)(known?diag.playback_read_max_wait_ms:0),
                    (unsigned long)(known?diag.playback_read_slow_events:0),
                    (unsigned long)(known?diag.playback_codec_call_max_ms:0),
                    (unsigned long)(known?diag.playback_codec_slow_events:0));
                if(n>0 && n<(int)sizeof(response))
                    (void)h9_send_line(response,(size_t)n);
                at=0;continue;
            }
            if(strcmp(command,"@@DFLAN2 PREFLIGHT")==0){
                r62_wifi_state_t net={0};r62_wifi_snapshot(&net);
                const size_t available=heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT);
                const size_t largest=heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT);
                char status[180];
                int count=snprintf(status,sizeof(status),
                    "@@DFLAN2 PREFLIGHT pair=%u ip=%u usb=%u free=%lu largest=%lu stack=14336 canalloc=%u\n",
                    (unsigned)r276_lan_paired_cached,(unsigned)net.has_ip,
                    (unsigned)r268_usb_host_alive(),
                    (unsigned long)available,(unsigned long)largest,
                    (unsigned)(available>=42*1024 && largest>=18*1024));
                if(count>0&&count<(int)sizeof(status))
                    (void)h9_send_line(status,(size_t)count);
                at=0;continue;
            }
            if(idle&&usb_serial_jtag_is_connected()){
                if(strncmp(command,"@@DFLAN2 PAIR ",14)==0){
                    const bool ok=r268_lan_usb_pair(command);
                    if(ok)r276_lan_paired_cached=true;
                    reply=ok?"@@DFLAN2 PAIRED\n":"@@DFLAN2 NACK invalid_pair\n";
                }else if(strcmp(command,"@@DFLAN2 FORGET")==0){
                    r268_lan_usb_forget();r276_lan_paired_cached=false;
                    reply="@@DFLAN2 FORGOTTEN\n";
                }
            }
            (void)h9_send_line(reply,strlen(reply));
            at=0;continue;
        }
#ifdef DF_R33_BOARD_UI
        if(strncmp(command,"@@DFVOICE1 ARM",14)==0 ||
           strncmp(command,"@@DFSTATE1 SET ",15)==0 ||
           strncmp(command,"@@DFCLOCK1 SET ",15)==0 ||
           strncmp(command,"@@DFPCM1 ",9)==0)
            r36_mac_seen_at=xTaskGetTickCount();
#endif
#ifdef DF_H13_SD_UPLOAD
#ifdef DF_H28_HOLD_MIC
#ifdef DF_R185_WN9
        if(strcmp(command,"@@DFWAKE3 CAPS")==0 ||
           strcmp(command,"@@DFWAKE3 STATUS")==0){
            char line[172];
            int n=snprintf(line,sizeof(line),
                "@@DFWAKE3 STATE model=%s ready=%u enabled=%u source=esp32_mic commands=0 boot=%016llx\n",
                r185_wake_active_model(),
                (unsigned)r185_wake_ready(),(unsigned)r185_wake_enabled(),
                (unsigned long long)r228_wake_boot_epoch);
            if(n>0 && n<(int)sizeof(line))(void)h9_send_line(line,(size_t)n);
            if(strcmp(command,"@@DFWAKE3 STATUS")==0){
                char diag[230];
                int dn=snprintf(diag,sizeof(diag),
                    "@@DFWAKE3 DIAG can_listen=%u wake_mic=%u reading=%u "
                    "capture=%u speak=%u pcm2=%u h10=%u transfer=%u phase=%s\n",
                    (unsigned)r185_can_listen(),(unsigned)r185_wake_owns_mic(),
                    (unsigned)r185_wake_read_inflight(),(unsigned)capturing,
                    (unsigned)speaking,(unsigned)r37_pcm2_active,
                    (unsigned)h10_receiving,(unsigned)r83_transfer_active(),
                    h11_current_state.phase);
                if(dn>0 && dn<(int)sizeof(diag))
                    (void)h9_send_line(diag,(size_t)dn);
                /* Bounded, numeric-only stage query. Works while
                 * esp_codec_dev_read / iface->detect is blocked. */
                r242_wake_stage stages={0};
                r242_wake_stage_read(&stages);
                char evidence[256];
                int en=snprintf(evidence,sizeof(evidence),
                    "@@DFWAKE3 STAGE re=%u ok=%u err=%u skip=%u "
                    "de=%u dr=%u hit=%u of=%u phase=%u age_ms=%u\n",
                    stages.read_enter,stages.read_ok,
                    stages.read_error,stages.gate_skip,
                    stages.detect_enter,stages.detect_return,
                    stages.detected,stages.open_fail,
                    stages.phase,stages.phase_age_ms);
                if(en>0 && en<(int)sizeof(evidence))
                    (void)h9_send_line(evidence,(size_t)en);
                r247_wake_speed speed={0};
                r247_wake_speed_read(&speed);
                char counters[292];
                int cn=snprintf(counters,sizeof(counters),
                    "@@DFWAKE3 RATE n=%u ch=%u hz=%u window_ms=%u "
                    "frames=%u read_us=%u detect_us=%u "
                    "read_max_us=%u detect_max_us=%u "
                    "peak=%u loud=%u clipped=%u\n",
                    speed.model_chunk,speed.model_channels,speed.model_rate,
                    speed.window_ms,speed.frames,speed.read_us_sum,
                    speed.detect_us_sum,speed.read_us_max,speed.detect_us_max,
                    speed.peak_16bit,speed.loud_frames,speed.clipped_frames);
                if(cn>0 && cn<(int)sizeof(counters))
                    (void)h9_send_line(counters,(size_t)cn);
                /* R249: repeat a bounded boot reason in existing read-only
                 * status polling so USB-only monitoring can distinguish
                 * brownout/panic/wdt reset from ordinary serial reconnect.
                 * No NVS write, audio data or reset is caused by this line. */
                char boot_info[99];
                int bn=snprintf(boot_info,sizeof(boot_info),
                    "@@DFWAKE3 BOOT reason=%u uptime_ms=%u\n",
                    (unsigned)esp_reset_reason(),
                    (unsigned)(xTaskGetTickCount()*portTICK_PERIOD_MS));
                if(bn>0 && bn<(int)sizeof(boot_info))
                    (void)h9_send_line(boot_info,(size_t)bn);
                char rt[157];
                int rn=snprintf(rt,sizeof(rt),
                    "@@DFWAKE3 BOOT2 boots=%u last_step=%u crash_step=%u crash_reason=%u\n",
                    (unsigned)r251_trace.boots,
                    (unsigned)r251_trace.last_step,
                    (unsigned)r251_trace.crash_step,
                    (unsigned)r251_trace.crash_reason);
                if(rn>0 && rn<(int)sizeof(rt))
                    (void)h9_send_line(rt,(size_t)rn);

            }
            at=0;continue;
        }
        if(strcmp(command,"@@DFWAKE3 ENABLE")==0){
            if(r185_wake_ready()){
                r185_wake_enable(true);
                static const char msg[]="@@DFWAKE3 ENABLED word=ni_hao_da_fei_yu\n";
                (void)h9_send_line(msg,sizeof(msg)-1);
            }else{
                static const char msg[]="@@DFWAKE3 UNAVAILABLE reason=model_or_heap\n";
                (void)h9_send_line(msg,sizeof(msg)-1);
            }
            at=0;continue;
        }
        if(strcmp(command,"@@DFWAKE3 DISABLE")==0){
            r185_wake_enable(false);
            bool released=r185_wake_wait_released(1400);
            const char *msg=released?"@@DFWAKE3 DISABLED\n":
                "@@DFWAKE3 NACK reason=mic_busy\n";
            (void)h9_send_line(msg,strlen(msg));
            at=0;continue;
        }
#endif
        if(strcmp(command,"@@DFVOICE3 CAPS")==0){
            static const char c[]=
#ifdef DF_R30_TOGGLE_MIC
                "@@DFVOICE3 READY source=esp32_mic trigger=tap_toggle max_frames=1000\n";
#else
                "@@DFVOICE3 READY source=esp32_mic trigger=hold_release max_frames=1000\n";
#endif
            (void)h9_send_line(c,sizeof(c)-1);
            at=0;continue;
        }
#endif
#ifdef DF_R33_BOARD_UI
        if(strncmp(command,"@@DFCLOCK2 SET ",15)==0){
            unsigned y=99,mo=99,d=99,h=99,mi=99,sec=99,w=99;
            char extra=0;
            bool valid=strlen(command)==28 &&
                sscanf(command+15,"%2u%2u%2u%2u%2u%2u%1u%c",
                       &y,&mo,&d,&h,&mi,&sec,&w,&extra)==7 &&
                r61_valid_date(y,mo,d) && h<24 && mi<60 && sec<60 && w<7;
            if(valid){
                r34_host_clock_minute=h*60u+mi;
                r34_host_clock_tick=xTaskGetTickCount();
                r34_host_clock_valid=true;
                bool persistent=r61_rtc_set_checked(y,mo,d,h,mi,sec,w);
                ESP_LOGI(TAG,"R61_RTC_SYNC verified=%u",(unsigned)persistent);
                static const char applied[]="@@DFCLOCK2 APPLIED rtc=1\n";
                static const char fallback[]="@@DFCLOCK2 APPLIED rtc=0\n";
                if(persistent)(void)h9_send_line(applied,sizeof(applied)-1);
                else (void)h9_send_line(fallback,sizeof(fallback)-1);
            }else{
                static const char rejected[]="@@DFCLOCK2 REJECTED\n";
                (void)h9_send_line(rejected,sizeof(rejected)-1);
            }
            at=0;continue;
        }
        if(strcmp(command,"@@DFRTC2 GET")==0){
            r34_telemetry();
            char line[90];
            int n=snprintf(line,sizeof(line),"@@DFRTC2 valid=%u hhmm=%02u%02u\n",
                           (unsigned)r34_rtc_valid,
                           r34_rtc_valid?r34_hour:0u,r34_rtc_valid?r34_minute:0u);
            if(n>0&&n<(int)sizeof(line))(void)h9_send_line(line,(size_t)n);
            at=0;continue;
        }
        if(strncmp(command,"@@DFCLOCK1 SET hhmm=",20)==0){
            unsigned hour=99,minute=99;char extra=0;
            if(strlen(command)==24 &&
               sscanf(command+20,"%2u%2u%c",&hour,&minute,&extra)==2 &&
               hour<24 && minute<60){
                r34_host_clock_minute=hour*60u+minute;
                r34_host_clock_tick=xTaskGetTickCount();
                r34_host_clock_valid=true;
                static const char ack[]="@@DFCLOCK1 APPLIED\n";
                (void)h9_send_line(ack,sizeof(ack)-1);
            }else{
                static const char reject[]="@@DFCLOCK1 REJECTED\n";
                (void)h9_send_line(reject,sizeof(reject)-1);
            }
            at=0;continue;
        }
#endif
#ifdef DF_R33_BOARD_UI
        if(strcmp(command,"@@DFCHAT2 STATUS")==0){
            char line[136];
            int n=snprintf(line,sizeof(line),
                "@@DFCHAT2 STATUS bytes=%u,%u,%u,%u rev=%lu\n",
                (unsigned)strnlen(r57_recent[0],768),
                (unsigned)strnlen(r57_recent[1],768),
                (unsigned)strnlen(r57_recent[2],768),
                (unsigned)strnlen(r57_recent[3],768),
                (unsigned long)r57_recent_revision);
            if(n>0 && n<(int)sizeof(line))(void)h9_send_line(line,(size_t)n);
            at=0;continue;
        }
        if(strncmp(command,"@@DFCHAT2 slot=",15)==0){
            unsigned slot=99,index=999,final=9;char b64[180]={0},extra=0;
            if(sscanf(command,"@@DFCHAT2 slot=%u index=%u final=%u b64=%179s%c",
                      &slot,&index,&final,b64,&extra)==4 &&
               slot<4 && index<9 && final<=1){
                if(index==0){r57_recent[slot][0]=0;r62_chat2_next[slot]=0;}
                if(index==r62_chat2_next[slot]){
                    uint8_t decoded[100]={0};size_t used=0;
                    size_t current=strnlen(r57_recent[slot],768);
                    if(mbedtls_base64_decode(decoded,sizeof(decoded)-1,&used,
                       (const unsigned char*)b64,strlen(b64))==0 &&
                       used<=96 && current+used<=768){
                        for(size_t j=0;j<used;j++)if(decoded[j]<32)decoded[j]=' ';
                        memcpy(r57_recent[slot]+current,decoded,used);
                        r57_recent[slot][current+used]=0;
                        ++r62_chat2_next[slot];
                        if(final){r57_recent_revision++;r62_chat2_next[slot]=0;}
                    }
                }
            }
            at=0;continue;
        }
        if(strncmp(command,"@@DFCHAT1 slot=",15)==0){
            unsigned slot=99;
            char encoded[220]={0},extra=0;
            if(sscanf(command,"@@DFCHAT1 slot=%u b64=%219s%c",
                      &slot,encoded,&extra)==2 && slot<4){
                if(strcmp(encoded,"-")==0){
                    r57_recent[slot][0]='\0';
                    r57_recent_revision++;
                }else{
                    uint8_t decoded[127]={0};size_t n=0;
                    int valid=mbedtls_base64_decode(decoded,sizeof(decoded)-1,
                        &n,(const unsigned char*)encoded,strlen(encoded));
                    if(valid==0 && n<=105){
                        for(size_t k=0;k<n;k++)
                            if(decoded[k]<32u)decoded[k]=' ';
                        memcpy(r57_recent[slot],decoded,n);
                        r57_recent[slot][n]='\0';
                        r57_recent_revision++;
                    }
                }
            }
            at=0;continue;
        }
        if(strncmp(command,"@@DFLINK1 ERROR=",16)==0){
#ifdef DF_R33_BOARD_UI
            const char *reason=command+16;
            if(strcmp(reason,"DSH")==0 || strcmp(reason,"STT")==0 ||
               strcmp(reason,"TTS")==0 || strcmp(reason,"PCM2")==0 ||
               strcmp(reason,"MIC")==0 || strcmp(reason,"UNKNOWN")==0){
                size_t n=strnlen(reason,7);
                memcpy(r50_link_error,reason,n);
                r50_link_error[n]='\0';
                static const char ack[]="@@DFLINK1 RECORDED\n";
                (void)h9_send_line(ack,sizeof(ack)-1);
            }
#endif
            at=0;continue;
        }
        if(strcmp(command,"@@DFTURN1 RESULT=ok")==0 ||
           strcmp(command,"@@DFTURN1 RESULT=failed")==0 ||
           strcmp(command,"@@DFTURN1 RESULT=stopped")==0){
            r36_real_turns++;
            r36_last_turn_ok=strcmp(command,"@@DFTURN1 RESULT=ok")==0;
            r51_last_stopped=strcmp(command,"@@DFTURN1 RESULT=stopped")==0;
            if(!r36_last_turn_ok && strcmp(r50_link_error,"DSH")==0 &&
                r50_progress>3)r50_progress=3;
            if(r36_last_turn_ok)r50_progress=6;
            static const char ack[]="@@DFTURN1 RECORDED\n";
            (void)h9_send_line(ack,sizeof(ack)-1);
            at=0;continue;
        }
        if(strcmp(command,"@@DFR82 CAPS")==0){
            static const char reply[]="@@DFR82 READY modes=live,quadrants,frozen build=82\n";
            (void)h9_send_line(reply,sizeof(reply)-1);
            at=0;continue;
        }
        if(strcmp(command,"@@DFR82 MODE=live")==0 ||
           strcmp(command,"@@DFR82 MODE=quadrants")==0 ||
           strcmp(command,"@@DFR82 MODE=frozen")==0){
            /* No LVGL calls from USB worker. Never enables radio/mic/SD writes. */
            r82_display_mode=(strcmp(command,"@@DFR82 MODE=quadrants")==0)?1u:
                             (strcmp(command,"@@DFR82 MODE=frozen")==0)?2u:0u;
            static const char reply[]="@@DFR82 QUEUED\n";
            (void)h9_send_line(reply,sizeof(reply)-1);
            at=0;continue;
        }
        /* R82_SD_STAGE_DIAGNOSTICS */
        if(strcmp(command,"@@DFR87 MOUNT")==0){
            unsigned step=0,sector=0,capacity=0,drive=999;
            int esp=0,fs=999;
            h13_r87_mount_trace(&step,&sector,&capacity,&drive,&esp,&fs);
            char line[181];
            int n=snprintf(line,sizeof(line),
              "@@DFR87 MOUNT step=%u sector=%u capacity=%u drive=%u esp=%d fatfs=%d\n",
              step,sector,capacity,drive,esp,fs);
            if(n>0&&n<(int)sizeof(line))(void)h9_send_line(line,(size_t)n);
            at=0;continue;
        }
        if(strcmp(command,"@@DFR86 SD35")==0){
            unsigned stage=0,id=999,expected=0,actual=0,found=0;
            int error=0;
            h13_r86_trace(&stage,&id,&error,&expected,&actual,&found);
            char msg[190];
            int n=snprintf(msg,sizeof(msg),
                "@@DFR86 SD35 stage=%u good=%u bad_id=%u fresult=%d expected=%u actual=%u\n",
                stage,found,id,error,expected,actual);
            if(n>0&&n<(int)sizeof(msg))(void)h9_send_line(msg,(size_t)n);
            at=0;continue;
        }
        if(strcmp(command,"@@DFR82 SD")==0){
            char reply[192];
            int n=snprintf(reply,sizeof(reply),
               "@@DFR82 SD stage=%u failed=%u err=%u internal=%lu largest=%lu psram=%lu\n",
               r82_sd_stage_value(),r82_sd_failed_at_value(),r82_sd_error_value(),
               (unsigned long)heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
               (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
               (unsigned long)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
            if(n>0 && n<(int)sizeof(reply))(void)h9_send_line(reply,(size_t)n);
            at=0;continue;
        }
        if(strcmp(command,"@@DFR82 STATUS")==0){
            char reply[132];
            int n=snprintf(reply,sizeof(reply),
                "@@DFR82 STATUS requested=%u current=%u transitions=%lu static_frames=%lu\n",
                r82_display_mode,r82_current_mode,
                (unsigned long)r82_mode_changes,(unsigned long)r82_static_enters);
            if(n>0 && n<(int)sizeof(reply))(void)h9_send_line(reply,(size_t)n);
            at=0;continue;
        }
        if(strncmp(command,"@@DFSCREEN3 ",12)==0){
            r133_screen_command(command,
                capturing||speaking||h10_receiving||r37_pcm2_active||r83_transfer_active(),
                h9_send_line);
            at=0;continue;
        }
        if(strncmp(command,"@@DFTRIGGER2 ",13)==0){
            r150_rules_command(command,
                capturing||speaking||h10_receiving||r37_pcm2_active||r83_transfer_active(),
                h9_send_line);
            at=0;continue;
        }
        if(strncmp(command,"@@DFTRIGGER1 ",13)==0){
            // R140 legacy API stays read-only once opt-in 106 v2 rules go
            // active, never silently write an ignored NVS map1.
            bool legacy_write=(strstr(command," ARM_REQUEST")||
                strstr(command," BEGIN")||strstr(command," SET ")||
                strstr(command," COMMIT"));
            if(r150_rules_v2_active() && legacy_write){
                static const char notice[]="@@DFTRIGGER1 NACK reason=use_v2_rules\n";
                (void)h9_send_line(notice,sizeof(notice)-1);
            } else r133_rules_command(command,
                capturing||speaking||h10_receiving||r37_pcm2_active||r83_transfer_active(),
                h9_send_line);
            at=0;continue;
        }
        if(strcmp(command,"@@DFGESTURE1 STATUS")==0){
            char reply[110];int n=snprintf(reply,sizeof(reply),
               "@@DFGESTURE1 STATE drag_count=%lu pending=%u\n",
               (unsigned long)r133_drag_count,(unsigned)r133_drag_requested);
            if(n>0&&n<(int)sizeof(reply))(void)h9_send_line(reply,(size_t)n);
            at=0;continue;
        }
        if(strcmp(command,"@@DFSCREEN2 CAPS")==0){
            static const char ready[]=
                "@@DFSCREEN2 READY width=480 height=480 format=rgb565 source=lvgl_snapshot\n";
            (void)h9_send_line(ready,sizeof(ready)-1);
            at=0;continue;
        }
        if(strcmp(command,"@@DFSCREEN2 CAPTURE")==0){
            /* Full LVGL rendered page including title/status/mic overlays.
             * This is NOT camera/OLED scanout readback. Never touch SD/NVS.
             * Explicitly refuse during microphone and speaker activity.
             */
            if(capturing||speaking||h10_receiving||r37_pcm2_active){
                static const char busy[]="@@DFSCREEN2 NACK busy_audio\n";
                (void)h9_send_line(busy,sizeof(busy)-1);
                at=0;continue;
            }
            const size_t raw_size=480u*480u*2u;
            uint8_t *pixels=heap_caps_aligned_alloc(16,raw_size,
                                     MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
            if(!pixels){
                static const char oom[]="@@DFSCREEN2 NACK psram\n";
                (void)h9_send_line(oom,sizeof(oom)-1);
                at=0;continue;
            }
            lv_image_dsc_t snap={0};
            lv_result_t captured=LV_RESULT_INVALID;
            if(esp_lv_adapter_lock(1200)==ESP_OK){
                /* Avoid calling LVGL APIs from USB while unprotected. */
                captured=lv_snapshot_take_to_buf(lv_screen_active(),
                     LV_COLOR_FORMAT_RGB565,&snap,pixels,(uint32_t)raw_size);
                esp_lv_adapter_unlock();
            }
            if(captured!=LV_RESULT_OK || snap.header.w!=480 ||
               snap.header.h!=480 || snap.header.stride!=960 ||
               snap.data_size>raw_size || snap.data!=pixels){
                heap_caps_free(pixels);
                static const char failed[]="@@DFSCREEN2 NACK snapshot_failed\n";
                (void)h9_send_line(failed,sizeof(failed)-1);
                at=0;continue;
            }
            uint32_t crc=esp_rom_crc32_le(0u,pixels,raw_size);
            char header[171];
            int hn=snprintf(header,sizeof(header),
              "@@DFSCREEN2 BEGIN source=lvgl_snapshot width=480 height=480 "
              "format=rgb565 bytes=460800 chunks=600 crc32=%08lx\n",
              (unsigned long)crc);
            bool transmitted=hn>0 && hn<(int)sizeof(header) &&
                             h9_send_line(header,(size_t)hn);
            for(unsigned seq=0;seq<600u && transmitted;seq++){
                /* 768 raw bytes => 1024 Base64 chars; stack below 2KiB. */
                uint8_t base64[1032]={0};size_t written=0;
                int result=mbedtls_base64_encode(base64,sizeof(base64),&written,
                                                 pixels+seq*768u,768u);
                if(result!=0){transmitted=false;break;}
                char output[1090];
                int n=snprintf(output,sizeof(output),
                       "@@DFSCREEN2 DATA index=%u b64=%s\n",seq,base64);
                if(n<=0||n>=(int)sizeof(output)||
                   !h9_send_line(output,(size_t)n)){
                    transmitted=false;break;
                }
            }
            if(transmitted){
                static const char done[]="@@DFSCREEN2 END count=600\n";
                (void)h9_send_line(done,sizeof(done)-1);
            }
            heap_caps_free(pixels);
            at=0;continue;
        }
        if(strncmp(command,"@@DFSD3 ",8)==0){
            if(!capturing && !speaking && !h10_receiving){
                r83_usb_command(command);
            }else{
                static const char busy[]="@@DFSD3 NACK reason=voice_busy\n";
                (void)h9_send_line(busy,sizeof(busy)-1);
            }
            at=0;continue;
        }
        if(strcmp(command,"@@DFVIS1 SNAPSHOT")==0){
            // Metadata only; serial port owner/permissions remain unchanged.
            char report[210];
            int n=snprintf(report,sizeof(report),
              "@@DFVIS1 drawn=%lu hidden=%lu offscreen=%lu "
              "bad_desc=%lu layer_conflict=%lu x1=%ld y1=%ld x2=%ld y2=%ld\n",
              (unsigned long)r71_drawn_frames,(unsigned long)r71_hidden,
              (unsigned long)r71_offscreen,(unsigned long)r71_bad_descriptor,
              (unsigned long)r71_overlay_conflict,
              (long)r71_x1,(long)r71_y1,(long)r71_x2,(long)r71_y2);
            if(n>0 && n<(int)sizeof(report))(void)h9_send_line(report,(size_t)n);
            at=0;continue;
        }
        /* R188 offline diagnostic candidate only; no automatic Wi-Fi at boot. */
        /* R191: user-requested memory receipt, no network configuration data. */
        if(strcmp(command,"@@DFWIFI4 MEM")==0){
            r62_wifi_state_t state={0};
            r62_wifi_snapshot(&state);
            char reply[260];
            int n=snprintf(reply,sizeof(reply),
              "@@DFWIFI4 MEM stage=%u raw=%d dma_min=%lu min_step=%u "
              "internal_min=%lu dma_now=%lu int_now=%lu int_largest=%lu "
              "psram_now=%lu wifi_ready=%u wifi_ip=%u pcm_underruns=%lu\n",
              (unsigned)state.diagnostic_stage,state.diagnostic_esp_error,
              (unsigned long)state.diagnostic_dma_min,
              (unsigned)state.diagnostic_min_stage,
              (unsigned long)state.diagnostic_internal_min,
              (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_DMA|MALLOC_CAP_INTERNAL),
              (unsigned long)heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
              (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
              (unsigned long)heap_caps_get_free_size(MALLOC_CAP_SPIRAM),
              (unsigned)state.ready,(unsigned)state.has_ip,
              (unsigned long)r37_pcm2_underruns);
            if(n>0 && n<(int)sizeof(reply))(void)h9_send_line(reply,(size_t)n);
            at=0;continue;
        }
        if(strcmp(command,"@@DFWIFI3 TRACE")==0){
            r62_wifi_state_t ws={0};
            r62_wifi_snapshot(&ws);
            char report[194];
            int n=snprintf(report,sizeof(report),
              "@@DFWIFI3 TRACE stage=%u raw=%d legacy=%d dma_at_fail=%lu internal_at_fail=%lu\n",
              (unsigned)ws.diagnostic_stage,ws.diagnostic_esp_error,ws.error,
              (unsigned long)ws.diagnostic_dma_largest,
              (unsigned long)ws.diagnostic_internal_largest);
            if(n>0 && n<(int)sizeof(report))(void)h9_send_line(report,(size_t)n);
            at=0;continue;
        }

        /* R198 explicit read-only scan progress, never log credentials. */
        if(strcmp(command,"@@DFWIFI2 STATUS")==0){
            r62_wifi_state_t w={0};r62_wifi_snapshot(&w);
            char output[220];
            int n=snprintf(output,sizeof(output),
              "@@DFWIFI2 STATUS ready=%u scanning=%u connecting=%u "
              "connected=%u ip=%u count=%d error=%d stage=%u raw=%d saved=%u setup=%u persist=%u rev=%lu sta=%u\n",
              (unsigned)w.ready,(unsigned)w.scanning,(unsigned)w.connecting,
              (unsigned)w.connected,(unsigned)w.has_ip,w.count,w.error,
              (unsigned)w.diagnostic_stage,w.diagnostic_esp_error,
              (unsigned)w.saved,(unsigned)w.needs_setup,(unsigned)w.persistence_stage,
              (unsigned long)w.persistence_generation,(unsigned)w.station_config_loaded);
            if(n>0 && n<(int)sizeof(output))(void)h9_send_line(output,(size_t)n);
            at=0;continue;
        }
        if(strncmp(command,"@@DFWIFI2 AP index=",19)==0){
            unsigned i=100;char tail=0;
            r62_wifi_state_t w={0};r62_wifi_snapshot(&w);
            if(sscanf(command+19,"%u%c",&i,&tail)==1 &&
               i<8u && i<(unsigned)w.count && !w.scanning){
                unsigned char b64[52]={0};size_t used=0;
                const size_t len=strnlen(w.ssid[i],32);
                if(mbedtls_base64_encode(b64,sizeof(b64),&used,
                     (const unsigned char*)w.ssid[i],len)==0){
                    char output[128];
                    int n=snprintf(output,sizeof(output),
                      "@@DFWIFI2 AP index=%u ssid_b64=%s rssi=%d\n",
                      i,(const char*)b64,w.signal[i]);
                    if(n>0 && n<(int)sizeof(output))
                        (void)h9_send_line(output,(size_t)n);
                }
            }else{
                static const char err[]="@@DFWIFI2 NACK no_such_ap_or_scanning\n";
                (void)h9_send_line(err,sizeof(err)-1);
            }
            at=0;continue;
        }
        if(strcmp(command,"@@DFWIFI2 SCAN")==0){
            if(capturing||speaking||h10_receiving||r37_pcm2_active||r83_transfer_active()){
                static const char busy[]="@@DFWIFI2 NACK busy_audio\n";
                (void)h9_send_line(busy,sizeof(busy)-1);
            }else{
                if(r62_wifi_scan()){
                    static const char ack[]="@@DFWIFI2 SCAN_QUEUED\n";
                    (void)h9_send_line(ack,sizeof(ack)-1);
                }else{
                    static const char fail[]="@@DFWIFI2 NACK scan_not_queued\n";
                    (void)h9_send_line(fail,sizeof(fail)-1);
                }
            }
            at=0;continue;
        }
        if(strcmp(command,"@@DFANIM1 DIAG")==0){
            // Only numeric state; no frames, audio, credentials or transcripts.
            char line[190];
            const uint32_t now=(uint32_t)xTaskGetTickCount();
            int n=snprintf(line,sizeof(line),
                "@@DFANIM1 DIAG beat=%lu age_ms=%lu frames=%lu hold=%lu "
                "fail=%lu capture=%u speaking=%u lan=%u sd_pause=%u sd_transfer=%u\n",
                (unsigned long)r322_anim_heartbeat,
                (unsigned long)((now-r322_anim_last_tick)*portTICK_PERIOD_MS),
                (unsigned long)r70_frames,(unsigned long)r322_anim_hold,
                (unsigned long)r322_anim_failures,(unsigned)capturing,
                (unsigned)speaking,(unsigned)r268_lan_busy,
                (unsigned)r154_sd_upload_pause_requested,
                (unsigned)r83_transfer_active());
            if(n>0 && n<(int)sizeof(line))(void)h9_send_line(line,(size_t)n);
            at=0;continue;
        }
        if(strcmp(command,"@@DFPERF2 SNAPSHOT")==0){
            char report[192];
            int n=snprintf(report,sizeof(report),
                "@@DFPERF2 n=%lu load_avg_us=%lu decode_avg_us=%lu "
                "lock_avg_us=%lu draw_avg_us=%lu backdrop_cached=%lu\n",
                (unsigned long)r510_perf_frames,
                (unsigned long)r510_avg_load_us,
                (unsigned long)r510_avg_decode_us,
                (unsigned long)r510_avg_lock_us,
                (unsigned long)r510_avg_draw_us,
                (unsigned long)r510_stage_ready);
            if(n>0 && n<(int)sizeof(report))
                (void)h9_send_line(report,(size_t)n);
            at=0;continue;
        }
        if(strcmp(command,"@@DFPERF1 SNAPSHOT")==0){
            // No secrets or device credentials. Read-only hardware counters.
            r62_wifi_state_t wifi={0};
            r62_wifi_snapshot(&wifi);
            char line[320];
            int n=snprintf(line,sizeof(line),
                "@@DFPERF1 uptime_ms=%lu frames=%lu decode_errors=%lu "
                "frame_last_ms=%lu frame_max_ms=%lu over125=%lu max_gap_ms=%lu "
                "opaque=%lu opaque_fail=%lu wifi_ready=%u wifi_scan=%u wifi_ip=%u "
                "wifi_error=%d internal_free=%lu internal_largest=%lu "
                "psram_free=%lu psram_largest=%lu pcm_underruns=%lu sd_ready=%u\n",
                (unsigned long)(xTaskGetTickCount()*portTICK_PERIOD_MS),
                (unsigned long)r70_frames,(unsigned long)r70_decoding_errors,
                (unsigned long)r70_frame_last_ms,(unsigned long)r70_frame_max_ms,
                (unsigned long)r70_frame_long,(unsigned long)r70_gap_max_ms,
                (unsigned long)r70_opaque_last,(unsigned long)r70_opaque_invalid,
                (unsigned)wifi.ready,(unsigned)wifi.scanning,
                (unsigned)wifi.has_ip,wifi.error,
                (unsigned long)heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
                (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
                (unsigned long)heap_caps_get_free_size(MALLOC_CAP_SPIRAM),
                (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM),
                (unsigned long)r37_pcm2_underruns,(unsigned)h12_sd_available());
            if(n>0 && n<(int)sizeof(line))(void)h9_send_line(line,(size_t)n);
            at=0;continue;
        }
        if(strcmp(command,"@@DFTELEMETRY1 GET")==0){
            char report[145];
            unsigned displayed_min=(r34_host_clock_minute+
                (unsigned)((xTaskGetTickCount()-r34_host_clock_tick)/
                    pdMS_TO_TICKS(60000)))%(24*60);
            int n=snprintf(report,sizeof(report),
                "@@DFTELEMETRY1 mac=%u battery_valid=%u present=%u percent=%u time_valid=%u hhmm=%04u\n",
                (unsigned)r268_usb_host_alive(),
                (unsigned)r34_bat_valid,(unsigned)r34_bat_present,r34_bat_percent,
                (unsigned)(r34_rtc_valid||r34_host_clock_valid),
                r34_rtc_valid?r34_hour*100u+r34_minute:
                              displayed_min/60*100u+displayed_min%60u);
            if(n>0&&n<(int)sizeof(report))(void)h9_send_line(report,(size_t)n);
            at=0;continue;
        }
#endif
        if(strcmp(command,"@@DFDEVICE1 VERSION")==0){
            static const char v[]="@@DFDEVICE1 VERSION=H13 role=usb_sd_exfat\n";
            (void)h9_send_line(v,sizeof(v)-1);
            at=0;continue;
        }
#ifdef DF_R225_LOCAL_OFFLINE
        if(strncmp(command,"@@DFVOICEFILE1 ",15)==0){
            if(strcmp(command,"@@DFVOICEFILE1 CAPS")==0){
                r225_voice_upload_handle(command,h9_send_line);
                at=0;continue;
            }
            if(!r154_sd_upload_paused || h12_use_sd ||
               !r224_sd_owned(R224_SD_USB,r229_usb_sd_lease) ||
               speaking || capturing || h10_receiving || r37_pcm2_active){
                static const char no[]="@@DFVOICEFILE1 NACK busy\n";
                (void)h9_send_line(no,sizeof(no)-1);
            }else{
                r225_voice_upload_handle(command,h9_send_line);
            }
            at=0;continue;
        }
        if(strcmp(command,"@@DFMN2 PROBE_ALLOC")==0){
            // Local bounded test of genuine MN5 + AFE allocation only;
            // USB cannot forge a speech hit or request any LLM action.
            if(speaking||capturing||h10_receiving||r37_pcm2_active||
               r37_pcm2_worker_running||r83_transfer_active()||
               r154_sd_upload_pause_requested||h13_sd_usb_active()){
                static const char busy[]="@@DFMN2 NACK busy\n";
                h9_send_line(busy,sizeof(busy)-1);
            }else if(!r185_wake_wait_released(2300)){
                static const char busy[]="@@DFMN2 NACK wake_mic_busy\n";
                h9_send_line(busy,sizeof(busy)-1);
                r185_wake_resume();
            }else{
                unsigned before=0,after=0,largest=0,recovered=0;
                int rc=r263_mn5_afe_alloc_probe(&before,&after,&largest,&recovered);
                r185_wake_resume();
                char line[172];
                int n=snprintf(line,sizeof(line),
                    "@@DFMN2 PROBED engine=mn5q8_cn afe=official rc=%d "
                    "psram_pre=%u psram_post=%u internal_post=%u "
                    "psram_recovered=%u\n",
                    rc,before,after,largest,recovered);
                if(n>0&&n<(int)sizeof(line))h9_send_line(line,(size_t)n);
            }
            at=0;continue;
        }
        if(strcmp(command,"@@DFMN1 STATUS")==0){
            unsigned tries=0,hits=0,heap=0,psram=0;int id=0,error=0;
            r259_read_diagnostics(&tries,&hits,&id,&error,&heap,&psram);
            char resp[180];
            int n=snprintf(resp,sizeof(resp),
                "@@DFMN1 STATE engine=mn5q8_cn trusted=esp32_mic "
                "tries=%u hits=%u last=%d error=%d reserve_internal=%u reserve_psram=%u\n",
                tries,hits,id,error,heap,psram);
            if(n>0&&n<(int)sizeof(resp))h9_send_line(resp,(size_t)n);
            at=0;continue;
        }
        if(strcmp(command,"@@DFOFFLINE1 CAPS")==0){
            static const char cap[]=
             "@@DFOFFLINE1 READY clips=10 wake=wn9_hilexin mode=offline\n";
            (void)h9_send_line(cap,sizeof(cap)-1);
            at=0;continue;
        }
        if(strcmp(command,"@@DFOFFLINE1 STATUS")==0){
            char resp[240];
            int n=snprintf(resp,sizeof(resp),
              "@@DFOFFLINE1 STATE wake_ready=%u wake_enabled=%u busy=%u last_id=%u last_result=%d sd_stage=%u sd_preload_rc=%d sd_stream_rc=%d cache=%u\n",
              (unsigned)r185_wake_ready(),(unsigned)r185_wake_enabled(),
              (unsigned)speaking,r225_last_clip,r225_last_rc,
              r228_sd_stage,r228_sd_preload_rc,r228_sd_stream_rc,
              (unsigned)r226_sd_wake_cached());
            if(n>0 && n<(int)sizeof(resp))h9_send_line(resp,(size_t)n);
            at=0;continue;
        }
        if(strncmp(command,"@@DFOFFLINE1 PLAY id=",21)==0){
            unsigned id=100;char extra=0;
            bool denied=sscanf(command,"@@DFOFFLINE1 PLAY id=%u%c",&id,&extra)!=1||
               id>=10 || speaking || capturing || loopback_busy ||
               r37_pcm2_active || h10_receiving ||
               r154_sd_upload_pause_requested || r225_voice_upload_active();
            // WakeNet is a live mic reader; generic busy hides slow handoff.
            bool released=!denied && r185_wake_wait_released(2300);
            if(denied || !released){
                // R231 diagnostic-only reason line; preserve original NACK.
                // No private audio/user content and no new UI entry.
                char detail[240];
                int dn=snprintf(detail,sizeof(detail),
                    "@@DFOFFLINE1 BLOCK invalid=%u speaking=%u capture=%u "
                    "loop=%u pcm2=%u h10=%u sd_req=%u voice_upload=%u "
                    "wake_mic=%u wake_read=%u handoff=%u\n",
                    (unsigned)(id>=10),(unsigned)speaking,(unsigned)capturing,
                    (unsigned)loopback_busy,(unsigned)r37_pcm2_active,
                    (unsigned)h10_receiving,(unsigned)r154_sd_upload_pause_requested,
                    (unsigned)r225_voice_upload_active(),
                    (unsigned)r185_wake_owns_mic(),(unsigned)r185_wake_read_inflight(),
                    (unsigned)!released);
                if(dn>0&&dn<(int)sizeof(detail))(void)h9_send_line(detail,(size_t)dn);
                if(!denied){
                    ESP_LOGW(TAG,"R231_SD_PLAY_WAKE_MIC_HANDOFF_TIMEOUT");
                    r185_wake_resume();
                }
                static const char no[]="@@DFOFFLINE1 NACK unavailable\n";
                (void)h9_send_line(no,sizeof(no)-1);
            }else{
                r225_requested_clip=id;
                r232_real_wake_greeting_pending=false;
                speaking=true;
                if(xTaskCreate(r185_wake_greeting_worker,
                    "r225_play",8192,NULL,5,NULL)==pdPASS){
                    static const char yes[]="@@DFOFFLINE1 ACCEPTED\n";
                    (void)h9_send_line(yes,sizeof(yes)-1);
                }else{speaking=false;r185_wake_resume();}
            }
            at=0;continue;
        }
#endif
        if(strncmp(command,"@@DFSD2 ",8)==0){
            // R154: a writer must first explicitly ask the animation owner
            // to release its SD reader and wait for an observed PAUSED ACK.
            if(strcmp(command,"@@DFSD2 PAUSE")==0){
                if(!capturing&&!speaking&&!h10_receiving&&!r37_pcm2_active
                   &&!r83_transfer_active()&&!h13_sd_usb_active()){
#ifdef DF_R225_LOCAL_OFFLINE
                    if(r225_voice_upload_active() ||
                       !r185_wake_wait_released(1500)){
                        static const char no[]="@@DFSD2 ERROR code=mic_busy\n";
                        (void)h9_send_line(no,sizeof(no)-1);
                        at=0;continue;
                    }
#endif
                    if(r229_usb_sd_lease==0 &&
                        !r224_sd_claim(R224_SD_USB,&r229_usb_sd_lease)){
                        static const char busy[]="@@DFSD2 ERROR code=sd_owner_busy\n";
                        (void)h9_send_line(busy,sizeof(busy)-1);
                    }else{
                        r154_sd_upload_pause_requested=true;
                        static const char ack[]="@@DFSD2 PAUSE_QUEUED\n";
                        (void)h9_send_line(ack,sizeof(ack)-1);
                    }
                }else{
                    static const char busy[]="@@DFSD2 ERROR code=audio_priority\n";
                    (void)h9_send_line(busy,sizeof(busy)-1);
                }
            }else if(strcmp(command,"@@DFSD2 PAUSE_STATUS")==0){
                const char *msg=r154_sd_upload_paused?
                  "@@DFSD2 PAUSED reader_released=1\n":
                  "@@DFSD2 PAUSE_PENDING reader_released=0\n";
                (void)h9_send_line(msg,strlen(msg));
            }else if(strcmp(command,"@@DFSD2 RESUME")==0){
                if(h13_sd_usb_active()
#ifdef DF_R225_LOCAL_OFFLINE
                || r225_voice_upload_active()
#endif
                ){
                    static const char busy[]="@@DFSD2 ERROR code=write_active\n";
                    (void)h9_send_line(busy,sizeof(busy)-1);
                }else if(!r224_sd_owned(R224_SD_USB,r229_usb_sd_lease)){
                    static const char no[]="@@DFSD2 ERROR code=sd_lease_missing\n";
                    (void)h9_send_line(no,sizeof(no)-1);
                }else{
                    r154_sd_upload_pause_requested=false;
                    r154_sd_upload_paused=false;
                    h13_boot_idle_pending=true; // restore protected m000
                    r224_sd_release(R224_SD_USB,r229_usb_sd_lease);
                    r229_usb_sd_lease=0;
#ifdef DF_R225_LOCAL_OFFLINE
                    r185_wake_resume();
#endif
                    static const char done[]="@@DFSD2 RESUMED idle_pending=1\n";
                    (void)h9_send_line(done,sizeof(done)-1);
                }
            }else if(!r154_sd_upload_paused || h12_use_sd ||
                     !r224_sd_owned(R224_SD_USB,r229_usb_sd_lease) ||
                     speaking||capturing||h10_receiving||r37_pcm2_active){
                static const char busy[]="@@DFSD2 ERROR code=device_busy\n";
                (void)h9_send_line(busy,sizeof(busy)-1);
            }else{
                h13_sd_usb_handle(command);
            }
            at=0;continue;
        }
#endif
#ifdef DF_H12_SD_ANIM
        if(strcmp(command,"@@DFMOTION1 STATUS")==0){
            char report[150];
            int n=snprintf(report,sizeof(report),
                "@@DFMOTION1 STATUS use_sd=%u request=%lu handled=%lu rendered=%lu id=m%03u\n",
                (unsigned)(h12_use_sd?1:0),(unsigned long)h12_req_seq,
                (unsigned long)h12_done_seq,(unsigned long)h12_rendered_seq,
                h12_rendered_id);
            if(n>0&&n<(int)sizeof(report))(void)h9_send_line(report,(size_t)n);
            at=0;continue;
        }
        // R121: USB-only self-test of the EXACT original local touch branch.
        // Only when idle, never activates microphone, DSH, SD writes or Wi-Fi.
        // QUEUED is not a frame receipt; later @@DFTOUCH1 APPLIED is required.
#ifdef DF_H28_HOLD_MIC
        if(strcmp(command,"@@DFMOTION1 SELFTEST_TOUCH")==0){
            bool allowed=!h28_touch_requested && !h28_touch_return_idle &&
                !capturing && !speaking && !h10_receiving &&
                h12_req_seq==h12_done_seq;
#ifdef DF_H11_PREVIEW_STATES
            allowed=allowed && strcmp(h11_current_state.phase,"idle")==0;
#endif
            if(allowed){
                h30_touch_requested_at=xTaskGetTickCount();
                h28_touch_requested=true;
                static const char queued[]="@@DFMOTION1 SELFTEST_QUEUED\n";
                (void)h9_send_line(queued,sizeof(queued)-1);
            }else{
                static const char blocked[]="@@DFMOTION1 SELFTEST_BUSY\n";
                (void)h9_send_line(blocked,sizeof(blocked)-1);
            }
            at=0;continue;
        }
#endif
        if(strcmp(command,"@@DFMOTION1 CAPS")==0){
            if(h12_sd_verify_selected35()==0){
                static const char ready[]="@@DFMOTION1 READY profile=selected35 store=sd\n";
                (void)h9_send_line(ready,sizeof(ready)-1);
            }else{
                static const char missing[]="@@DFMOTION1 UNAVAILABLE reason=selected35_incomplete\n";
                (void)h9_send_line(missing,sizeof(missing)-1);
            }
            at=0;continue;
        }
        if(strncmp(command,"@@DFMOTION1 SELECT ",19)==0){
#ifdef DF_H13_SD_UPLOAD
            if(h13_sd_usb_active()){
                static const char busy[]="@@DFMOTION1 REJECTED upload_in_progress\n";
                (void)h9_send_line(busy,sizeof(busy)-1);
                at=0;continue;
            }
#endif
            unsigned seq=0,id=0;char extra=0;
            if(sscanf(command,"@@DFMOTION1 SELECT seq=%u id=m%u%c",&seq,&id,&extra)==2 &&
                seq>h12_req_seq && seq<=999999999U && h12_selected_id(id) &&
                h12_sd_available() && (h12_req_seq==0||h12_req_seq==h12_done_seq)){
                h12_req_id=id;h12_req_seq=seq;
                static const char queued[]="@@DFMOTION1 QUEUED\n";
                (void)h9_send_line(queued,sizeof(queued)-1);
            }else{
                static const char bad[]="@@DFMOTION1 REJECTED\n";
                (void)h9_send_line(bad,sizeof(bad)-1);
            }
            at=0;continue;
        }
#endif
#ifdef DF_H11_PREVIEW_STATES
        if(strcmp(command,"@@DFSTATE1 CAPS")==0){
            static const char ready[]="@@DFSTATE1 READY phases=9\n";
            (void)h9_send_line(ready,sizeof(ready)-1);
            at=0;continue;
        }
        if(strncmp(command,"@@DFSTATE1 SET ",15)==0){
            uint32_t seq=0;const char*phase=NULL;
            if(df_h11_parse_state(command,&h11_current_state,&seq,&phase)==0){
                // ACK means status text applied. It does NOT mean a motion
                // played; SD selected35 renderer is still unavailable.
#ifdef DF_H28_HOLD_MIC
                ui_status(h28_ui_phase_text(phase));
#else
                ui_status(phase);
#endif
                df_h11_commit_state(&h11_current_state,seq,phase);
#ifdef DF_R33_BOARD_UI
                r33_error_since=strcmp(phase,"error")==0?xTaskGetTickCount():0;
                snprintf(r50_link_phase,sizeof(r50_link_phase),"%s",phase);
                if(strcmp(phase,"listening")==0){
                    r50_progress=1;r50_dsh_seen=false;r51_last_stopped=false;
                    snprintf(r50_link_error,sizeof(r50_link_error),"none");
                }else if(strcmp(phase,"transcribing")==0){
                    if(r50_progress<2)r50_progress=2;
                }else if(strcmp(phase,"thinking")==0 ||
                         strcmp(phase,"tool_pending")==0 ||
                         strcmp(phase,"approval_pending")==0){
                    r50_dsh_seen=true;
                    if(r50_progress<3)r50_progress=3;
                }else if(strcmp(phase,"voice_generating")==0){
                    if(r50_progress<4)r50_progress=4;
                }else if(strcmp(phase,"speaking")==0){
                    if(r50_progress<5)r50_progress=5;
                }
#endif
#ifdef DF_H28_HOLD_MIC
                if(strcmp(phase,"idle")==0)h28_last_idle_stage_tick=(uint32_t)xTaskGetTickCount();
#endif
                char ack[90];
                int n=snprintf(ack,sizeof(ack),
                    "@@DFSTATE1 APPLIED seq=%u phase=%s\n",(unsigned)seq,phase);
                if(n>0 && n<(int)sizeof(ack)) (void)h9_send_line(ack,(size_t)n);
            }else{
                static const char bad[]="@@DFSTATE1 REJECTED\n";
                (void)h9_send_line(bad,sizeof(bad)-1);
            }
            at=0;continue;
        }
#endif
#ifdef DF_R46_PCM2_ONLY
        if(strncmp(command,"@@DFPCM2 ",9)==0){
            r36_mac_seen_at=xTaskGetTickCount();
            r37_pcm2_control(command);
            at=0;continue;
        }
#endif
        if(strncmp(command,"@@DFPCM1 ",9)==0){
            h10_dynamic_command(command);
            at=0;
            continue;
        }
        if(strcmp(command,"@@DFVOICE1 ARM")==0 && !speaking && !capturing && !h10_receiving){
            mic_host_deadline=xTaskGetTickCount()+pdMS_TO_TICKS(HOST_ARM_TIMEOUT_MS);
            mic_host_armed=true;
            printf("@@DFVOICE1 ARMED\n");fflush(stdout);
            ESP_LOGI(TAG,"H8_HOST_ARMED for=180_seconds");
        }else if(strcmp(command,"@@DFVOICE1 DISARM")==0){
            mic_host_armed=false;
            printf("@@DFVOICE1 DISARMED\n");fflush(stdout);
            ESP_LOGI(TAG,"H8_HOST_DISARMED");
        }else if(strcmp(command,"@@DFVOICE1 LOOPBACK")==0 &&
                 !speaking && !capturing && !loopback_busy){
            loopback_busy=true;
            if(xTaskCreate(h9_usb_loopback,"h9_loop",8192,NULL,5,NULL)!=pdPASS){
                loopback_busy=false;
                ESP_LOGE(TAG,"H9_LOOPBACK_TASK_FAILED");
            }
        }else if(strcmp(command,"@@DFVOICE1 PLAY")==0 && !speaking && !capturing && !loopback_busy){
            speaking=true;
            if(xTaskCreate(voice_worker,"h7_voice",VOICE_TASK_STACK_BYTES,NULL,5,NULL)!=pdPASS)
                speaking=false;
        }
        at=0;
        } // byte_i: each individual protocol line still has one handler
    }
}
#ifdef DF_H28_HOLD_MIC
static const char *h28_ui_phase_text(const char *phase){
    if(strcmp(phase,"idle")==0)return "待机中 · 点击录音";
    if(strcmp(phase,"listening")==0)return "正在聆听";
    if(strcmp(phase,"transcribing")==0)return "正在识别语音";
    if(strcmp(phase,"thinking")==0)return "正在思考";
    if(strcmp(phase,"tool_pending")==0)return "正在处理请求";
    if(strcmp(phase,"approval_pending")==0)return "请在 Mac 端确认";
    if(strcmp(phase,"voice_generating")==0)return "正在合成语音";
    if(strcmp(phase,"speaking")==0)return "正在播报";
    if(strcmp(phase,"error")==0)return "操作失败，请重试";
    return "待机中 · 点击录音";
}
#endif
void app_main(void){
    r251_boot_trace_start();
#ifdef DF_R185_WN9
    // Read-only per-boot correlation ID; never persisted to NVS/SD.
    // Entropy may be limited without Wi-Fi; not an authentication secret.
    r228_wake_boot_epoch=((uint64_t)esp_random()<<32)|(uint64_t)esp_random();
    if(!r228_wake_boot_epoch)r228_wake_boot_epoch=1;
    r228_wake_seq=0;
#endif
    ESP_LOGI(TAG,"H10_DUPLEX_PCM_LOCAL_USB_NO_AUTO_MIC");
    h28_last_idle_stage_tick=(uint32_t)xTaskGetTickCount();
    h28_last_bonus_tick=h28_last_idle_stage_tick;
    const size_t cap=SPRITE_W*SPRITE_W*3u;
    raw_frame=heap_caps_malloc(cap,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    delta=heap_caps_malloc(cap,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    compressed=heap_caps_malloc(R71_DFSP_COMPRESSED_MAX,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    frame_rgb=heap_caps_malloc(SPRITE_W*SPRITE_W*2u,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if(!raw_frame||!delta||!compressed||!frame_rgb){
        ESP_LOGE(TAG,"ANIMATION_PSRAM_ALLOCATION_FAILED");return;
    }
    image_desc.header.magic=LV_IMAGE_HEADER_MAGIC;
    image_desc.header.cf=LV_COLOR_FORMAT_RGB565;
    image_desc.header.w=SPRITE_W;image_desc.header.h=SPRITE_W;
    image_desc.data_size=SPRITE_W*SPRITE_W*2u;
    image_desc.data=frame_rgb;
    dfsp_stage_background(frame_rgb,SPRITE_W,SPRITE_W);
    /* Unified MN5 CPU isolation (actual Waveshare BSP default was LVGL
     * priority6 unpinned; it could preempt the priority4 model on CPU1).
     * Keep exact panel rotation/tearing/touch parameters used by BSP.
     * Feed mic on CPU0 priority6, draw LVGL on CPU0 priority4,
     * animation render on CPU0 priority3, MN5 alone on CPU1 priority4.
     */
    bsp_display_cfg_t r430_display_cfg={
        .lv_adapter_cfg=ESP_LV_ADAPTER_DEFAULT_CONFIG(),
        .rotation=ESP_LV_ADAPTER_ROTATE_0,
        .tear_avoid_mode=ESP_LV_ADAPTER_TEAR_AVOID_MODE_NONE,
        .touch_flags={.swap_xy=1,.mirror_x=0,.mirror_y=1}
    };
    r430_display_cfg.lv_adapter_cfg.task_core_id=0;
    r430_display_cfg.lv_adapter_cfg.task_priority=4;
    lv_display_t *r296_display=
        bsp_display_start_with_config(&r430_display_cfg);
    if(!r296_display){
        ESP_LOGE(TAG,"LCD_INIT_FAILED");return;
    }
    if(esp_lv_adapter_lock(-1)!=ESP_OK)return;
    lv_display_add_event_cb(r296_display,r296_display_event_cb,LV_EVENT_REFR_READY,NULL);
    lv_display_add_event_cb(r296_display,r296_display_event_cb,LV_EVENT_FLUSH_WAIT_FINISH,NULL);
    lv_obj_t *screen=lv_screen_active();
    lv_obj_set_style_bg_opa(screen,LV_OPA_COVER,0);
    lv_obj_set_style_bg_color(screen,lv_color_hex(0xFFFFFF),0);
    lv_obj_set_style_text_color(screen,lv_color_hex(0x193653),0);
    lv_obj_t *title=lv_label_create(screen);
#ifdef DF_H13_SD_UPLOAD
    lv_label_set_text(title,"DeepSeek");
#elif defined(DF_H12_SD_ANIM)
    lv_label_set_text(title,"DAFEIYU   /   H12");
#else
    lv_label_set_text(title,"DAFEIYU   /   H10");
#endif
    lv_obj_set_style_text_font(title,&lv_font_montserrat_22,0);
    lv_obj_t *brand=lv_label_create(screen);
    // Tiny built-in CJK subset omits the glyphs 肥 / 鱼. Use a fully
    // supported Latin brand now rather than rendering broken squares.
    lv_label_set_text(brand,"DAFEIYU");
    lv_obj_set_style_text_font(brand,&lv_font_montserrat_16,0);
    lv_obj_set_style_text_color(brand,lv_color_hex(0x2873B9),0);
    lv_obj_align(brand,LV_ALIGN_TOP_MID,0,10);
    lv_obj_align(title,LV_ALIGN_TOP_MID,0,30);
    lv_obj_add_flag(title,LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(brand,LV_OBJ_FLAG_HIDDEN);
    r33_header=lv_label_create(screen);
    lv_label_set_text(r33_header,"离线");
    lv_obj_set_style_text_font(r33_header,&lv_font_montserrat_16,0);
    lv_obj_set_style_text_color(r33_header,lv_color_hex(0x507A92),0);
    lv_obj_align(r33_header,LV_ALIGN_TOP_LEFT,38,24);
    r36_mac_dot=lv_obj_create(screen);
    lv_obj_remove_style_all(r36_mac_dot);
    lv_obj_set_size(r36_mac_dot,10,10);
    lv_obj_set_style_radius(r36_mac_dot,LV_RADIUS_CIRCLE,0);
    lv_obj_set_style_bg_color(r36_mac_dot,lv_color_hex(0xB2BDC8),0);
    lv_obj_set_style_bg_opa(r36_mac_dot,LV_OPA_COVER,0);
    lv_obj_align(r36_mac_dot,LV_ALIGN_TOP_LEFT,20,31);
    r36_clock_label=lv_label_create(screen);
    lv_label_set_text(r36_clock_label,"--:--");
    lv_obj_set_style_text_font(r36_clock_label,&lv_font_montserrat_20,0);
    lv_obj_set_style_text_color(r36_clock_label,lv_color_hex(0x385C76),0);
    lv_obj_align(r36_clock_label,LV_ALIGN_TOP_MID,0,20);
    r36_battery_shell=lv_obj_create(screen);
    lv_obj_remove_style_all(r36_battery_shell);
    lv_obj_set_size(r36_battery_shell,30,17);
    lv_obj_set_style_border_width(r36_battery_shell,2,0);
    lv_obj_set_style_border_color(r36_battery_shell,lv_color_hex(0x52728D),0);
    lv_obj_set_style_radius(r36_battery_shell,4,0);
    lv_obj_align(r36_battery_shell,LV_ALIGN_TOP_RIGHT,-70,28);
    r36_battery_fill=lv_obj_create(r36_battery_shell);
    lv_obj_remove_style_all(r36_battery_fill);
    lv_obj_set_height(r36_battery_fill,9);
    lv_obj_set_width(r36_battery_fill,0);
    lv_obj_set_style_bg_color(r36_battery_fill,lv_color_hex(0x5AAB96),0);
    lv_obj_set_style_bg_opa(r36_battery_fill,LV_OPA_COVER,0);
    lv_obj_set_style_radius(r36_battery_fill,2,0);
    lv_obj_align(r36_battery_fill,LV_ALIGN_LEFT_MID,2,0);
    // Keep the existing 30x17 battery outline and percentage position.
    // Charge icon is PMU-backed; external power with full battery uses USB,
    // not a false charging lightning bolt.
    r277_power_icon=lv_label_create(r36_battery_shell);
    lv_label_set_text(r277_power_icon,LV_SYMBOL_CHARGE);
    lv_obj_set_style_text_font(r277_power_icon,LV_FONT_DEFAULT,0);
    lv_obj_set_style_text_color(r277_power_icon,lv_color_hex(0x154F7C),0);
    lv_obj_center(r277_power_icon);
    lv_obj_add_flag(r277_power_icon,LV_OBJ_FLAG_HIDDEN);
    r33_battery=lv_label_create(screen);
    lv_label_set_text(r33_battery,"--");
    lv_obj_set_style_text_font(r33_battery,&lv_font_montserrat_16,0);
    lv_obj_set_style_text_color(r33_battery,lv_color_hex(0x507A92),0);
    lv_obj_align(r33_battery,LV_ALIGN_TOP_RIGHT,-13,25);
    picture=lv_image_create(screen);
    lv_image_set_src(picture,&image_desc);
    lv_image_set_pivot(picture,120,220); // anchored near feet
    lv_obj_add_flag(picture,LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(picture,r133_on_avatar_drag,LV_EVENT_PRESSED,NULL);
    lv_obj_add_event_cb(picture,r133_on_avatar_drag,LV_EVENT_PRESSING,NULL);
    lv_obj_add_event_cb(picture,r133_on_avatar_drag,LV_EVENT_RELEASED,NULL);
    lv_obj_add_event_cb(picture,r133_on_avatar_drag,LV_EVENT_PRESS_LOST,NULL);
    lv_obj_add_event_cb(picture,h28_on_avatar_tap,LV_EVENT_SHORT_CLICKED,NULL);
    lv_obj_set_size(picture,240,240);
    lv_obj_align(picture,LV_ALIGN_TOP_LEFT,70,113);
    lv_obj_t *button=lv_button_create(screen);
    lv_obj_set_size(button,58,58);
    lv_obj_align(button,LV_ALIGN_TOP_RIGHT,-16,138);
    lv_obj_set_style_shadow_width(button,18,0);
    lv_obj_set_style_shadow_color(button,lv_color_hex(0x86B8EE),0);
    lv_obj_set_style_shadow_opa(button,LV_OPA_30,0);
    lv_obj_set_style_radius(button,LV_RADIUS_CIRCLE,0);
    lv_obj_set_style_bg_color(button,lv_color_hex(0x2E73EA),0);
    lv_obj_add_event_cb(button,h28_on_mic_button,LV_EVENT_PRESSED,NULL);
    lv_obj_add_event_cb(button,h28_on_mic_button,LV_EVENT_RELEASED,NULL);
    lv_obj_add_event_cb(button,h28_on_mic_button,LV_EVENT_PRESS_LOST,NULL);
    lv_obj_set_style_bg_color(button,lv_color_hex(0xFFFFFF),0);
    lv_obj_set_style_border_width(button,1,0);
    lv_obj_set_style_border_color(button,lv_color_hex(0xC9E3EF),0);
    lv_obj_set_style_radius(button,16,0);
    lv_obj_set_style_shadow_width(button,0,0);
    lv_obj_set_style_bg_color(button,lv_color_hex(0xDDEFF7),LV_STATE_PRESSED);
    lv_obj_t *label=lv_label_create(button);
    lv_label_set_text(label,""); // icon-only, no long button caption
    lv_obj_set_style_text_font(label,&lv_font_montserrat_20,0);
    lv_obj_set_style_text_color(label,lv_color_hex(0xFFFFFF),0);
    lv_obj_center(label);
    // One transparent, center-aligned mic; retains R36 button location and
    // presses. Short tap toggles Voice3; recording displays the original STOP.
    r33_mic_button=button;
    r33_mic_stop=lv_label_create(button);
    lv_label_set_text(r33_mic_stop,"STOP");
    lv_obj_set_style_text_font(r33_mic_stop,&lv_font_montserrat_16,0);
    lv_obj_set_style_text_color(r33_mic_stop,lv_color_hex(0xC85164),0);
    lv_obj_center(r33_mic_stop);
    lv_obj_add_flag(r33_mic_stop,LV_OBJ_FLAG_HIDDEN);
    r46_mic_img=lv_image_create(button);
    lv_image_set_src(r46_mic_img,&r46_mic_dsc);
    lv_obj_set_size(r46_mic_img,R42_MIC_W,R42_MIC_W);
    lv_obj_center(r46_mic_img);
    lv_obj_remove_flag(r46_mic_img,LV_OBJ_FLAG_CLICKABLE);
    ESP_LOGI(TAG,"R46_MIC_ICON_ONLY_READY source=single44 parent=R36");
    status_label=lv_label_create(screen);
    lv_label_set_text(status_label,"Hold the mic to speak");
    lv_obj_set_style_text_color(status_label,lv_color_hex(0x193653),0);
    lv_obj_set_style_text_font(status_label,&lv_font_montserrat_16,0);
    lv_obj_set_size(status_label,436,40);
    lv_obj_set_style_bg_color(status_label,lv_color_hex(0xFFFFFF),0);
    lv_obj_set_style_bg_opa(status_label,LV_OPA_COVER,0);
    lv_obj_set_style_radius(status_label,11,0);
    lv_obj_set_style_pad_left(status_label,12,0);
    lv_obj_set_style_pad_top(status_label,8,0);
    lv_obj_align(status_label,LV_ALIGN_BOTTOM_MID,0,-13);
    lv_obj_set_style_text_font(status_label,&lv_font_montserrat_16,0);
    lv_label_set_text(status_label,"点击录音开始对话");
    r57_style_home(screen,button,label);
    // A descriptor check before releasing the LVGL lock exposes missing
    // glyphs even when the camera cannot resolve 16px on-device text.
    lv_font_glyph_dsc_t r58_glyph = {0};
    bool r58_zh = lv_font_get_glyph_dsc(&lv_font_r57_cn_16,
                                        &r58_glyph,0x5F55,0);
    bool r58_label = lv_font_get_glyph_dsc(&lv_font_r57_cn_20,
                                           &r58_glyph,0x97F3,0);
    ESP_LOGI(TAG,"R58_FONT_GLYPH_PROOF lu=%u yin=%u bpp=4 raw",
             (unsigned)r58_zh,(unsigned)r58_label);
    bool r59_colon=lv_font_get_glyph_dsc(&lv_font_r57_cn_16,&r58_glyph,0xFF1A,0);
    bool r59_return=lv_font_get_glyph_dsc(&lv_font_r57_cn_16,&r58_glyph,0x8FD4,0);
    bool r59_empty=lv_font_get_glyph_dsc(&lv_font_r57_cn_16,&r58_glyph,0x6682,0);
    ESP_LOGI(TAG,"R59_CJK_COLON_RETURN_EMPTY colon=%u return=%u empty=%u",
         (unsigned)r59_colon,(unsigned)r59_return,(unsigned)r59_empty);
    ESP_LOGI(TAG,"R59_WHITE_STAGE no_home_menu mic_icon_small");
    lv_timer_create(r33_update_status,1000,NULL);
    lv_timer_create(r279_lan_ui_tick,130,NULL);
    esp_lv_adapter_unlock();
    r34_init_telemetry();
    ESP_LOGI(TAG,"H10_DISPLAY_READY avatar_native240 voice_button=1 long_hold_mic=1");
#ifdef DF_H12_SD_ANIM
    // Leave the card's partitioning and filesystem untouched on startup.
    (void)h12_sd_initialize_read_only();
#ifdef DF_H13_SD_UPLOAD
    if(h12_sd_verify_selected35()==0){
        h13_boot_idle_pending=true;
        ESP_LOGI(TAG,"H13_BOOT_IDLE_ASSET_READY complete35");
    }else{
        ESP_LOGI(TAG,"H13_BOOT_EMBEDDED_FALLBACK incomplete35");
    }
#endif
#endif
#if defined(DF_H13_SD_UPLOAD) && defined(DF_R33_BOARD_UI)
    // Safe first-boot SD provisioning before any animation/USB SD consumers.
    ESP_LOGI(TAG,"R57_SD_PRESETS_DEFERRED startup_no_write_safety_gate");
#endif
    r133_rules_init();
    r150_rules_init(); // read old map1, prefer opt-in map2; never rewrite old key
    if(xTaskCreatePinnedToCore(animation_worker,"h5_anim",
          ANIMATION_TASK_STACK_BYTES,NULL,3,NULL,0)!=pdPASS)
        ESP_LOGE(TAG,"ANIMATION_TASK_CREATE_FAILED");
    if(xTaskCreate(usb_control_worker,"h8_usb",COMMAND_STACK_BYTES,NULL,3,NULL)!=pdPASS)
        ESP_LOGE(TAG,"H8_USB_CONTROL_TASK_FAILED");
    // R268: start WN9 before any saved-Wi-Fi auto-connect task. Offline
    // recognition must coexist with local radio; no credentials => radio off.
#if defined(DF_R185_WN9) && !defined(DF_R434_MAC_PREWAKE_ONLY)
    if(!microphone)microphone=r248_microphone_init_with_gain();
    if(!microphone || !r185_wake_start(microphone,r185_can_listen,
                                      r185_wake_detected)){
        ESP_LOGW(TAG,"R185_WN9_UNAVAILABLE_TOUCH_MODE_UNCHANGED");
    }else{
        // R261: standalone power-on must not depend on a Mac USB message.
        // WakeNet remains local, does not create a DSH request or transmit
        // audio. Only a verified user speech hit may enter the official
        // MultiNet offline window. A later explicit DISABLE still works.
        r185_wake_enable(true);
        ESP_LOGI(TAG,"R261_STANDALONE_WAKENET_AUTOSTART no_mac_required=1");
    }
#endif
    // R268: WN9 initializes its verified model asynchronously on core0.
    // Do not allocate Wi-Fi task stacks or driver heap until the official WN9
    // model is actually ready. Earlier parallel boot could starve the >=112KiB
    // internal-heap pre-model gate and silently degrade to touch-only.
    // Bound the wait; on WN9 failure retain offline SD/touch and allow an
    // explicit UI Wi-Fi scan to initialize the radio later.
#if defined(DF_R185_WN9) && !defined(DF_R434_MAC_PREWAKE_ONLY)
    bool r268_wake_boot_ready=false;
    for(unsigned r268_gate=0;r268_gate<120u;r268_gate++){
        if(r185_wake_ready()&&r185_wake_enabled()){
            r268_wake_boot_ready=true;break;
        }
        vTaskDelay(pdMS_TO_TICKS(100));
    }
    // Pair once after WN9 has initialized, BEFORE Wi-Fi allocates its RAM.
    // Neither the LVGL touch callback nor the Wi-Fi init hot path reads NVS.
    r276_lan_paired_cached=r268_lan_paired();
    if(r268_wake_boot_ready){
        ESP_LOGI(TAG,"R268_WIFI_BOOT_AFTER_REAL_WN9_READY");
        r62_wifi_begin();
    }else{
        ESP_LOGW(TAG,"UNIFIED_WIFI_AUTO_DEFERRED_CUSTOM_WAKE_NOT_READY");
    }
#else
    r276_lan_paired_cached=r268_lan_paired();
    r62_wifi_begin();
#endif
    ESP_LOGI(TAG,"R276_LAN_PAIR_CACHED valid=%u",(unsigned)r276_lan_paired_cached);
#ifdef DF_R434_MAC_PREWAKE_ONLY
    if(xTaskCreatePinnedToCore(r434_mac_prewake_worker,"r434_prewake",
          14*1024,NULL,4,NULL,1)!=pdPASS)
      ESP_LOGE(TAG,"R434_PREWAKE_WORKER_CREATE_FAILED");
    else
      ESP_LOGI(TAG,"R434_MAC_KWS_PREWAKE_READY paired=%u",(unsigned)r276_lan_paired_cached);
#endif
}
