/* R226 real SD-origin wake reply loaded before animation owner starts.
 * 76 KiB PSRAM cache bypasses FatFs+animation lock during actual wake.
 * Read-only to existing exFAT; never overwrite user media.
 */
#include "r226_sd_wake_cache.h"
#include "h13_sd_usb.h"
#include "r224_offline_voice.h"
#include "ff.h"
#include "esp_heap_caps.h"
#include "mbedtls/sha256.h"
#include "esp_log.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define R226_WAV_BYTES 76844u
static uint8_t *wake_wav=NULL;
static const uint8_t trusted_sha[32]={
0xa4, 0x0b, 0x8e, 0x72, 0xf2, 0x1f, 0x9a, 0xa5, 0xab, 0x89, 0x1f, 0xef, 0xc1, 0x43, 0xce, 0xe8,
0xed, 0x93, 0x20, 0xbb, 0x6c, 0xf0, 0xe4, 0xfa, 0x25, 0xa7, 0x9c, 0x37, 0x21, 0x58, 0x1e, 0x9a};
bool r226_sd_wake_cached(void){return wake_wav!=NULL;}
int r226_preload_sd_wake(void){
 if(wake_wav)return 0;
 const char *root=h13_sd_user_root();
 if(!root)return -1;
 char path[100];
 int n=snprintf(path,sizeof(path),"%s/DAFEIYU/VOICE/wake_ack.wav",root);
 if(n<=0||n>=(int)sizeof(path))return -2;
 FILINFO st={0};
 if(f_stat(path,&st)!=FR_OK||st.fsize!=R226_WAV_BYTES)return -3;
 // PSRAM headroom remains for LCD, WakeNet and PCM2.
 if(heap_caps_get_free_size(MALLOC_CAP_SPIRAM)<R226_WAV_BYTES+650000u)return -4;
 uint8_t *buf=heap_caps_malloc(R226_WAV_BYTES,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 if(!buf)return -5;
 // FatFs FIL is >4KiB with the current exFAT configuration. Never put
 // it on the 3584-byte app_main or 8192-byte greeting task stack.
 FIL *file=calloc(1,sizeof(*file));
 if(!file){heap_caps_free(buf);return -8;}
 if(f_open(file,path,FA_READ)!=FR_OK){free(file);heap_caps_free(buf);return -6;}
 UINT got=0;size_t count=0;bool ok=true;
 while(count<R226_WAV_BYTES){
  UINT take=(R226_WAV_BYTES-count>2048?2048:(UINT)(R226_WAV_BYTES-count));
  if(f_read(file,buf+count,take,&got)!=FR_OK||got!=take){ok=false;break;}
  count+=got;
 }
 if(f_close(file)!=FR_OK)ok=false;
 free(file);
 uint8_t sum[32]={0};
 if(!ok || count!=R226_WAV_BYTES ||
    !r224_wav_header_valid(buf,44,R226_WAV_BYTES) ||
    mbedtls_sha256(buf,R226_WAV_BYTES,sum,0)!=0 ||
    memcmp(sum,trusted_sha,32)!=0){
  heap_caps_free(buf);return -7;
 }
 wake_wav=buf;
 ESP_LOGI("R226_VOICE","SD_WAKE_CACHE_READY bytes=%u sha_verified=1",
   (unsigned)R226_WAV_BYTES);
 return 0;
}
int r226_play_cached_wake(esp_codec_dev_handle_t speaker,
                         bool(*exclusive)(void),int volume){
 if(!wake_wav||!speaker||!exclusive||!exclusive())return -1;
 // Keep the 20ms frame out of the greeting-worker stack as well.
 uint8_t *frame=calloc(1,960);
 if(!frame)return -6;
 esp_codec_dev_sample_info_t fmt={
     .sample_rate=24000,.channel=1,.bits_per_sample=16};
 if(esp_codec_dev_open(speaker,&fmt)!=ESP_CODEC_DEV_OK){free(frame);return -2;}
 int rc=0;
 if(esp_codec_dev_set_out_vol(speaker,volume)!=ESP_CODEC_DEV_OK)rc=-3;
 for(size_t offset=44;rc==0 && offset<R226_WAV_BYTES;offset+=960){
  if(!exclusive()){rc=-4;break;}
  size_t take=R226_WAV_BYTES-offset;
  if(take>960)take=960;
  memset(frame,0,960);
  memcpy(frame,wake_wav+offset,take);
  if(esp_codec_dev_write(speaker,frame,960)!=ESP_CODEC_DEV_OK)rc=-5;
 }
 if(esp_codec_dev_close(speaker)!=ESP_CODEC_DEV_OK && rc==0)rc=-9;
 free(frame);
 return rc;
}
