#pragma once
#include <stdbool.h>
#include "esp_codec_dev.h"
int r226_preload_sd_wake(void);
bool r226_sd_wake_cached(void);
int r226_play_cached_wake(esp_codec_dev_handle_t speaker,
                          bool(*still_exclusive)(void),int volume);
