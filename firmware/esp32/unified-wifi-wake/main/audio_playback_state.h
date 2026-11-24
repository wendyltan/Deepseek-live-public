// SPDX-License-Identifier: MIT
#pragma once
#include "freertos/FreeRTOS.h"
#include "lvgl.h"
#include "esp_codec_dev.h"
#include "r268_lan_transport.h"

#define R281_DIAG_MAGIC 0x52783281u
typedef struct {
 uint32_t magic, sessions, voice_phase_events, lvgl_ticks, status_commits;
 uint32_t avatar_frames_during_wifi, speaker_blocks, slow_codec_blocks;
 uint32_t max_codec_write_us, max_source_peak, clipped_source_samples;
} r281_ui_audio_trace_t;
extern esp_codec_dev_handle_t speaker;
extern uint8_t volume;
extern volatile bool r303_wss_audio_offered;
extern volatile bool r435_mouth_first_frame_ready;
extern volatile r281_ui_audio_trace_t r281_trace;
extern volatile uint32_t r47_motion_epoch;
extern volatile uint8_t r47_audio_motion;
