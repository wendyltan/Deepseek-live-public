/* Project-owned RGB565 + A8 overlay compositor, not an LCD driver. */
#ifndef DAFEIYU_DFSP_BLIT_H
#define DAFEIYU_DFSP_BLIT_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* All RGB565 buffers are little-endian. Alpha is 0..255.
 * Clip is centered in supplied destination rectangle x/y; circle mask optional.
 * Preserve background pixels outside artwork and circular visible display. */
int dfsp_blit_rgb565a8(const uint8_t *src, uint16_t width, uint16_t height,
    uint8_t *dst, uint16_t dst_width, uint16_t dst_height,
    int x, int y, int circle_clip);
/* Optional 2x nearest-neighbor source enlargement for 160px sprites on a
 * square 480px screen. No circular masking; preserves alpha composition.
 * Caller places the resulting (2*width)x(2*height) rectangle at x/y.
 */
int dfsp_blit_rgb565a8_square_2x(const uint8_t *src, uint16_t width, uint16_t height,
    uint8_t *dst, uint16_t dst_width, uint16_t dst_height, int x, int y);
#endif
