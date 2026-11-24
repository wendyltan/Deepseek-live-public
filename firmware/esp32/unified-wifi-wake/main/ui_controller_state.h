// SPDX-License-Identifier: MIT
#pragma once
#include "freertos/FreeRTOS.h"
#include "lvgl.h"
#include "esp_codec_dev.h"
#include "r268_lan_transport.h"

bool r257_local_voice_from_touch(unsigned clip);
bool r268_usb_host_alive(void);
extern bool r36_last_turn_ok;
extern bool speaking;
extern lv_obj_t *picture;
extern lv_obj_t *r33_battery;
extern lv_obj_t *r33_header;
extern lv_obj_t *r33_mic_stop;
extern lv_obj_t *r36_battery_shell;
extern lv_obj_t *r36_brightness_pct;
extern lv_obj_t *r36_brightness_slider;
extern lv_obj_t *r36_clock_label;
extern lv_obj_t *r36_mac_dot;
extern lv_obj_t *r36_volume_pct;
extern lv_obj_t *r36_volume_slider;
extern lv_obj_t *r46_mic_img;
extern lv_obj_t *status_label;
extern uint8_t r33_brightness;
extern uint8_t volume;
extern volatile TickType_t h30_touch_requested_at;
extern volatile bool capturing;
extern volatile bool h10_receiving;
extern volatile bool h28_mic_press_session;
extern volatile bool h28_touch_requested;
extern volatile bool r268_lan_busy;
extern volatile r268_lan_phase_t r268_current_phase;
extern volatile uint32_t h12_req_seq;
extern volatile uint32_t h12_done_seq;
void r36_brightness_changed(lv_event_t *event);
void r36_volume_changed(lv_event_t *event);
void r51_stop_audio(lv_event_t *event);
