/* R550: bounded audio receive policy for the paired ESP32 WSS voice owner.
 *
 * Before first playback, prebuffer up to eight 60ms frames. Once playback
 * starts, consume already-verified complete frames instead of blocking for
 * an eight-frame refill on *every* 60ms codec write.
 *
 * Incremental R508 audio must still keep the final currently-received frame
 * until authenticated EOS supplies its true total and last-frame sample
 * count; preserve the original source/frame-count/protocol gates.
 *
 * This pure function has no ESP-IDF dependency and is host-compiler tested.
 * It changes no board until an independently approved guarded flash.
 */
#pragma once
#include <stdbool.h>
#include <stdint.h>

static inline bool r550_wss_pcm_needs_input(
    bool offered, bool got_eos, bool started, bool incremental,
    uint32_t out_frames, uint32_t received, uint32_t played
) {
    if (!offered) return true;
    if (got_eos) return false;
    /* Cannot consume an invalid negative ring occupancy. Existing
     * sequence checks should prevent it; keep reception conservative.
     */
    if (received < played) return true;
    const uint32_t buffered = received - played;
    if (!started) {
        const uint32_t startup = out_frames < 8u ? out_frames : 8u;
        return out_frames == 0u || buffered < startup;
    }
    /* Incremental: never write an unsealed last frame. After EOS it is
     * safe to drain it, including the last short-frame zero padding.
     */
    if (incremental) return buffered <= 1u;
    /* Legacy fully-buffered: a nonempty ring is playable. Stop imposing
     * network RTTs at every frame simply to keep eight frames stocked.
     */
    return buffered == 0u;
}
