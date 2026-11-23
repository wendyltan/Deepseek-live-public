/* Pure RGB565 backing: exactly white, matching R58 LVGL screen.
 * Draw only a small feathered ground shadow under the character's feet;
 * never rasterize a square asset background or circular mask.
 */
#ifndef DAFEIYU_DFSP_STAGE_H
#define DAFEIYU_DFSP_STAGE_H
#include <stdint.h>
#include <stddef.h>
#define DAFEIYU_STAGE_R 0xFF
#define DAFEIYU_STAGE_G 0xFF
#define DAFEIYU_STAGE_B 0xFF
#define DAFEIYU_STAGE_BG_RGB565 0xFFFF
void dfsp_stage_background(uint8_t *rgb565, uint16_t width, uint16_t height);
int dfsp_stage_soft_shadow(uint8_t *rgb565, uint16_t width, uint16_t height,
                           int center_x, int center_y, int radius_x, int radius_y);
#endif
