/* R224: pre-recorded Qwen WAV -> local SD read -> ESP32 codec.
 * Zero Mac, Wi-Fi or DSH dependency. No card writes or USB operations.
 * Not connected to WakeNet/MultiNet yet; all calls require exclusive owner.
 */
#include "r224_sd_voice_player.h"
#include "h13_sd_usb.h"
#include "ff.h"
#include "esp_log.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static const char *TAG="R224_OFFLINE_VOICE";
int r224_play_onboard_sd(r224_clip_t id,esp_codec_dev_handle_t speaker,
                        bool (*exclusive)(void),int volume){
 const char *filename=r224_clip_filename(id);
 if(!filename||!speaker||!exclusive||!exclusive())return -1;
 if(h13_sd_usb_active())return -2;
 const char *root=h13_sd_user_root();
 if(!root)return -3;
 char path[90];
 int size=snprintf(path,sizeof(path),"%s/DAFEIYU/VOICE/%s",root,filename);
 if(size<=0||size>=(int)sizeof(path))return -4;
 FILINFO info={0};
 if(f_stat(path,&info)!=FR_OK ||info.fsize<46||info.fsize>750000)return -5;
 // exFAT FIL currently occupies 4176 bytes; keep it off task stacks.
 FIL *file=calloc(1,sizeof(*file));
 if(!file)return -15;
 if(f_open(file,path,FA_READ)!=FR_OK){free(file);return -6;}
 int rc=-7;bool codec=false;
 uint8_t header[44]={0};UINT got=0;
 if(f_read(file,header,44,&got)!=FR_OK||got!=44||
    !r224_wav_header_valid(header,44,(uint32_t)info.fsize))goto done;
 if(!exclusive()||h13_sd_usb_active()){rc=-8;goto done;}
 esp_codec_dev_sample_info_t format={.sample_rate=24000,.channel=1,.bits_per_sample=16};
 if(esp_codec_dev_open(speaker,&format)!=ESP_CODEC_DEV_OK){rc=-9;goto done;}
 codec=true;
 if(esp_codec_dev_set_out_vol(speaker,volume)!=ESP_CODEC_DEV_OK){rc=-10;goto done;}
 // Fixed 20ms PCM16 frames; avoids allocating the entire WAV in internal RAM.
 // Only the final partial frame gets zero padding, at most 19.9ms.
 int16_t *frame=calloc(480,sizeof(*frame));
 if(!frame){rc=-16;goto done;}
 uint32_t left=(uint32_t)info.fsize-44;
 while(left){
  if(!exclusive()||h13_sd_usb_active()){rc=-11;break;}
  UINT ask=(UINT)(left>960?960:left);
  if((ask&1)!=0){rc=-12;break;}
  memset(frame,0,960);got=0;
  if(f_read(file,frame,ask,&got)!=FR_OK||got!=ask){rc=-13;break;}
  if(esp_codec_dev_write(speaker,frame,960)!=ESP_CODEC_DEV_OK){rc=-14;break;}
  left-=got;
 }
 free(frame);
 if(left==0 && rc==-7)rc=0;
done:
 if(codec && esp_codec_dev_close(speaker)!=ESP_CODEC_DEV_OK && rc==0)rc=-18;
 if(f_close(file)!=FR_OK && rc==0)rc=-17;
 free(file);
 // No private filename, WAV waveform, wake transcript or credentials in logs.
 if(rc)ESP_LOGW(TAG,"OFFLINE_CLIP_DECLINED code=%d",rc);
 return rc;
}
