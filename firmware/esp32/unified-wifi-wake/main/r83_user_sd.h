// R83 guarded user-motion SD writer, never overwrites the factory 35 files.
#ifndef R83_USER_SD_H
#define R83_USER_SD_H
#include <stdbool.h>
bool r83_arm_touch(void);
/* Verify user slot on physical SD before playback, no cached claim. */
bool r83_user_slot_verified(unsigned id,unsigned *bytes);
bool r83_transfer_active(void);
bool r83_arm_pending(void);
void r83_usb_command(const char *cmd);
void r83_usb_housekeeping(bool audio_busy);
void r83_animation_sd_quiescent_boundary(void);
#endif
