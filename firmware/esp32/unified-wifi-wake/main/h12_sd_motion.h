#ifndef H12_SD_MOTION_H
#define H12_SD_MOTION_H
/* R82_SD_STAGE_DIAGNOSTICS */
unsigned r82_sd_stage_value(void);
unsigned r82_sd_failed_at_value(void);
unsigned r82_sd_error_value(void);
#include <stdint.h>
#include <stddef.h>
// Device-side exFAT card is never formatted/mounted writable.
int h12_sd_initialize_read_only(void);
int h12_sd_available(void);
#ifdef DF_H13_SD_UPLOAD
#include "sdmmc_cmd.h"
sdmmc_card_t *h12_sd_card_for_usb_upload(void);
#endif
int h12_sd_verify_selected35(void);
int h12_sd_choose_motion(unsigned id);
void h12_sd_clear_motion(void);
size_t h12_sd_motion_size(void);
size_t h12_sd_read_motion(size_t offset,uint8_t *dst,size_t count);
int h12_selected_id(unsigned id);
#endif
