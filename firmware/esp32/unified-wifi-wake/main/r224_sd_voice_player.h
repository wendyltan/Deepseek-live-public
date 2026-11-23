/* R224 opt-in isolated SD audio player.
 * The caller MUST exclusively own speaker/mic and pass a true current lock
 * callback. This module is NOT wired into the currently flashed R223.
 */
#pragma once
#include <stdbool.h>
#include "esp_codec_dev.h"
#include "r224_offline_voice.h"
int r224_play_onboard_sd(r224_clip_t id,esp_codec_dev_handle_t speaker,
                        bool (*still_exclusive)(void),int volume);
