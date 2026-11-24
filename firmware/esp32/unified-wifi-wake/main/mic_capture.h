// SPDX-License-Identifier: MIT
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_codec_dev.h"

extern esp_codec_dev_handle_t microphone;
esp_codec_dev_handle_t r248_microphone_init_with_gain(void);
bool r268_audio_mic_open(void *unused);
bool r268_audio_mic_read(void *unused,int16_t *samples,size_t count);
void r268_audio_mic_close(void *unused);
