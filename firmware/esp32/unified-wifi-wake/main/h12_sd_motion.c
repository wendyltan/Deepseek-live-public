// SPDX-License-Identifier: MIT
// Optional H12 SDMMC/exFAT read-only reader for user-selected DFSP sprites.
// No sdmmc_write_sectors, format or FATFS/VFS mounts in this translation unit.
#include "h12_sd_motion.h"
#include "exfat_ro_animation.h"
#include <string.h>
#include "driver/sdmmc_host.h"
#include "sdmmc_cmd.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "bsp/esp-bsp.h"
#include "freertos/semphr.h"
#ifdef DF_H13_SD_UPLOAD
#include "h13_sd_usb.h"
#endif
#ifdef DF_H12_HASH_VERIFY
#include "mbedtls/sha256.h"
#include "h12_motion_hashes.h" // generated only in ignored private Tools build
#endif
static const char *TAG="H12_EXFAT_RO";
/* R82_SD_STAGE_DIAGNOSTICS: no changes to SD card content. */
static volatile unsigned r82_sd_stage=0,r82_sd_failed_at=0;
static volatile unsigned r82_sd_error=0;
unsigned r82_sd_stage_value(void){return r82_sd_stage;}
unsigned r82_sd_failed_at_value(void){return r82_sd_failed_at;}
unsigned r82_sd_error_value(void){return r82_sd_error;}
static void r82_mark(unsigned stage,int error){
    r82_sd_stage=stage;
    if(error){r82_sd_failed_at=stage;r82_sd_error=(unsigned)error;}
    ESP_LOGI(TAG,"R82_SD_STAGE stage=%u err=%d internal=%lu largest=%lu psram=%lu",
       stage,error,
       (unsigned long)heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
       (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
       (unsigned long)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
}

static const unsigned chosen[]={0,1,2,3,8,10,11,13,14,15,16,18,19,20,23,24,25,
  26,27,28,30,61,62,67,70,71,72,73,75,80,81,83,97,99,105};
int h12_selected_id(unsigned id){
#ifdef DF_R150_ALL106
    if(id<106u)return 1; // Offline SHA-approved original 106 assets; file may be absent.
#endif
#ifdef DF_R103_USER_SD
  if(id>=200u && id<=207u)return 1; // Still SHA-verified by h13 playback.
#endif
  for(unsigned i=0;i<sizeof(chosen)/sizeof(chosen[0]);i++)if(chosen[i]==id)return 1;
  return 0;
}
static sdmmc_card_t *card;
static uint8_t *dma_sector;
static SemaphoreHandle_t card_lock;
static df_ro_exfat volume;
static df_ro_file current;
static bool ready=false,has_motion=false,host_initialized=false;
static int get_sector(void *context,uint32_t lba,uint8_t buffer[512]){
  (void)context;
  if(!ready||!card||!dma_sector||!card_lock)return -1;
  if(xSemaphoreTake(card_lock,pdMS_TO_TICKS(3000))!=pdTRUE)return -1;
  esp_err_t err=sdmmc_read_sectors(card,dma_sector,lba,1);
  if(err==ESP_OK)memcpy(buffer,dma_sector,512);
  xSemaphoreGive(card_lock);
  return err==ESP_OK?0:-1;
}
static int initial_sector(void *context,uint32_t lba,uint8_t buffer[512]){
  (void)context;
  if(!card||!dma_sector)return -1;
  if(sdmmc_read_sectors(card,dma_sector,lba,1)!=ESP_OK)return -1;
  memcpy(buffer,dma_sector,512);
  return 0;
}
static uint32_t rd32(const uint8_t*p){return (uint32_t)p[0] |((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);}
int h12_sd_initialize_read_only(void){
  if(ready)return 0;
  r82_mark(1,0);
  sdmmc_host_t host=SDMMC_HOST_DEFAULT();
  sdmmc_slot_config_t slot=SDMMC_SLOT_CONFIG_DEFAULT();
  slot.clk=BSP_SD_CLK;slot.cmd=BSP_SD_CMD;slot.d0=BSP_SD_D0;
  slot.d1=GPIO_NUM_NC;slot.d2=GPIO_NUM_NC;slot.d3=GPIO_NUM_NC;
  slot.width=1;slot.cd=SDMMC_SLOT_NO_CD;slot.wp=SDMMC_SLOT_NO_WP;
  esp_err_t err=sdmmc_host_init();
  if(err!=ESP_OK){r82_mark(91,(int)err);return -1;}
  r82_mark(2,0);
  host_initialized=true;
  err=sdmmc_host_init_slot(host.slot,&slot);
  if(err!=ESP_OK){r82_mark(92,(int)err);goto fail;}
  r82_mark(3,0);
  card=heap_caps_calloc(1,sizeof(*card),MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT);
  dma_sector=heap_caps_calloc(1,512,MALLOC_CAP_INTERNAL|MALLOC_CAP_DMA);
  card_lock=xSemaphoreCreateMutex();
  if(!card||!dma_sector||!card_lock){r82_mark(93,1);goto fail;}
  r82_mark(4,0);
  esp_err_t card_result=sdmmc_card_init(&host,card);
  if(card_result!=ESP_OK){r82_mark(94,(int)card_result);goto fail;}
  r82_mark(5,0);
  if(card->csd.sector_size!=512||
     card->csd.capacity<32||card->csd.capacity>UINT32_MAX)goto fail;
  uint8_t first[512];
  r82_mark(6,0);
  if(initial_sector(NULL,0,first)){r82_mark(96,1);goto fail;}
  uint32_t begin=0;
  if(first[510]==0x55&&first[511]==0xAA&&memcmp(first+3,"EXFAT   ",8)!=0){
    const uint8_t*partition=first+446;
    if(partition[4]==0xEE||partition[4]==0)goto fail; // GPT not yet supported
    begin=rd32(partition+8);
    if(begin<1||begin>=card->csd.capacity)goto fail;
  }
  r82_mark(7,0);
  if(df_ro_exfat_mount(&volume,initial_sector,NULL,begin,(uint32_t)card->csd.capacity)){r82_mark(97,1);goto fail;}
  // After mount, normal reads are guarded by verified volume geometry.
  volume.read=get_sector;ready=true;
  r82_mark(8,0);
  ESP_LOGI(TAG,"H12_EXFAT_RO_READY card_sectors=%lu sector=512 no_writes",
           (unsigned long)card->csd.capacity);
  return 0;
fail:
  ready=false;has_motion=false;
  if(card){heap_caps_free(card);card=NULL;}
  if(dma_sector){heap_caps_free(dma_sector);dma_sector=NULL;}
  if(card_lock){vSemaphoreDelete(card_lock);card_lock=NULL;}
  if(host_initialized){sdmmc_host_deinit();host_initialized=false;}
  ESP_LOGW(TAG,"H12_EXFAT_RO_UNAVAILABLE preserve_card_data");
  return -1;
}
int h12_sd_available(void){return ready;}
#ifdef DF_H13_SD_UPLOAD
sdmmc_card_t *h12_sd_card_for_usb_upload(void){return ready?card:NULL;}
#endif
int h12_sd_choose_motion(unsigned id){
#ifdef DF_H13_SD_UPLOAD
  return h13_sd_select_verified(id);
#else
  if(!ready||!h12_selected_id(id))return -1;
  df_ro_file item;
  if(df_ro_exfat_locate_motion(&volume,id,&item)!=0)return -1;
#ifdef DF_H12_HASH_VERIFY
  const h12_trusted_hash *expected=h12_lookup_hash(id);
  if(!expected||item.length!=expected->size)return -1;
  // Hash the ORIGINAL SD bytes, not just a plausible DFSP header. This
  // prevents another file with a user-selected name becoming trusted art.
  mbedtls_sha256_context sha;
  mbedtls_sha256_init(&sha);
  if(mbedtls_sha256_starts(&sha,0)!=0){mbedtls_sha256_free(&sha);return -1;}
  uint8_t block[512];uint64_t pos=0;int ok=1;
  while(pos<item.length){
    size_t n=(size_t)(item.length-pos);if(n>sizeof(block))n=sizeof(block);
    if(df_ro_exfat_read(&volume,&item,pos,block,n)!=n||
       mbedtls_sha256_update(&sha,block,n)!=0){ok=0;break;}
    pos+=n;
  }
  uint8_t digest[32];
  if(!ok||mbedtls_sha256_finish(&sha,digest)!=0)ok=0;
  mbedtls_sha256_free(&sha);
  if(!ok||memcmp(digest,expected->digest,32)!=0){
    ESP_LOGW(TAG,"H12_SD_HASH_MISMATCH id=%u no_display",id);
    return -1;
  }
#endif
  // Confirm format header through the existing DFSP decoder before display;
  // do not trust file name or length as proof of a valid user-selected image.
  current=item;has_motion=true;return 0;
#endif
}
void h12_sd_clear_motion(void){
#ifdef DF_H13_SD_UPLOAD
  h13_sd_release_selected();
#endif
  has_motion=false;memset(&current,0,sizeof(current));
}
size_t h12_sd_motion_size(void){
#ifdef DF_H13_SD_UPLOAD
  return h13_sd_selected_length();
#else
  return has_motion?(size_t)current.length:0;
#endif
}
size_t h12_sd_read_motion(size_t offset,uint8_t *dst,size_t n){
#ifdef DF_H13_SD_UPLOAD
  return h13_sd_selected_read(offset,dst,n);
#else
  return has_motion?df_ro_exfat_read(&volume,&current,offset,dst,n):0;
#endif
}
int h12_sd_verify_selected35(void){
#ifdef DF_H13_SD_UPLOAD
  r82_mark(9,0);
  int result=h13_sd_verify_all35();
  r82_mark(result==0?10:98,result==0?0:result);
  return result;
#else
  if(!ready)return -1;
  unsigned good=0;
  for(unsigned i=0;i<sizeof(chosen)/sizeof(chosen[0]);i++){
    df_ro_file item;
    if(df_ro_exfat_locate_motion(&volume,chosen[i],&item)==0)good++;
  }
  const unsigned expected=(unsigned)(sizeof(chosen)/sizeof(chosen[0]));
  return good==expected?0:(int)good-(int)expected;
#endif
}
