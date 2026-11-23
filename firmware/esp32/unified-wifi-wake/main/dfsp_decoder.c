#include "dfsp_decoder.h"
#include <string.h>
#ifdef ESP_PLATFORM
#include "miniz.h" /* ESP-IDF 5.5.5 esp_rom/include/miniz.h */
#else
#include <zlib.h>
#endif

static uint16_t u16le(const uint8_t *p) {
 return (uint16_t)((unsigned)p[0] | ((unsigned)p[1] << 8));
}
static uint32_t u32le(const uint8_t *p) {
 return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
        ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
int dfsp_open(dfsp_decoder *ctx, const uint8_t *input, size_t input_size,
              uint8_t *output, size_t out_cap, uint8_t *scratch, size_t scratch_cap) {
 if (!ctx || !input || !output || !scratch || output == scratch)
  return DFSP_ERR_STATE;
 memset(ctx, 0, sizeof(*ctx));
 if (input_size < 12 || memcmp(input, "DFSP", 4) != 0 || input[4] != 1)
  return DFSP_ERR_HEADER;
 uint16_t width = u16le(input+5), height=u16le(input+7), count=u16le(input+10);
 uint8_t fps=input[9];
 if (width != height || (width != 160 && width != 240 && width != 320) ||
     fps == 0 || fps > 20 || count == 0 || count > 100)
  return DFSP_ERR_HEADER;
 size_t frame_bytes=(size_t)width * height * 3;
 if (out_cap < frame_bytes || scratch_cap < frame_bytes)
  return DFSP_ERR_SIZE;
 ctx->data=input;
 ctx->size=input_size;
 ctx->next_offset=12;
 ctx->width=width;ctx->height=height;
 ctx->frame_count=count;ctx->fps=fps;
 ctx->frame_bytes=frame_bytes;
 ctx->output=output;ctx->scratch=scratch;
 return DFSP_OK;
}
int dfsp_open_reader(dfsp_decoder *ctx, dfsp_read_at read_at, void *read_user,
    size_t total_size, uint8_t *output, size_t out_cap,
    uint8_t *scratch, size_t scratch_cap,
    uint8_t *compressed, size_t compressed_cap) {
 if (!ctx || !read_at || !output || !scratch || !compressed ||
     output == scratch || compressed == output || compressed == scratch ||
     total_size < 12 || total_size > 32000000)
  return DFSP_ERR_STATE;
 uint8_t header[12] = {0};
 if (read_at(read_user, 0, header, sizeof(header)) != sizeof(header))
  return DFSP_ERR_SIZE;
 int status=dfsp_open(ctx, header, sizeof(header), output, out_cap,
                      scratch, scratch_cap);
 if (status != DFSP_OK) return status;
 /* The header was a stack temporary. Reader owns the persistent bytes. */
 ctx->data=NULL;
 ctx->read_at=read_at;
 ctx->read_user=read_user;
 ctx->compressed=compressed;
 ctx->compressed_cap=compressed_cap;
 ctx->size=total_size;
 return DFSP_OK;
}
int dfsp_next(dfsp_decoder *ctx) {
 if (!ctx || (!ctx->data && !ctx->read_at) || !ctx->output || !ctx->scratch)
  return DFSP_ERR_STATE;
 if (ctx->frame_index >= ctx->frame_count)
  return DFSP_END;
 size_t offset=ctx->next_offset;
 if (offset > ctx->size || ctx->size-offset < 5)
  return DFSP_ERR_SIZE;
 uint8_t frame_header[5]={0};
 const uint8_t *header=ctx->data ? ctx->data+offset : frame_header;
 if (!ctx->data && ctx->read_at(ctx->read_user,offset,frame_header,5)!=5)
  return DFSP_ERR_SIZE;
 unsigned kind=header[0];
 size_t payload=(size_t)u32le(header+1);
 offset += 5;
 if ((kind!=1 && kind!=2) || (kind==2 && ctx->frame_index==0))
  return DFSP_ERR_HEADER;
 /* Reject decompression bombs or an implausibly large encoded block. */
 if (!payload || payload>ctx->frame_bytes+ctx->frame_bytes/100+64 ||
     payload>ctx->size-offset ||
     (ctx->frame_index+1 == ctx->frame_count && offset+payload != ctx->size))
  return DFSP_ERR_SIZE;
 const uint8_t *zdata=ctx->data ? ctx->data+offset : ctx->compressed;
 if (!ctx->data && (payload>ctx->compressed_cap ||
     ctx->read_at(ctx->read_user,offset,ctx->compressed,payload)!=payload))
  return DFSP_ERR_SIZE;
#ifdef ESP_PLATFORM
 /* ESP-IDF disables MINIZ_NO_ZLIB_APIS: use its ROM tinfl-compatible API.
  * Parse zlib wrapper + Adler32 and decode into supplied bounded PSRAM.
  */
 size_t unpacked=tinfl_decompress_mem_to_mem(ctx->scratch,ctx->frame_bytes,
     zdata,payload,
     TINFL_FLAG_PARSE_ZLIB_HEADER | TINFL_FLAG_USING_NON_WRAPPING_OUTPUT_BUF);
 if (unpacked != ctx->frame_bytes)
  return DFSP_ERR_COMPRESSED;
#else
 uLongf unpacked=(uLongf)ctx->frame_bytes;
 int rc=uncompress(ctx->scratch,&unpacked,zdata,(uLong)payload);
 if (rc!=Z_OK || unpacked != ctx->frame_bytes)
  return DFSP_ERR_COMPRESSED;
#endif
 /* No torn frame on errors: only output after full decompression. */
 if (kind==1) {
  memcpy(ctx->output,ctx->scratch,ctx->frame_bytes);
 } else {
  for(size_t i=0;i<ctx->frame_bytes;i++)
   ctx->output[i] ^= ctx->scratch[i];
 }
 ctx->next_offset=offset+payload;
 ctx->frame_index++;
 if (ctx->frame_index==ctx->frame_count &&
     ctx->next_offset!=ctx->size)
  return DFSP_ERR_SIZE;
 return DFSP_OK;
}
