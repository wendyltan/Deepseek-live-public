// SPDX-License-Identifier: MIT
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "freertos/FreeRTOS.h"
#include "lvgl.h"

#define R302_BREATH_MAGIC 0x5292B31Au
typedef struct {
 uint32_t magic,pulses,wake_pulses,mic_pulses,lock_misses,restores;
} r302_breath_trace_t;
typedef struct {
 bool active;
 int32_t original_scale;
 TickType_t last_pulse;
 uint8_t step;
} r302_breath_state_t;

extern volatile r302_breath_trace_t r302_trace;
void r302_breathe_complete_image(r302_breath_state_t *state,bool enabled,bool is_wake,lv_obj_t *picture);
