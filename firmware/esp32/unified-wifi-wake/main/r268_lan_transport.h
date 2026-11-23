/* R268 Wi-Fi WSS transport adapter. Original USB/SD/DSH remains unchanged. */
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
typedef enum {
 R268_LAN_IDLE=0,R268_LAN_CONNECTING=1,R268_LAN_LISTENING=2,
 R268_LAN_THINKING=3,R268_LAN_SPEAKING=4,R268_LAN_FINISHED=5,
 R268_LAN_ERROR=6
} r268_lan_phase_t;
typedef struct {
 void *ctx;
 bool (*mic_open)(void *ctx);
 bool (*mic_read)(void *ctx,int16_t *samples,size_t count);
 void (*mic_close)(void *ctx);
 // R441: optional authentic local wake greeting after the Mac has ACKed
 // START, immediately before mic_open; only used for verified wake sessions.
 bool (*wake_ack)(void *ctx);
 bool (*speaker_open)(void *ctx);
 bool (*speaker_write)(void *ctx,const int16_t *samples,size_t count,bool last);
 void (*speaker_close)(void *ctx);
 bool (*stop_requested)(void *ctx);
 void (*phase)(void *ctx,r268_lan_phase_t phase);
} r268_lan_codec_t;
// RTC-retained numeric-only WSS failure receipt; never stores credentials.
typedef struct {
 uint32_t stage,failed_stage,elapsed_ms;
 uint32_t internal_free,internal_largest;
 int32_t socket_errno;
 uint32_t result; // 0=failed or unfinished,1=complete
 uint32_t exit_reason; // 0 unknown, 1 explicit STOP, 2 recv error,
                        // 3 server error, 4 protocol decode, 5 deadline
 uint32_t protocol_detail; // 0 none,1 opcode,2 malformed JSON,
                           // 3 session mismatch,4 unexpected control
 uint32_t protocol_opcode; // last received WS opcode, numeric only
 uint32_t protocol_bytes;  // last frame payload byte count, no contents
 // R441: aggregate numeric playback evidence, no PCM/text/credentials.
 uint32_t playback_ring_empty_events;
 uint32_t playback_read_max_wait_ms;
 uint32_t playback_read_slow_events;
 uint32_t playback_codec_call_max_ms;
 uint32_t playback_codec_slow_events;
} r277_lan_diag_t;
bool r277_lan_diag_snapshot(r277_lan_diag_t *out);
bool r268_lan_paired(void);
bool r268_lan_run(const r268_lan_codec_t *codec,bool started_by_wake);
bool r268_lan_usb_pair(const char *command);
void r268_lan_usb_forget(void);

#ifdef DF_R434_MAC_PREWAKE_ONLY
/* Paired WSS microphone streaming; returns true only with KWS ticket. */
bool r268_lan_prewake_listen(const r268_lan_codec_t *codec);
// Is the current WSS Mac prewake channel actually authenticated & streaming?
bool r486_lan_prewake_authenticated(void);
#endif
