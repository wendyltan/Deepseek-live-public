/* R229: single codec and SD-pause owner; no network, filesystem or allocation.
 * Tokens are acquired/released by the real task, not copied across USB turns.
 */
#pragma once
#include <stdbool.h>
#include <stdint.h>
typedef enum {
 R224_MEDIA_NONE=0,R224_MEDIA_WAKE=1,R224_MEDIA_CAPTURE=2,
 R224_MEDIA_LOCAL_CLIP=3,R224_MEDIA_PCM1=4,R224_MEDIA_PCM2=5
} r224_media_owner_t;
typedef enum {
 R224_SD_NONE=0,R224_SD_LOCAL=1,R224_SD_USB=2
} r224_sd_owner_t;
bool r224_audio_claim(r224_media_owner_t owner,uint32_t *lease);
bool r224_audio_release(r224_media_owner_t owner,uint32_t lease);
bool r224_audio_owned(r224_media_owner_t owner,uint32_t lease);
bool r224_sd_claim(r224_sd_owner_t owner,uint32_t *lease);
bool r224_sd_release(r224_sd_owner_t owner,uint32_t lease);
bool r224_sd_owned(r224_sd_owner_t owner,uint32_t lease);
