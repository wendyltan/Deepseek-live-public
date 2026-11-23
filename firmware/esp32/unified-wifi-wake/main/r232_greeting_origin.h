#pragma once
#include <stdbool.h>
#include <stdint.h>
/* Pure, auditable authorization gate. Only the physical WakeNet detector can
 * set origin=true; a USB OFFLINE1 PLAY is not a real detected utterance.
 * ARM is necessary but not sufficient for automatic capture.
 */
static inline bool r232_should_auto_capture(bool physical_wake_origin,
                                            bool mac_armed,
                                            int32_t ticks_before_deadline) {
    return physical_wake_origin && mac_armed && ticks_before_deadline > 0;
}
