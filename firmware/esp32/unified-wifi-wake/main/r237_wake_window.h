#ifndef R237_WAKE_WINDOW_H
#define R237_WAKE_WINDOW_H
#include <stdbool.h>
/* 20ms real onboard MIC frames. No 1s false-silence termination.
 * Leave enough time for the user to start speaking after the greeting.
 * Only local board frames, no Mac mic or external voice engine. */
static inline bool r237_should_close_wake(bool heard, unsigned frames,
                                           unsigned silent) {
    return frames >= 500u || (heard && frames >= 150u && silent >= 65u);
}
#endif
