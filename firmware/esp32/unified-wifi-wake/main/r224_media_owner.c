/* FreeRTOS spinlock only guards two short in-memory state changes.
 * NEVER perform I/O, codec open, waiting, task create or SD calls inside it.
 */
#include "r224_media_owner.h"
#include "freertos/FreeRTOS.h"
#include <stddef.h>
static portMUX_TYPE media_lock=portMUX_INITIALIZER_UNLOCKED;
static uint32_t serial_counter=0,audio_token=0,sd_token=0;
static r224_media_owner_t audio_owner=R224_MEDIA_NONE;
static r224_sd_owner_t sd_owner=R224_SD_NONE;
static uint32_t new_token(void) {
    ++serial_counter;
    if(serial_counter==0)++serial_counter;
    return serial_counter;
}
bool r224_audio_claim(r224_media_owner_t owner,uint32_t *lease){
 if(owner<=R224_MEDIA_NONE||owner>R224_MEDIA_PCM2||!lease)return false;
 bool ok=false;
 portENTER_CRITICAL(&media_lock);
 if(audio_owner==R224_MEDIA_NONE){
  audio_owner=owner;audio_token=new_token();*lease=audio_token;ok=true;
 }
 portEXIT_CRITICAL(&media_lock);
 return ok;
}
bool r224_audio_release(r224_media_owner_t owner,uint32_t lease){
 bool ok=false;
 portENTER_CRITICAL(&media_lock);
 if(owner!=R224_MEDIA_NONE&&lease!=0&&audio_owner==owner&&audio_token==lease){
  audio_owner=R224_MEDIA_NONE;audio_token=0;ok=true;
 }
 portEXIT_CRITICAL(&media_lock);
 return ok;
}
bool r224_audio_owned(r224_media_owner_t owner,uint32_t lease){
 bool ok=false;
 portENTER_CRITICAL(&media_lock);
 ok=owner!=R224_MEDIA_NONE&&lease!=0&&audio_owner==owner&&audio_token==lease;
 portEXIT_CRITICAL(&media_lock);
 return ok;
}
bool r224_sd_claim(r224_sd_owner_t owner,uint32_t *lease){
 if(owner<=R224_SD_NONE||owner>R224_SD_USB||!lease)return false;
 bool ok=false;
 portENTER_CRITICAL(&media_lock);
 if(sd_owner==R224_SD_NONE){
  sd_owner=owner;sd_token=new_token();*lease=sd_token;ok=true;
 }
 portEXIT_CRITICAL(&media_lock);
 return ok;
}
bool r224_sd_release(r224_sd_owner_t owner,uint32_t lease){
 bool ok=false;
 portENTER_CRITICAL(&media_lock);
 if(owner!=R224_SD_NONE&&lease!=0&&sd_owner==owner&&sd_token==lease){
  sd_owner=R224_SD_NONE;sd_token=0;ok=true;
 }
 portEXIT_CRITICAL(&media_lock);
 return ok;
}
bool r224_sd_owned(r224_sd_owner_t owner,uint32_t lease){
 bool ok=false;
 portENTER_CRITICAL(&media_lock);
 ok=owner!=R224_SD_NONE&&lease!=0&&sd_owner==owner&&sd_token==lease;
 portEXIT_CRITICAL(&media_lock);
 return ok;
}
