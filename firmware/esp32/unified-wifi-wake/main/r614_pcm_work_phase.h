/* R614: pure audible-PCM-to-work gate, host-testable without ESP-IDF.
 * Ignore network processing pings and use ONLY verified codec write time.
 * All timestamps are wrap-safe millisecond ticks from one monotonic clock.
 */
#pragma once
#include <stdbool.h>
#include <stdint.h>

static inline bool r614_wss_should_show_work(
    uint32_t now_ms, uint32_t last_dac_ms,
    bool offered, bool started, bool got_eos, bool incremental,
    uint32_t received, uint32_t played, bool already_working
) {
    // R619: R550 holds ONE unsealed incremental PCM frame until EOS.
    // That frame is *not yet writable to the codec*. Requiring zero frames
    // prevented THINKING throughout long phone operations. Only a verified
    // physical codec write extends the lip interval, not incoming pings.
    return offered && started && !got_eos && !already_working &&
           received >= played &&
           received - played <= (incremental ? 1u : 0u) &&
           (uint32_t)(now_ms-last_dac_ms) >= 1500u;
}
