/* R225 white-listed private voice asset upload over verified USB serial.
 * Only own DAFEIYU/VOICE *.TMP, commit with rename after SHA and readback.
 * Caller enforces animation reader PAUSED and audio idle.
 */
#include "r225_voice_upload.h"
#include "h13_sd_usb.h"
#include "ff.h"
#include "mbedtls/base64.h"
#include "mbedtls/sha256.h"
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
typedef struct {const char *name;uint32_t size;uint8_t sha[32];} trusted_t;
static const trusted_t trusted[10]={
{"wake_ack",76844u,{0xa4,0x0b,0x8e,0x72,0xf2,0x1f,0x9a,0xa5,0xab,0x89,0x1f,0xef,0xc1,0x43,0xce,0xe8,0xed,0x93,0x20,0xbb,0x6c,0xf0,0xe4,0xfa,0x25,0xa7,0x9c,0x37,0x21,0x58,0x1e,0x9a}},
{"hello",153644u,{0x2e,0x1e,0xbb,0x23,0x07,0x14,0x6e,0xfb,0x3d,0x68,0x50,0xa0,0x6c,0x55,0xad,0x42,0x28,0xdb,0xa5,0xd3,0xe3,0x03,0xc6,0xc1,0xc4,0x12,0xc2,0x6c,0x8a,0xaf,0x89,0x54}},
{"offline",309164u,{0x26,0x00,0x83,0xd0,0x15,0xc5,0x73,0xb2,0x21,0xb5,0xf9,0x97,0x07,0xaa,0x0f,0x35,0xfb,0xa1,0xe3,0x92,0xb5,0xa2,0x3c,0x2a,0xfa,0x4d,0xb9,0x20,0x4b,0x81,0x20,0xd7}},
{"rice",243884u,{0x05,0xc1,0xcf,0x41,0xc6,0x63,0x6e,0xcb,0xf5,0x66,0x4f,0x4d,0xe3,0x07,0xe0,0xf6,0x70,0x60,0x0a,0xa3,0x81,0xbf,0x8c,0x9d,0xae,0x9d,0xc4,0xe3,0x5c,0x02,0xce,0x47}},
{"status",308204u,{0xc9,0x9d,0x4e,0x83,0x2a,0xb4,0x2d,0x9e,0xba,0xd4,0x18,0xac,0xcd,0xa9,0x46,0xb5,0xc6,0xa0,0xc8,0x28,0x48,0x3c,0x88,0x1c,0x3b,0x93,0xd7,0xb3,0x25,0x00,0x1c,0xd8}},
{"sleep",194924u,{0x76,0xae,0x7a,0x26,0x06,0x8c,0x7b,0x1b,0xe2,0x56,0xdd,0xba,0x6c,0x21,0x0f,0x6d,0xa7,0xc0,0x5e,0x86,0x99,0xa2,0xa4,0x37,0xeb,0x95,0x6d,0x48,0x4e,0x79,0x98,0xc8}},
{"touch",188684u,{0x2a,0x87,0xdb,0x81,0x48,0xdc,0x85,0x77,0xd0,0x95,0x12,0xd0,0x7a,0x6c,0xb2,0x5a,0xc5,0x8e,0xb4,0xea,0x5a,0x49,0x51,0xea,0xe2,0xb9,0x25,0xc4,0x9d,0xf1,0x9f,0xb4}},
{"unknown",301484u,{0x2e,0xf5,0x93,0x78,0xda,0x9e,0x14,0x9d,0xe1,0xe6,0x93,0xcd,0x6f,0x2e,0xa3,0x29,0xf9,0xa7,0x55,0xa0,0xf9,0x5e,0x12,0x54,0xea,0x5d,0x4d,0xfa,0xf2,0x95,0xf7,0xcc}},
{"goodbye",69164u,{0x8e,0xbe,0x2a,0xbd,0x57,0xe1,0x7c,0xbf,0xe1,0xc7,0x15,0x85,0x0e,0x20,0x54,0x8f,0xa4,0xc3,0x85,0xb5,0x83,0xdf,0xd4,0x08,0x40,0x13,0xc8,0x05,0x46,0x36,0xb1,0xf5}},
{"happy",166604u,{0x46,0x57,0xff,0x57,0x4c,0x7d,0x4b,0xff,0x0c,0x70,0x9a,0xe4,0xd1,0xc6,0x7f,0x05,0xcd,0x09,0xe1,0x9d,0x9c,0xa2,0x9f,0x07,0x3d,0x11,0xf3,0x17,0x0a,0x6b,0x07,0x68}}
};
static FIL current={0};static bool active=false;
static int slot=-1;static uint32_t written=0,sequence=0;
static char temp[98]={0},target[98]={0};
static mbedtls_sha256_context digest;
bool r225_voice_upload_active(void){return active;}
static void emit(bool(*tx)(const char*,size_t),const char *s){
 if(tx)(void)tx(s,strlen(s));
}
static void fail(bool(*tx)(const char*,size_t),const char *reason){
 char buf[96];int n=snprintf(buf,sizeof(buf),"@@DFVOICEFILE1 NACK %s\n",reason);
 if(n>0&&(size_t)n<sizeof(buf))emit(tx,buf);
}
static void cancel(void){
 if(active){(void)f_close(&current);(void)f_unlink(temp);
  mbedtls_sha256_free(&digest);}
 active=false;slot=-1;written=0;sequence=0;
 temp[0]=0;target[0]=0;
}
void r225_voice_upload_handle(const char *cmd,bool(*tx)(const char*,size_t)){
 if(!cmd||!tx)return;
 if(strcmp(cmd,"@@DFVOICEFILE1 CAPS")==0){
  emit(tx,"@@DFVOICEFILE1 READY files=10 chunk=1024 format=wav_pcm16_24k\n");
  return;
 }
 if(strcmp(cmd,"@@DFVOICEFILE1 ABORT")==0){
  cancel();emit(tx,"@@DFVOICEFILE1 ABORTED\n");return;
 }
 if(strncmp(cmd,"@@DFVOICEFILE1 OPEN id=",23)==0){
  unsigned id=0;char extra;
  if(active){fail(tx,"busy");return;}
  if(sscanf(cmd,"@@DFVOICEFILE1 OPEN id=%u%c",&id,&extra)!=1||id>=10){
   fail(tx,"id");return;
  }
  const char *root=h13_sd_user_root();
  if(!root){fail(tx,"no_sd");return;}
  char dir[85];int n=snprintf(dir,sizeof(dir),"%s/DAFEIYU",root);
  if(n<1||n>=(int)sizeof(dir)){fail(tx,"path");return;}
  FRESULT r=f_mkdir(dir);if(r!=FR_OK&&r!=FR_EXIST){fail(tx,"dir");return;}
  n=snprintf(dir,sizeof(dir),"%s/DAFEIYU/VOICE",root);
  if(n<1||n>=(int)sizeof(dir)){fail(tx,"path");return;}
  r=f_mkdir(dir);if(r!=FR_OK&&r!=FR_EXIST){fail(tx,"dir");return;}
  n=snprintf(target,sizeof(target),"%s/%s.wav",dir,trusted[id].name);
  if(n<1||n>=(int)sizeof(target)){fail(tx,"path");return;}
  n=snprintf(temp,sizeof(temp),"%s/%s.tmp",dir,trusted[id].name);
  if(n<1||n>=(int)sizeof(temp)){fail(tx,"path");return;}
  FILINFO stat={0};if(f_stat(target,&stat)!=FR_NO_FILE||
       f_stat(temp,&stat)!=FR_NO_FILE){fail(tx,"exists_no_overwrite");return;}
  if(f_open(&current,temp,FA_WRITE|FA_CREATE_NEW)!=FR_OK){
    fail(tx,"open");return;
  }
  mbedtls_sha256_init(&digest);
  if(mbedtls_sha256_starts(&digest,0)!=0){
    active=true;cancel();fail(tx,"hash_init");return;
  }
  active=true;slot=(int)id;written=0;sequence=0;
  char out[116];
  n=snprintf(out,sizeof(out),"@@DFVOICEFILE1 OPENED id=%u bytes=%lu\n",
       id,(unsigned long)trusted[id].size);
  if(n>0&&(size_t)n<sizeof(out))emit(tx,out);
  return;
 }
 if(strncmp(cmd,"@@DFVOICEFILE1 DATA seq=",24)==0){
  if(!active){fail(tx,"not_open");return;}
  unsigned s=0;int prefix=0;
  if(sscanf(cmd,"@@DFVOICEFILE1 DATA seq=%u %n",&s,&prefix)!=1||
     prefix<=0||s!=sequence){fail(tx,"sequence");return;}
  const char *enc=cmd+prefix;size_t chars=strlen(enc),n=0;
  if(!chars||chars>1368||chars%4){fail(tx,"b64_len");return;}
  uint8_t data[1024];
  if(mbedtls_base64_decode(data,sizeof(data),&n,
            (const uint8_t*)enc,chars)!=0||!n||
     n>trusted[slot].size-written){cancel();fail(tx,"invalid_data");return;}
  UINT sent=0;
  if(f_write(&current,data,(UINT)n,&sent)!=FR_OK||sent!=n||
     mbedtls_sha256_update(&digest,data,n)!=0){
    cancel();fail(tx,"write");return;
  }
  written+=(uint32_t)n;sequence++;
  char ack[90];int c=snprintf(ack,sizeof(ack),
     "@@DFVOICEFILE1 ACK seq=%u bytes=%lu\n",s,(unsigned long)written);
  if(c>0&&(size_t)c<sizeof(ack))emit(tx,ack);
  return;
 }
 if(strcmp(cmd,"@@DFVOICEFILE1 CLOSE")==0){
  if(!active){fail(tx,"not_open");return;}
  uint8_t result[32]={0};
  if(written!=trusted[slot].size||
     mbedtls_sha256_finish(&digest,result)!=0||
     memcmp(result,trusted[slot].sha,32)!=0 ||
     f_sync(&current)!=FR_OK){
    cancel();fail(tx,"sha_or_size");return;
  }
  (void)f_close(&current);mbedtls_sha256_free(&digest);active=false;
  FIL check={0};uint8_t check_hash[32]={0};bool okay=true;
  mbedtls_sha256_context verify;mbedtls_sha256_init(&verify);
  if(f_open(&check,temp,FA_READ)!=FR_OK||
     mbedtls_sha256_starts(&verify,0)!=0){okay=false;}
  if(okay){uint8_t buf[1024];UINT got=0;uint32_t count=0;
    while(count<trusted[slot].size){
      UINT request=(trusted[slot].size-count>sizeof(buf)?
                 sizeof(buf):(UINT)(trusted[slot].size-count));
      if(f_read(&check,buf,request,&got)!=FR_OK||got!=request||
         mbedtls_sha256_update(&verify,buf,got)!=0){okay=false;break;}
      count+=got;
    }
    if(okay && (mbedtls_sha256_finish(&verify,check_hash)!=0||
       memcmp(check_hash,trusted[slot].sha,32)!=0))okay=false;
  }
  (void)f_close(&check);mbedtls_sha256_free(&verify);
  FILINFO info={0};
  if(!okay || f_stat(target,&info)!=FR_NO_FILE ||
     f_rename(temp,target)!=FR_OK){
    (void)f_unlink(temp);slot=-1;fail(tx,"readback_or_rename");return;
  }
  char out[98];int c=snprintf(out,sizeof(out),
       "@@DFVOICEFILE1 COMMITTED id=%d bytes=%lu\n",
       slot,(unsigned long)written);
  slot=-1;written=0;sequence=0;temp[0]=0;target[0]=0;
  if(c>0&&(size_t)c<sizeof(out))emit(tx,out);
  return;
 }
 fail(tx,"unknown");
}
