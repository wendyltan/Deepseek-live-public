// SPDX-License-Identifier: MIT
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

bool h9_send_line(const char *line,size_t n);
bool h9_send_audio_frame(unsigned i,const int16_t *samples,bool diagnostic,size_t sample_count);
#ifdef DF_H28_HOLD_MIC
bool h28_send_mic_frame(unsigned i,const int16_t *samples,size_t sample_count);
#endif
