/* Project-owned DFSP v1 transparent sprite decoder for ESP32-S3, no assets.
 * Layout: <4sBHHBH> header, repeated <BI> kind+zlib length + bytes.
 * Pixel output: little-endian RGB565 plus one alpha byte, 3B/pixel.
 * ESP32: link ESP-IDF esp_rom/miniz; host QA: zlib.
 * Caller owns buffers; PSRAM/Flash storage and display are separate.
 */
#ifndef DAFEIYU_DFSP_DECODER_H
#define DAFEIYU_DFSP_DECODER_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Random-access bounded read from mapped flash / partition / file. */
typedef size_t (*dfsp_read_at)(void *user, size_t offset, uint8_t *dst, size_t count);
enum {
 DFSP_OK = 0,
 DFSP_END = 1,
 DFSP_ERR_HEADER = -1,
 DFSP_ERR_SIZE = -2,
 DFSP_ERR_COMPRESSED = -3,
 DFSP_ERR_STATE = -4
};
typedef struct {
 const uint8_t *data;
 dfsp_read_at read_at;
 void *read_user;
 uint8_t *compressed;
 size_t compressed_cap;
 size_t size;
 size_t next_offset;
 uint16_t width, height, frame_count, frame_index;
 uint8_t fps;
 /* Caller supplies TWO full frames: output and scratch. */
 uint8_t *output;
 uint8_t *scratch;
 size_t frame_bytes;
} dfsp_decoder;

/* Both buffers must each hold at least 3*width*height bytes. */
int dfsp_open(dfsp_decoder *ctx, const uint8_t *input, size_t input_size,
              uint8_t *output, size_t output_capacity,
              uint8_t *scratch, size_t scratch_capacity);
/* One clip stays in flash: buffers hold only one decoded frame, one delta
 * frame, and one compressed block. Caller keeps these alive while decoding.
 * read_at returns count only on a complete successful read. */
int dfsp_open_reader(dfsp_decoder *ctx, dfsp_read_at read_at, void *read_user,
    size_t total_size, uint8_t *output, size_t output_capacity,
    uint8_t *scratch, size_t scratch_capacity,
    uint8_t *compressed, size_t compressed_capacity);
int dfsp_next(dfsp_decoder *ctx);
#ifdef __cplusplus
}
#endif
#endif
