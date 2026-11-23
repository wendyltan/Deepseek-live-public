/* R186 non-DMA LVGL allocator pool: external BSS, freeing 64KiB
 * internal DRAM for LCD SPI DMA, audio codec and WakeNet internals.
 * Only LV_ATTRIBUTE_LARGE_RAM_ARRAY changes. Do not move DMA buffers. */
#pragma once
#include "esp_attr.h"
#define LV_ATTRIBUTE_LARGE_RAM_ARRAY EXT_RAM_BSS_ATTR
