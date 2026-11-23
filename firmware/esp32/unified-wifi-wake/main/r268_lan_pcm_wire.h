/* R268: ESP32<->Mac audio envelope, identical to app/device_audio_frame.py.
 * Transport-independent and usable from host native tests; no codecs, keys,
 * allocations, flash or tasks. Network byte order, 16-byte header.
 */
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#define R268_MAGIC_0 0x44u
#define R268_MAGIC_1 0x46u
#define R268_VERSION 2u
#define R268_MIC_UPLINK 1u
#define R268_SPEAKER_DOWNLINK 2u
#define R268_ENVELOPE 16u
#define R268_UP_PCM_BYTES 1920u
#define R268_DOWN_PCM_BYTES 2880u
#define R268_MAX_PAYLOAD 4096u
typedef struct {
    uint8_t direction;
    uint64_t stream_id;
    uint32_t sequence;
    const uint8_t *data;
    size_t data_len;
} r268_pcm_wire_t;
bool r268_wire_encode(uint8_t *out,size_t out_cap,
                      uint8_t dir,uint64_t stream,uint32_t sequence,
                      const uint8_t *payload,size_t n);
bool r268_wire_decode(const uint8_t *buffer,size_t len,
                      uint8_t required_direction,r268_pcm_wire_t *out);
