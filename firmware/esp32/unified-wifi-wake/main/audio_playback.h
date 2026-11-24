// SPDX-License-Identifier: MIT
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

bool sample_asset(const uint8_t **pcm,size_t *samples);

bool r268_audio_speaker_open(void *unused);
bool r268_audio_speaker_write(void *unused,const int16_t *data,size_t count,bool last);
void r268_audio_speaker_close(void *unused);
