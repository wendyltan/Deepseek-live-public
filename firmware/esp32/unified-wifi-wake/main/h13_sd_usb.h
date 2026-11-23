// Only selected, SHA256 pinned .DFS can be pushed over ESP32 built-in USB-JTAG.
#ifndef H13_SD_USB_H
#define H13_SD_USB_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
void h13_sd_usb_handle(const char *line);
const char *h13_sd_user_root(void);
int h13_sd_presets_prepare(void);
int h13_sd_preset_copy(unsigned index,char *dst,size_t cap);
bool h13_sd_usb_active(void);
uint64_t h13_sd_known_motion_bytes(void);
// Read-only actual filesystem capacity and occupied clusters. 0=verified.
int h13_sd_usage_bytes(uint64_t *total,uint64_t *used);
int h13_sd_verify_all35(void);
void h13_r87_mount_trace(unsigned *step,unsigned *sector,unsigned *capacity,
                          unsigned *drive,int *esp_err,int *fresult);
/* R86 readonly first failure stage, never exposes private card contents */
void h13_r86_trace(unsigned *stage,unsigned *bad_id,int *fs_error,
                    unsigned *expected,unsigned *actual,unsigned *found);
int h13_sd_select_verified(unsigned id);
void h13_sd_release_selected(void);
size_t h13_sd_selected_length(void);
size_t h13_sd_selected_read(size_t offset,uint8_t *dst,size_t count);
#endif
