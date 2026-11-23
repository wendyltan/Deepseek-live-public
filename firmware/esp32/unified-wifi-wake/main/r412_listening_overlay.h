// R412: offline-only dedicated listening waveform over approved m000 pixels.
// 240x240 RGB565 little-endian, no allocation, no SD access, no LVGL objects.
// Pixel-only waveform: character, background, and geometry are unchanged.
#ifndef R412_LISTEN_OVERLAY_H
#define R412_LISTEN_OVERLAY_H
#include <stdint.h>
#include <stddef.h>
#define R412_LISTEN_W 240u
#define R412_LISTEN_H 240u
#define R412_LISTEN_FRAMES 16u
static inline void r412_listen_render(uint8_t *rgb565, unsigned step) {
    if (!rgb565) return;
    static const uint8_t heights[16][5] = {
        {5,  9, 13,  9, 5}, {6, 10, 14,  9, 5},
        {7, 11, 15, 10, 6}, {8, 12, 16, 11, 7},
        {9, 13, 16, 12, 8}, {9, 12, 15, 13, 9},
        {8, 11, 14, 14,10}, {7, 10, 13, 15,11},
        {6,  9, 13, 15,11}, {6,  8, 12, 14,10},
        {5,  8, 11, 13, 9}, {5,  8, 11, 11, 8},
        {5,  9, 12, 10, 7}, {5,  9, 13,  9, 6},
        {5,  9, 13,  9, 5}, {5,  9, 13,  9, 5}
    };
    const uint8_t *h = heights[step % R412_LISTEN_FRAMES];
    uint16_t *canvas = (uint16_t *)(void *)rgb565;
    // Small muted aqua sound bars at the top-right; no character scaling,
    // no huge UI halo, no reading of microphone samples or private audio.
    for (unsigned bar = 0; bar < 5u; ++bar) {
        const int x0 = 181 + (int)bar * 8;
        const int center = 31;
        const int low = center - (int)(h[bar] / 2u);
        const int high = low + (int)h[bar] - 1;
        for (int y = low; y <= high; ++y) {
            for (int dx = 0; dx < 3; ++dx) {
                const unsigned x = (unsigned)(x0 + dx);
                const unsigned yy = (unsigned)y;
                if (x < R412_LISTEN_W && yy < R412_LISTEN_H) {
                    const uint16_t highlight = (bar == 2u) ? 0x35F2u : 0x3DB0u;
                    canvas[yy * R412_LISTEN_W + x] = highlight;
                }
            }
        }
    }
}
#endif
