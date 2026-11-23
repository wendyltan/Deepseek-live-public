/* R556: idle wake capture must not hang after one or two noise peaks.
 * Decision only; no TLS/codec/DSH/flash writes. Host-testable C11.
 */
#ifndef R556_WAKE_EMPTY_CAPTURE_POLICY_H
#define R556_WAKE_EMPTY_CAPTURE_POLICY_H
#include <stdbool.h>
#include <stdint.h>
static inline bool r556_wake_empty_capture(uint32_t seq, unsigned voice_frames,
                                           unsigned quiet_frames) {
    /* 59 full 60ms frames == 3.54s; original zero-voice grace remains. */
    if (seq < 58u) return false;
    if (voice_frames == 0u) return true;
    /* A one/two-frame impulse is insufficient real speech. If silence
       follows for 1.44s, or the capture exceeds 6s, return to idle. */
    return (voice_frames < 3u &&
            (quiet_frames >= 24u || seq >= 99u));
}
#endif
