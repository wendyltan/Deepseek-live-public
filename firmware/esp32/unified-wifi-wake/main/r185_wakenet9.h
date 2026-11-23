#pragma once
#include <stdbool.h>
#include "esp_codec_dev.h"
typedef bool (*r185_listen_allowed)(void);
typedef void (*r185_detect_event)(void);
bool r185_wake_start(esp_codec_dev_handle_t mic,
                    r185_listen_allowed can,r185_detect_event wake);
void r185_wake_enable(bool on);
void r185_wake_pause(void);
void r185_wake_resume(void);
bool r185_wake_wait_released(unsigned timeout_ms);
bool r185_wake_ready(void);
const char *r185_wake_active_model(void);
bool r185_wake_enabled(void);
bool r185_wake_owns_mic(void);
bool r185_wake_read_inflight(void);
/* Diagnostic-only, independent counters; no PCM, user text or audio retained. */
typedef struct {
 unsigned read_enter,read_ok,read_error,gate_skip;
 unsigned detect_enter,detect_return,detected,open_fail;
 unsigned phase,phase_age_ms;
} r242_wake_stage;
void r242_wake_stage_read(r242_wake_stage *out);
/* R247: numeric-only, completed ~10s window. No PCM is retained. */
typedef struct {
 unsigned model_chunk, model_channels, model_rate;
 unsigned window_ms, frames, read_us_sum, read_us_max;
 unsigned detect_us_sum, detect_us_max, peak_16bit;
 unsigned loud_frames, clipped_frames;
} r247_wake_speed;
void r247_wake_speed_read(r247_wake_speed *out);
