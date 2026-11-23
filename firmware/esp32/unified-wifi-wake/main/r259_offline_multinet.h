#pragma once
#include "esp_codec_dev.h"
/* Only called after an actual local WakeNet event AND real codec release.
 * Returns command ID 1..7 only from a genuine AFE->MultiNet acoustic hit.
 * 0=no command, negative=failed safe; no USB text can invoke this function.
 */
int r259_acoustic_command(esp_codec_dev_handle_t mic,unsigned window_ms);
/* Direct real 16k PCM alternative, no Mac/second mic/AFE worker. */
int r265_direct_mn5_command(esp_codec_dev_handle_t mic,unsigned window_ms,
                            void (*on_listen_ready)(void));
void r259_read_diagnostics(unsigned *attempts,unsigned *hits,int *last,
                           int *last_error,unsigned *free_internal,
                           unsigned *free_psram);
/* Only numeric real SDK model+AFE allocation; no microphone read or hit. */
int r263_mn5_afe_alloc_probe(unsigned *psram_before,unsigned *psram_after,
                             unsigned *internal_after,unsigned *psram_recovered);
