/* R268 ESP32-S3 native TLS WebSocket voice transport.
 * Works only after local USB pairing (certificate+token) and DHCP GOT_IP.
 * Reuses original 16k/24k board codec through callbacks. No LLM/TTS on chip.
 * No automatic retry of a partially submitted DSH turn.
 */
#include "r268_lan_transport.h"
#include "r268_lan_pcm_wire.h"
#include "r550_wss_pcm_drain_policy.h"
#include "r614_pcm_work_phase.h"
#include "r556_wake_empty_capture_policy.h"
#include "esp_transport.h"
#include "esp_transport_ws.h"
#include "esp_transport_ssl.h"
#include "esp_log.h"
#include "esp_attr.h"
#include <errno.h>
#include "esp_heap_caps.h"
#include "esp_random.h"
#include "nvs.h"
#include "mbedtls/base64.h"
#include "lwip/sockets.h"
#include "lwip/inet.h"
#include "cJSON.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define UP_BYTES 1920u
#define DOWN_BYTES 2880u
#define SLOT_COUNT 12u // R441: 720 ms PSRAM ring for short WSS jitter; still bounded
#define PROTO_BUFFER 4096u
#define R268_MAX_INPUT_FRAMES 333u
#define R268_MAX_OUTPUT_FRAMES 3000u
#define MAX_PEER_CERT 1536u
#define DSH_TIMEOUT_MS 210000u
static const char *TAG="R268_LAN";
#ifdef DF_R434_MAC_PREWAKE_ONLY
static char r434_wake_ticket[72]={0};
// R486 truth signal: set ONLY after authenticated Mac prewake ACK and
// microphone open, clear on every disconnect/error/exit. No credentials.
static volatile bool r486_prewake_authenticated=false;
bool r486_lan_prewake_authenticated(void){
 return r486_prewake_authenticated;
}
#endif
#define R277_DIAG_MAGIC 0x5277380Cu // R441 telemetry schema, ignore old RTC snapshot
// RTC NOINIT survives USB-serial soft reboots, enabling post-battery
// diagnosis. Numeric-only; no Wi-Fi password, LAN token, PCM, or transcript.
typedef struct { uint32_t magic; r277_lan_diag_t receipt; } r277_rtc_receipt_t;
static RTC_NOINIT_ATTR r277_rtc_receipt_t r277_rtc;
bool r277_lan_diag_snapshot(r277_lan_diag_t *out){
 if(!out || r277_rtc.magic!=R277_DIAG_MAGIC)return false;
 *out=r277_rtc.receipt;return true;
}
static void r277_checkpoint(uint32_t stage){
 r277_rtc.magic=R277_DIAG_MAGIC;
 r277_rtc.receipt.stage=stage;
 r277_rtc.receipt.internal_free=(uint32_t)
     heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT);
 r277_rtc.receipt.internal_largest=(uint32_t)
     heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT);
}
typedef struct {
 char host[16],device[40],token[70];
 uint16_t port;
 uint16_t cert_len;
 uint8_t cert[MAX_PEER_CERT];
} r268_peer_t;
static bool allowed_id(const char *p,size_t min,size_t max){
 size_t n=p?strnlen(p,max+1):0;
 if(n<min||n>max)return false;
 for(size_t i=0;i<n;i++)if(!isalnum((unsigned char)p[i])&&
   p[i]!='_'&&p[i]!='-')return false;
 return true;
}
static bool allowed_token(const char *p){
 if(!p||strlen(p)!=64)return false;
 for(size_t i=0;i<64;i++)if(!isxdigit((unsigned char)p[i]))return false;
 return true;
}
static bool allowed_host(const char *host){
 struct in_addr ip;
 return host&&strlen(host)<=15&&inet_pton(AF_INET,host,&ip)==1;
}
static bool load_peer(r268_peer_t *peer){
 if(!peer)return false;
 memset(peer,0,sizeof(*peer));
 nvs_handle_t n;
 if(nvs_open("dflan",NVS_READONLY,&n)!=ESP_OK)return false;
 size_t h=sizeof(peer->host),d=sizeof(peer->device),t=sizeof(peer->token),c=sizeof(peer->cert);
 bool ok=nvs_get_str(n,"host",peer->host,&h)==ESP_OK &&
   nvs_get_u16(n,"port",&peer->port)==ESP_OK &&
   nvs_get_str(n,"device",peer->device,&d)==ESP_OK &&
   nvs_get_str(n,"token",peer->token,&t)==ESP_OK &&
   nvs_get_blob(n,"cert",peer->cert,&c)==ESP_OK;
 nvs_close(n);
 peer->cert_len=ok?(uint16_t)c:0;
 return ok&&allowed_host(peer->host)&&peer->port>=1024&&
     allowed_id(peer->device,8,39)&&allowed_token(peer->token)&&
     c>=150&&c<=MAX_PEER_CERT;
}
bool r268_lan_paired(void){
 r268_peer_t *peer=heap_caps_calloc(1,sizeof(r268_peer_t),
                                     MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 if(!peer)return false;
 bool ok=load_peer(peer);
 memset(peer,0,sizeof(*peer));heap_caps_free(peer);
 return ok;
}
/* No credentials are printed. Pairing is only accepted by the existing,
 * physically attached and sole authorized USB serial owner at IDLE.
 * Wire: @@DFLAN2 PAIR host=<ipv4> port=<port> device=<id>
 *       token=<64hex> cert=<base64DER> (one line).
 */
bool r268_lan_usb_pair(const char *command){
 if(!command)return false;
 char host[16]={0},device[40]={0},token[70]={0};
 char cert_b64[2052]={0};
 unsigned port=0;
 int n=sscanf(command,
  "@@DFLAN2 PAIR host=%15s port=%u device=%39s token=%69s cert=%2051s",
  host,&port,device,token,cert_b64);
 if(n!=5||!allowed_host(host)||port<1024||port>65535||
   !allowed_id(device,8,39)||!allowed_token(token))return false;
 uint8_t *cert=heap_caps_malloc(MAX_PEER_CERT,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 if(!cert)return false;
 size_t used=0;
 bool ok=mbedtls_base64_decode(cert,MAX_PEER_CERT,&used,
                  (const uint8_t*)cert_b64,strlen(cert_b64))==0 &&
                  used>=150&&used<=MAX_PEER_CERT&&cert[0]==0x30;
 if(ok){
   nvs_handle_t handle;
   ok=nvs_open("dflan",NVS_READWRITE,&handle)==ESP_OK;
   if(ok){
     esp_err_t rc=nvs_set_str(handle,"host",host);
     if(rc==ESP_OK)rc=nvs_set_u16(handle,"port",(uint16_t)port);
     if(rc==ESP_OK)rc=nvs_set_str(handle,"device",device);
     if(rc==ESP_OK)rc=nvs_set_str(handle,"token",token);
     if(rc==ESP_OK)rc=nvs_set_blob(handle,"cert",cert,used);
     if(rc==ESP_OK)rc=nvs_commit(handle);
     nvs_close(handle);
     ok=rc==ESP_OK;
   }
 }
 memset(token,0,sizeof(token));
 memset(cert_b64,0,sizeof(cert_b64));
 memset(cert,0,MAX_PEER_CERT);heap_caps_free(cert);
 return ok;
}
void r268_lan_usb_forget(void){
 nvs_handle_t n;
 if(nvs_open("dflan",NVS_READWRITE,&n)!=ESP_OK)return;
 if(nvs_erase_all(n)==ESP_OK)(void)nvs_commit(n);
 nvs_close(n);
}
/* R322: Reassemble one bounded RFC6455 data message. The initial
 * TEXT/BINARY opcode determines the type of every continuation (opcode 0).
 * Reject orphan continuations, interleaved data messages, overlarge frames,
 * and incomplete messages. ESP transport handles PING/PONG internally. */
static int read_frame(esp_transport_handle_t ws,uint8_t *buf,size_t cap,
                      uint32_t timeout_ms,int *opcode){
 size_t used=0;
 int message_opcode=-1;
 for(unsigned fragments=0;fragments<64;fragments++){
   if(used>=cap)return -1;
   int received=esp_transport_read(ws,(char*)buf+used,
                                   (int)(cap-used),(int)timeout_ms);
   if(received<=0)return received==0 && message_opcode<0?0:-1;
   int total=esp_transport_ws_get_read_payload_len(ws);
   int op=esp_transport_ws_get_read_opcode(ws)&0x0F;
   bool fin=esp_transport_ws_get_fin_flag(ws);
   if(total<=0 || (size_t)total>cap-used)return -1;
   if(message_opcode<0){
     if(op!=WS_TRANSPORT_OPCODES_TEXT &&
        op!=WS_TRANSPORT_OPCODES_BINARY)return -1;
     message_opcode=op;
   }else if(op!=0){
     return -1; /* only continuation is valid until FIN */
   }
   while(received<total){
     int n=esp_transport_read(ws,(char*)buf+used+received,
                              total-received,(int)timeout_ms);
     if(n<=0)return -1;
     received+=n;
   }
   used+=(size_t)received;
   if(fin){
     if(opcode)*opcode=message_opcode;
     return (int)used;
   }
 }
 return -1;
}
static bool text_send(esp_transport_handle_t ws,char *txt){
 size_t n=strlen(txt);
 return n>0&&n<2048&&
    // esp_transport_ws_send_raw() transmits the opcode bits literally.
    // ESP-IDF 5.5.5 requires the FIN bit explicitly: bare TEXT=0x01
    // advertises a fragmented message with no final continuation,
    // causing Mac websockets to wait forever for HELLO completion.
    esp_transport_ws_send_raw(ws,(ws_transport_opcodes_t)(
        WS_TRANSPORT_OPCODES_TEXT|WS_TRANSPORT_OPCODES_FIN),
                             txt,(int)n,4000)==(int)n;
}
static bool json_string(cJSON *obj,const char *key,char *to,size_t cap){
 cJSON *v=cJSON_GetObjectItemCaseSensitive(obj,key);
 if(!cJSON_IsString(v)||!v->valuestring)return false;
 size_t n=strnlen(v->valuestring,cap);
 if(n==0||n>=cap)return false;
 memcpy(to,v->valuestring,n+1);return true;
}
static bool json_type(cJSON *obj,const char *type){
 const cJSON *v=cJSON_GetObjectItemCaseSensitive(obj,"type");
 return cJSON_IsString(v)&&v->valuestring&&strcmp(v->valuestring,type)==0;
}
static bool json_session(cJSON *obj,const char *sid){
 const cJSON *v=cJSON_GetObjectItemCaseSensitive(obj,"session_id");
 return cJSON_IsString(v)&&v->valuestring&&strcmp(v->valuestring,sid)==0;
}
static bool send_session(esp_transport_handle_t ws,const char *type,
                         const char *session,const char *turn,
                         const char *playback,unsigned frame_count){
 char out[300];
 int n=snprintf(out,sizeof(out),
   "{\"type\":\"%s\",\"session_id\":\"%s\","
   "\"turn_id\":\"%s\",\"playback_id\":\"%s\",\"played_frames\":%u}",
   type,session,turn,playback,frame_count);
 return n>0&&n<(int)sizeof(out)&&text_send(ws,out);
}
static void phase(const r268_lan_codec_t *c,r268_lan_phase_t p){
 if(c->phase)c->phase(c->ctx,p);
}

bool r268_lan_run(const r268_lan_codec_t *codec,bool wake){
 if(!codec||!codec->mic_open||!codec->mic_read||!codec->mic_close||
    !codec->speaker_open||!codec->speaker_write||!codec->speaker_close||
    !codec->stop_requested)return false;
 r277_rtc.magic=R277_DIAG_MAGIC;
 memset(&r277_rtc.receipt,0,sizeof(r277_rtc.receipt));
 r277_checkpoint(1); // peer + PSRAM slots
 bool result=false,got_mic=false,got_speaker=false,offered=false;
 bool started=false,got_eos=false,submitted=false,wake_no_speech=false;
 bool incremental=false; // R508: legacy replies continue unchanged
 r268_peer_t *peer=heap_caps_calloc(1,sizeof(r268_peer_t),
                                     MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 uint8_t *incoming=heap_caps_malloc(PROTO_BUFFER,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 uint8_t *ring=heap_caps_malloc(SLOT_COUNT*DOWN_BYTES,
                                MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 esp_transport_handle_t tls=NULL,ws=NULL;
 char session[66]={0},turn[40]={0},playback[45]={0};
 uint64_t stream_up=0,stream_down=0;
 uint32_t received=0,played=0;
 uint32_t out_frames=0;
 uint32_t begin_ms=(uint32_t)pdTICKS_TO_MS(xTaskGetTickCount());
 if(!peer||!incoming||!ring||!load_peer(peer))goto end;
 r277_checkpoint(2); // TLS creation
 phase(codec,R268_LAN_CONNECTING);
 // The SDK's websocket error logs may include full Authorization headers;
 // disable this tag BEFORE setting credentials or attempting connection.
 esp_log_level_set("transport_ws",ESP_LOG_NONE);
 tls=esp_transport_ssl_init();
 if(!tls)goto end;
 esp_transport_ssl_set_cert_data_der(tls,(const char*)peer->cert,peer->cert_len);
 r277_checkpoint(3); // WSS allocation
 ws=esp_transport_ws_init(tls);
 if(!ws)goto end;
 esp_transport_ws_set_path(ws,"/device");
 r277_checkpoint(4); // headers, no secret logged
 char headers[210]={0};
 int n=snprintf(headers,sizeof(headers),
  "Authorization: Bearer %s\r\nDevice-Id: %s\r\nClient-Id: %s\r\n",
  peer->token,peer->device,peer->device);
 if(n<=0||n>=(int)sizeof(headers)||
    esp_transport_ws_set_headers(ws,headers)!=ESP_OK)goto end;
 memset(headers,0,sizeof(headers));
 r277_checkpoint(5); // SSL/TCP connect (last failed stage)
 if(esp_transport_connect(ws,peer->host,peer->port,12000)<0){
    r277_rtc.receipt.socket_errno=errno;
    goto end;
 }
 r277_checkpoint(6); // HELLO negotiation
 char msg[360];
 n=snprintf(msg,sizeof(msg),
  "{\"type\":\"hello\",\"v\":2,\"device_id\":\"%s\","
  "\"client_id\":\"%s\",\"source\":\"onboard_mic\","
  "\"audio_params\":{\"format\":\"pcm16le\",\"uplink_hz\":16000,"
  "\"downlink_hz\":24000,\"channels\":1,\"frame_ms\":60},"
  "\"playback_window_frames\":12,\"supports_incremental_audio\":true,\"supports_no_speech_terminal\":true,"
  "\"supports_verified_local_origins\":true}",
  peer->device,peer->device);
 if(n<=0||n>=(int)sizeof(msg)||!text_send(ws,msg))goto end;
 int opcode=0;
 int got=read_frame(ws,incoming,PROTO_BUFFER,6000,&opcode);
 if(got<=0||opcode!=WS_TRANSPORT_OPCODES_TEXT)goto end;
 cJSON *j=cJSON_ParseWithLength((const char*)incoming,(size_t)got);
 if(!j)goto end;
 const cJSON *verified=cJSON_GetObjectItemCaseSensitive(j,"session_verified");
 bool verified_hello=json_type(j,"hello_ack")&&cJSON_IsTrue(verified)&&
   json_string(j,"session_id",session,sizeof(session));
 cJSON_Delete(j);
 if(!verified_hello)goto end;
 r277_checkpoint(7); // HELLO verified
 uint32_t random_a=esp_random(),random_b=esp_random(),random_c=esp_random();
 snprintf(turn,sizeof(turn),"%08lx%08lx%08lx",
    (unsigned long)random_a,(unsigned long)random_b,(unsigned long)random_c);
#ifdef DF_R434_MAC_PREWAKE_ONLY
 if(wake && r434_wake_ticket[0]){
  n=snprintf(msg,sizeof(msg),
   "{\"type\":\"start\",\"session_id\":\"%s\","
   "\"turn_id\":\"%s\",\"origin\":\"wake\","
   "\"wake_ticket\":\"%s\"}",
   session,turn,r434_wake_ticket);
  memset(r434_wake_ticket,0,sizeof(r434_wake_ticket));
 }else
#endif
 n=snprintf(msg,sizeof(msg),
  "{\"type\":\"start\",\"session_id\":\"%s\","
  "\"turn_id\":\"%s\",\"origin\":\"%s\"}",
  session,turn,wake?"wake":"touch");
 if(n<=0||n>=(int)sizeof(msg)||!text_send(ws,msg))goto end;
 got=read_frame(ws,incoming,PROTO_BUFFER,6500,&opcode);
 if(got<=0||opcode!=WS_TRANSPORT_OPCODES_TEXT)goto end;
 j=cJSON_ParseWithLength((const char*)incoming,(size_t)got);
 if(!j)goto end;
 bool accepted=json_type(j,"state")&&json_session(j,session)&&
   json_string(j,"capture_stream_id",msg,sizeof(msg));
 const cJSON *s=cJSON_GetObjectItemCaseSensitive(j,"state");
 accepted=accepted&&cJSON_IsString(s)&&strcmp(s->valuestring,"listening")==0;
 cJSON_Delete(j);
 if(!accepted||strlen(msg)!=16)goto end;
 r277_checkpoint(8); // START acknowledged
 for(size_t i=0;i<16;i++)if(!isxdigit((unsigned char)msg[i]))goto end;
 stream_up=strtoull(msg,NULL,16);
 // R441: Play the real local 1.6s greeting only AFTER authenticated Mac
 // listening ACK, then immediately claim the board microphone. The old
 // 650ms blind wait plus WSS setup AFTER the greeting lost the first words.
 // The existing single audio owner is unchanged; no extra mic reader/task.
 if(!stream_up)goto end;
 if(wake && codec->wake_ack) (void)codec->wake_ack(codec->ctx);
 r277_checkpoint(9); // microphone open
 if(!codec->mic_open(codec->ctx))goto end;
 got_mic=true;
 phase(codec,R268_LAN_LISTENING);
 unsigned quiet=0,voice_frames=0;
 bool voice_detected=false;
 r277_checkpoint(10); // real mic uplink
 for(uint32_t seq=0;seq<R268_MAX_INPUT_FRAMES;seq++){
   if(codec->stop_requested(codec->ctx)){
       if(seq<3)goto end;
       break;
   }
   int16_t pcm[960]={0};
   if(!codec->mic_read(codec->ctx,pcm,960))goto end;
   unsigned peak=0;
   for(size_t i=0;i<960;i++){
      int32_t a=pcm[i];if(a<0)a=-a;
      if((unsigned)a>peak)peak=(unsigned)a;
   }
   if(peak>1200){voice_frames++;voice_detected=true;quiet=0;}
   else if(voice_detected)quiet++;
   uint8_t frame[R268_ENVELOPE+UP_BYTES];
   if(!r268_wire_encode(frame,sizeof(frame),R268_MIC_UPLINK,
                         stream_up,seq,(const uint8_t*)pcm,UP_BYTES)||
      esp_transport_ws_send_raw(ws,(ws_transport_opcodes_t)(
          WS_TRANSPORT_OPCODES_BINARY|WS_TRANSPORT_OPCODES_FIN),
                 (char*)frame,sizeof(frame),5000)!=(int)sizeof(frame))
       goto end;
   received++;
   if(wake&&r556_wake_empty_capture(seq,voice_frames,quiet)){
     // R556: also return after only one or two spurious noise peaks.
     // The valid >=3 voiced-frame path, R441 pauses, STOP, and the
     // existing 3.5s completely silent path remain unchanged.
     // No FINISH, ASR, DSH or paid model submission.
     wake_no_speech=true;result=true;goto end;
   }
   // R287: the Mac official-DSH wake gate requires >=2.0s of microphone
   // PCM before ASR. Without a matching hardware minimum, a brief word
   // followed by 14 silent 60ms frames auto-FINISHES in ~1.0s, then the
   // backend denies the turn as wake_capture_too_short_no_submit.
   // Require >=34 full frames (2.04s); keep the 3.5s no-speech abort,
   // bounded max duration, physical WakeNet origin and silence threshold.
   // R441: 1.44s of true post-speech silence rather than 0.84s;
   // preserves ordinary sentence pauses without extending a 20s cap or
   // changing the 2.04s minimum official DSH capture gate.
   if(wake&&voice_detected&&voice_frames>=3&&quiet>=24&&seq+1>=34)break;
 }
 codec->mic_close(codec->ctx);got_mic=false;
 if(received<3)goto end;
 n=snprintf(msg,sizeof(msg),
  "{\"type\":\"finish\",\"session_id\":\"%s\",\"turn_id\":\"%s\"}",
  session,turn);
 if(n<=0||n>=(int)sizeof(msg)||!text_send(ws,msg))goto end;
 submitted=true;
 r277_checkpoint(11); // official DSH response
 phase(codec,R268_LAN_THINKING);
 uint32_t waiting_since=(uint32_t)pdTICKS_TO_MS(xTaskGetTickCount());
 uint32_t last_frame_ms=waiting_since;
 // R587: the original WSS turn has ONE playback_id but may contain a
 // spoken Pinky progress announcement, long silent tool work, then speech.
 // Mouth motion is for actual written PCM only, not the whole open stream.
 bool r587_work_intermission=false;
 uint32_t r614_last_pcm_write_ms=0;
 while(true){
   if(codec->stop_requested(codec->ctx)){
      r277_rtc.receipt.exit_reason=1;goto end;
   }
   uint32_t now=(uint32_t)pdTICKS_TO_MS(xTaskGetTickCount());
   if((uint32_t)(now-begin_ms)>DSH_TIMEOUT_MS ||
      (submitted&&!offered&&(uint32_t)(now-waiting_since)>190000u) ||
      (offered&&(uint32_t)(now-last_frame_ms)>18000u)){
      r277_rtc.receipt.exit_reason=5;goto end;
   }
   // R614: tool progress/heartbeat text does not extend audible mouth time.
   // Only the last successful physical codec write resets this 1.5s clock.
   if(r614_wss_should_show_work(now,r614_last_pcm_write_ms,
       offered,started,got_eos,incremental,
       received,played,r587_work_intermission)){
       r587_work_intermission=true;
       phase(codec,R268_LAN_THINKING);
   }
   if(offered&&got_eos&&played==out_frames){
     if(!started||!send_session(ws,"playback_finished",session,turn,playback,played))
        goto end;
     result=true;break;
   }
   unsigned target_buffer=out_frames<8?out_frames:8; // R441: 480ms first-play reserve
   // R550: startup needs the real physical 8-frame reserve. After playback
   // has started, waiting to refill to 8 before writing *each* next frame
   // creates 0.5-1s gaps despite 1-7 usable frames in the ring. Keep R508's
   // final unsealed incremental frame, but drain verified legacy PCM.
   bool need_incoming=r550_wss_pcm_needs_input(
       offered,got_eos,started,incremental,out_frames,received,played);
   if(need_incoming){
     // R441: numeric-only receive starvation telemetry, not a network
     // "missing audio" assertion. ESP Codec may still have its own gaps.
     if(offered&&started&&received==played&&!got_eos)
         r277_rtc.receipt.playback_ring_empty_events++;
     uint32_t rx_begin=(uint32_t)pdTICKS_TO_MS(xTaskGetTickCount());
     got=read_frame(ws,incoming,PROTO_BUFFER,1500,&opcode);
     uint32_t rx_wait=(uint32_t)pdTICKS_TO_MS(xTaskGetTickCount())-rx_begin;
     if(offered&&started){
         if(rx_wait>r277_rtc.receipt.playback_read_max_wait_ms)
             r277_rtc.receipt.playback_read_max_wait_ms=rx_wait;
         if(rx_wait>180u)r277_rtc.receipt.playback_read_slow_events++;
     }
     if(got<0){r277_rtc.receipt.socket_errno=errno;
               r277_rtc.receipt.exit_reason=2;goto end;}
     if(got==0){
       // Reevaluate the DAC clock even if no further network packet arrives.
       // Processing heartbeats never reset r614_last_pcm_write_ms.
       uint32_t silence_now=(uint32_t)pdTICKS_TO_MS(xTaskGetTickCount());
       if(r614_wss_should_show_work(silence_now,r614_last_pcm_write_ms,
           offered,started,got_eos,incremental,
       received,played,r587_work_intermission)){
           r587_work_intermission=true;
           phase(codec,R268_LAN_THINKING);
       }
       continue;
     }
     last_frame_ms=(uint32_t)pdTICKS_TO_MS(xTaskGetTickCount());
     r277_rtc.receipt.protocol_opcode=(uint32_t)opcode;
     r277_rtc.receipt.protocol_bytes=(uint32_t)got;
     if(opcode==WS_TRANSPORT_OPCODES_BINARY){
       r268_pcm_wire_t audio={0};
       if(!offered||!r268_wire_decode(incoming,(size_t)got,
                             R268_SPEAKER_DOWNLINK,&audio)||
          audio.stream_id!=stream_down||audio.sequence!=received||
          audio.data_len!=DOWN_BYTES||received>=out_frames||
          received-played>=SLOT_COUNT)goto end;
       memcpy(ring+(received%SLOT_COUNT)*DOWN_BYTES,audio.data,DOWN_BYTES);
       received++;
       continue;
     }
     if(opcode!=WS_TRANSPORT_OPCODES_TEXT){
       r277_rtc.receipt.protocol_detail=1;
       r277_rtc.receipt.exit_reason=4;goto end;
     }
     j=cJSON_ParseWithLength((const char*)incoming,(size_t)got);
     if(!j){
       r277_rtc.receipt.protocol_detail=2;
       r277_rtc.receipt.exit_reason=4;goto end;
     }
     bool same=json_session(j,session);
     if(!same||json_type(j,"error")){
       if(!same)r277_rtc.receipt.protocol_detail=3;
       r277_rtc.receipt.exit_reason=same?3:4;
       cJSON_Delete(j);goto end;
     }
     if(json_type(j,"no_speech")){
       // R461: verified no-speech from the authenticated, current turn.
       // No model call or fake audio receipt. Return to idle without showing
       // a WSS stage11 reason3 error. A stale/forged message stays fail closed.
       const cJSON *tid=cJSON_GetObjectItemCaseSensitive(j,"turn_id");
       const cJSON *status=cJSON_GetObjectItemCaseSensitive(j,"reason");
       bool verified_no_speech=!offered && submitted && wake &&
           cJSON_IsString(tid)&&tid->valuestring&&
           strcmp(tid->valuestring,turn)==0&&
           cJSON_IsString(status)&&status->valuestring&&
           strcmp(status->valuestring,"vad_no_speech")==0;
       cJSON_Delete(j);
       if(!verified_no_speech)goto end;
       wake_no_speech=true;result=true;break;
     }
     if(json_type(j,"audio_offer")){
       char profile[40],origin[55],streamhex[24];
       const cJSON *count=cJSON_GetObjectItemCaseSensitive(j,"frames");
       const cJSON *hz=cJSON_GetObjectItemCaseSensitive(j,"hz");
       const cJSON *frame_ms=cJSON_GetObjectItemCaseSensitive(j,"frame_ms");
       const bool requested_incremental=cJSON_IsTrue(
           cJSON_GetObjectItemCaseSensitive(j,"incremental"));
       bool trusted=!offered&&json_string(j,"playback_id",playback,sizeof(playback))&&
         json_string(j,"voice_profile_id",profile,sizeof(profile))&&
         json_string(j,"answer_origin",origin,sizeof(origin))&&
         json_string(j,"stream_id",streamhex,sizeof(streamhex))&&
         strcmp(profile,"dafeiyu-qwen3-d10")==0&&
         (strcmp(origin,"official_dsh_verified")==0||
          strcmp(origin,"verified_mac_local_datetime")==0||
          strcmp(origin,"verified_open_meteo_weather")==0||
          strcmp(origin,"local_weather_source_unavailable")==0)&&
         strlen(streamhex)==16&&
         cJSON_IsNumber(count)&&
         count->valuedouble==(double)count->valueint&&
         (requested_incremental?count->valueint==0:
            (count->valuedouble>=1 &&
             count->valuedouble<=R268_MAX_OUTPUT_FRAMES))&&
         cJSON_IsNumber(hz)&&hz->valueint==24000&&
         cJSON_IsNumber(frame_ms)&&frame_ms->valueint==60;
       if(trusted){
         for(size_t i=0;i<16;i++)if(!isxdigit((unsigned char)streamhex[i]))trusted=false;
       }
       if(!trusted){cJSON_Delete(j);goto end;}
       incremental=requested_incremental;
       out_frames=incremental?R268_MAX_OUTPUT_FRAMES:
                  (uint32_t)count->valueint;
       stream_down=strtoull(streamhex,NULL,16);
       if(!stream_down){cJSON_Delete(j);goto end;}
       received=0;played=0;offered=true;
     }else if(json_type(j,"audio_eos")){
       const cJSON *count=cJSON_GetObjectItemCaseSensitive(j,"frames");
       char id[45]={0};
       bool valid=offered&&!got_eos&&json_string(j,"playback_id",id,sizeof(id))&&
            strcmp(id,playback)==0&&cJSON_IsNumber(count)&&
            count->valuedouble==(double)count->valueint&&
            count->valueint>=1&&count->valueint<=R268_MAX_OUTPUT_FRAMES&&
            (incremental?count->valueint<=(int)out_frames:
                          count->valueint==(int)out_frames)&&
            received==(uint32_t)count->valueint;
       if(!valid){cJSON_Delete(j);goto end;}
       if(incremental)out_frames=(uint32_t)count->valueint;
       got_eos=true;
     }else if(!json_type(j,"state")&&!json_type(j,"heartbeat_ack")){
       r277_rtc.receipt.protocol_detail=4;
       r277_rtc.receipt.exit_reason=4;
       cJSON_Delete(j);goto end;
     }
     cJSON_Delete(j);
     continue;
   }
   // Keep one owner for the ES8311 DAC. ACK only after real codec write.
   if(offered && received>played){
     if(!got_speaker){
       if(received-played<target_buffer&&!got_eos)continue;
       if(!codec->speaker_open(codec->ctx))goto end;
       got_speaker=true;
       r277_checkpoint(12); // codec open; playback is attempted
       // Do not notify speaking or change the speaking avatar until the
       // FIRST physical PCM block is accepted by the codec below.
     }
     const int16_t *pcm=(const int16_t*)
                  (ring+(played%SLOT_COUNT)*DOWN_BYTES);
     uint32_t write_begin=(uint32_t)pdTICKS_TO_MS(xTaskGetTickCount());
     bool written=codec->speaker_write(codec->ctx,pcm,DOWN_BYTES/2,
                                      played+1==out_frames);
     uint32_t write_ms=(uint32_t)pdTICKS_TO_MS(xTaskGetTickCount())-write_begin;
     if(write_ms>r277_rtc.receipt.playback_codec_call_max_ms)
         r277_rtc.receipt.playback_codec_call_max_ms=write_ms;
     if(write_ms>90u)r277_rtc.receipt.playback_codec_slow_events++;
     if(!written)goto end;
     r614_last_pcm_write_ms=(uint32_t)pdTICKS_TO_MS(xTaskGetTickCount());
     played++;
     if(!started){
       if(!send_session(ws,"playback_started",session,turn,playback,0))goto end;
       started=true;
     }
     if(r587_work_intermission || played==1u){
       // No animated lips before successful actual codec write.
       r587_work_intermission=false;
       phase(codec,R268_LAN_SPEAKING);
     }
     if(!send_session(ws,"audio_progress",session,turn,playback,played))goto end;
   }else if(!got_eos){
     got=read_frame(ws,incoming,PROTO_BUFFER,1500,&opcode);
     if(got<0){r277_rtc.receipt.exit_reason=2;goto end;}
     // If a frame arrived, process it in the next loop. Normally this branch
     // cannot be reached because need_incoming was true.
     if(got>0)goto end;
   }
 }
end:
 if(got_mic)codec->mic_close(codec->ctx);
 if(got_speaker)codec->speaker_close(codec->ctx);
 if(ws){(void)esp_transport_close(ws);(void)esp_transport_destroy(ws);}
 if(tls)(void)esp_transport_destroy(tls);
 if(incoming)heap_caps_free(incoming);
 if(ring)heap_caps_free(ring);
 if(peer){
    memset(peer,0,sizeof(*peer));heap_caps_free(peer);
 }
 if(result){r277_checkpoint(13);r277_rtc.receipt.result=1;}
 else r277_rtc.receipt.failed_stage=r277_rtc.receipt.stage;
 r277_rtc.receipt.elapsed_ms=
     (uint32_t)pdTICKS_TO_MS(xTaskGetTickCount())-begin_ms;
 phase(codec,wake_no_speech?R268_LAN_IDLE:
       result?R268_LAN_FINISHED:R268_LAN_ERROR);
 if(wake_no_speech)ESP_LOGI(TAG,"R461_WAKE_NO_SPEECH_RETURN_IDLE");
 else if(!result)ESP_LOGW(TAG,"R268_WSS_TURN_FAILED stage=%u sent=%u played=%lu",
   (unsigned)(offered?3:submitted?2:1),(unsigned)submitted,(unsigned long)played);
 else ESP_LOGI(TAG,"R268_WSS_TURN_CODEC_COMPLETE frames=%lu",
              (unsigned long)played);
 return result;
}

#ifdef DF_R434_MAC_PREWAKE_ONLY
/* R434: no MN5/AFE wake task. The SAME physical paired WSS TLS credentials
 * are used before the original R268 wake-triggered voice session.
 * The only microphone owner is the original R268 codec bridge.
 * Short-lived wake ticket is not logged or persisted to flash/NVS.
 */
static bool r434_valid_ticket(const char *t){
 size_t n=t?strnlen(t,sizeof(r434_wake_ticket)):0;
 if(n<24||n>=sizeof(r434_wake_ticket))return false;
 for(size_t i=0;i<n;i++){
  unsigned char c=(unsigned char)t[i];
  if(!isalnum(c)&&c!='-'&&c!='_')return false;
 }
 return true;
}
bool r268_lan_prewake_listen(const r268_lan_codec_t *codec){
 r486_prewake_authenticated=false;
 if(!codec||!codec->mic_open||!codec->mic_read||!codec->mic_close||
    !codec->stop_requested)return false;
 memset(r434_wake_ticket,0,sizeof(r434_wake_ticket));
 bool hit=false,mic_opened=false;
 r268_peer_t *peer=heap_caps_calloc(1,sizeof(r268_peer_t),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 uint8_t *rx=heap_caps_malloc(PROTO_BUFFER,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 esp_transport_handle_t tls=NULL,ws=NULL;
 char session[66]={0},stream_text[25]={0};
 uint64_t stream_id=0;
 if(!peer||!rx||!load_peer(peer))goto finish;
 esp_log_level_set("transport_ws",ESP_LOG_NONE);
 tls=esp_transport_ssl_init();
 if(!tls)goto finish;
 esp_transport_ssl_set_cert_data_der(tls,(const char*)peer->cert,peer->cert_len);
 ws=esp_transport_ws_init(tls);
 if(!ws)goto finish;
 esp_transport_ws_set_path(ws,"/device");
 char headers[210]={0};
 int n=snprintf(headers,sizeof(headers),
  "Authorization: Bearer %s\r\nDevice-Id: %s\r\nClient-Id: %s\r\n",
  peer->token,peer->device,peer->device);
 if(n<=0||n>=(int)sizeof(headers)||
    esp_transport_ws_set_headers(ws,headers)!=ESP_OK)goto finish;
 memset(headers,0,sizeof(headers));
 if(esp_transport_connect(ws,peer->host,peer->port,12000)<0)goto finish;
 char msg[390];
 n=snprintf(msg,sizeof(msg),
  "{\"type\":\"prewake_hello\",\"v\":2,\"device_id\":\"%s\","
  "\"client_id\":\"%s\",\"source\":\"onboard_mic_prewake\","
  "\"audio_params\":{\"format\":\"pcm16le\",\"uplink_hz\":16000,"
  "\"downlink_hz\":24000,\"channels\":1,\"frame_ms\":60}}",
  peer->device,peer->device);
 if(n<=0||n>=(int)sizeof(msg)||!text_send(ws,msg))goto finish;
 int opcode=0;
 int got=read_frame(ws,rx,PROTO_BUFFER,16000,&opcode);
 if(got<=0||opcode!=WS_TRANSPORT_OPCODES_TEXT)goto finish;
 cJSON *j=cJSON_ParseWithLength((const char*)rx,(size_t)got);
 if(!j)goto finish;
 bool ok=json_type(j,"prewake_ack")&&
   json_string(j,"session_id",session,sizeof(session))&&
   json_string(j,"stream_id",stream_text,sizeof(stream_text));
 cJSON_Delete(j);
 if(!ok||strlen(stream_text)!=16)goto finish;
 for(unsigned k=0;k<16;k++)if(!isxdigit((unsigned char)stream_text[k]))goto finish;
 stream_id=strtoull(stream_text,NULL,16);
 if(!stream_id||!codec->mic_open(codec->ctx))goto finish;
 mic_opened=true;
 r486_prewake_authenticated=true;
 for(uint32_t seq=0;seq<9000;seq++){
  if(codec->stop_requested(codec->ctx))break;
  int16_t pcm[960]={0};
  if(!codec->mic_read(codec->ctx,pcm,960))break;
  uint8_t packet[R268_ENVELOPE+UP_BYTES];
  if(!r268_wire_encode(packet,sizeof(packet),R268_MIC_UPLINK,
                      stream_id,seq,(const uint8_t *)pcm,UP_BYTES))break;
  if(esp_transport_ws_send_raw(ws,(ws_transport_opcodes_t)(
       WS_TRANSPORT_OPCODES_BINARY|WS_TRANSPORT_OPCODES_FIN),
       (char*)packet,sizeof(packet),4500)!=(int)sizeof(packet))break;
  /* Receive only when a complete application packet is pending. The
   * TLS/WS transport supports poll_read; no duplicated mic task, buffers
   * or ping process is spawned. A false poll is not a wake. */
  int poll=esp_transport_poll_read(ws,0);
  if(poll<0)break;
  if(poll==0)continue;
  got=read_frame(ws,rx,PROTO_BUFFER,2000,&opcode);
  if(got<=0||opcode!=WS_TRANSPORT_OPCODES_TEXT)break;
  j=cJSON_ParseWithLength((const char*)rx,(size_t)got);
  if(!j)break;
  char ticket[72]={0};
  char received_session[66]={0};
  char keyword[35]={0};
  ok=json_type(j,"prewake_hit")&&
    json_string(j,"session_id",received_session,sizeof(received_session))&&
    json_string(j,"keyword",keyword,sizeof(keyword))&&
    json_string(j,"wake_ticket",ticket,sizeof(ticket))&&
    strcmp(session,received_session)==0 &&
    strcmp(keyword,"ni_hao_da_fei_yu")==0 &&
    r434_valid_ticket(ticket);
  cJSON_Delete(j);
  if(ok){
   memcpy(r434_wake_ticket,ticket,sizeof(r434_wake_ticket));
   memset(ticket,0,sizeof(ticket));
   hit=true;
   ESP_LOGI(TAG,"R434_REAL_AUTHENTICATED_MAC_KWS_HIT frames=%lu",(unsigned long)(seq+1));
  }
  break; /* no other prewake server message is accepted */
 }
finish:
 r486_prewake_authenticated=false;
 if(mic_opened)codec->mic_close(codec->ctx);
 if(ws)esp_transport_close(ws);
 if(ws)esp_transport_destroy(ws);
 if(tls)esp_transport_destroy(tls);
 if(rx)heap_caps_free(rx);
 if(peer){memset(peer,0,sizeof(*peer));heap_caps_free(peer);}
 if(!hit)memset(r434_wake_ticket,0,sizeof(r434_wake_ticket));
 return hit;
}
#endif
