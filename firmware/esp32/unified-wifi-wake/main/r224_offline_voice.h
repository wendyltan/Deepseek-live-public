/* R224 offline command and WAV gate; no Mac, paid API, or SD writes. */
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
typedef enum {
 R224_NO_CLIP=-1,R224_WAKE_ACK=0,R224_HELLO=1,R224_OFFLINE=2,
 R224_RICE=3,R224_STATUS=4,R224_SLEEP=5,R224_TOUCH=6,
 R224_UNKNOWN=7,R224_GOODBYE=8,R224_HAPPY=9
} r224_clip_t;
typedef struct {bool listening;uint32_t boot_epoch,wake_at_ms,last_sequence;} r224_offline_gate_t;
const char *r224_clip_filename(r224_clip_t id);
bool r224_wav_header_valid(const uint8_t *h,size_t n,uint32_t total_file_bytes);
r224_clip_t r224_verified_wake(r224_offline_gate_t *g,uint32_t epoch,uint32_t now_ms,
 bool model_verified,bool microphone_exclusive,bool playback_idle);
r224_clip_t r224_verified_command(r224_offline_gate_t *g,uint32_t epoch,
 uint32_t seq,uint32_t now_ms,uint16_t multinet_command_id,bool recognition_verified);
