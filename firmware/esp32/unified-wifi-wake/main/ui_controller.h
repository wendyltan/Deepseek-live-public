// SPDX-License-Identifier: MIT
#pragma once

const char *r59_local_status(const char *status);

#ifdef DF_R33_BOARD_UI
#include <stdint.h>
#include "lvgl.h"
extern lv_obj_t *r57_root;
extern volatile unsigned r57_local_motion_request;
extern char r57_recent[4][769];
extern unsigned r62_chat2_next[4];
extern volatile uint32_t r57_recent_revision;
extern unsigned r57_page;
void r57_style_home(lv_obj_t *screen,lv_obj_t *mic,lv_obj_t *mic_label);
LV_FONT_DECLARE(lv_font_r57_cn_16);
LV_FONT_DECLARE(lv_font_r57_cn_20);
#endif
