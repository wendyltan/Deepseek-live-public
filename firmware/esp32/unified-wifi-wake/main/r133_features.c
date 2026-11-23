// R133 isolated experimental firmware module. Not part of production build.
#include "r133_features.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "esp_heap_caps.h"
#include "esp_rom_crc.h"
#include "esp_lv_adapter.h"
#include "lvgl.h"
#include "mbedtls/base64.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stddef.h>
#define MOTION_COUNT 35u
#define RULE_MAGIC 0x52543133u
#define SCREEN_BYTES (480u*480u*2u)
static const uint16_t ids[MOTION_COUNT]={0,1,2,3,8,10,11,13,14,15,16,18,19,20,23,24,25,26,27,28,30,61,62,67,70,71,72,73,75,80,81,83,97,99,105};
static const uint8_t defaults[MOTION_COUNT]={6,0,2,2,0,2,2,1,1,1,1,0,0,0,0,4,4,4,4,0,0,3,3,3,0,0,0,0,0,0,0,3,3,3,3};
typedef struct {uint32_t magic;uint16_t version,n;uint8_t group[MOTION_COUNT];uint32_t crc;} RuleBlob;
static RuleBlob active,staged;
static bool nvs_ok=false,stage_open=false;
static volatile bool wait_touch=false,auth=false;
static volatile TickType_t touch_deadline=0,auth_deadline=0;
static portMUX_TYPE rule_mux=portMUX_INITIALIZER_UNLOCKED;
static bool (*send_line)(const char*,size_t)=NULL;
static uint32_t crc_rule(const RuleBlob *b){return esp_rom_crc32_le(0,(const uint8_t*)b,offsetof(RuleBlob,crc));}
static void emit(const char *s){if(send_line)(void)send_line(s,strlen(s));}
static void nack(const char *s){char r[112];snprintf(r,sizeof(r),"@@DFTRIGGER1 NACK reason=%s\n",s);emit(r);}
static int find_id(unsigned id){for(unsigned i=0;i<MOTION_COUNT;i++)if(ids[i]==id)return (int)i;return -1;}
static bool valid(const RuleBlob *b){
 if(b->magic!=RULE_MAGIC||b->version!=1||b->n!=MOTION_COUNT||b->group[0]!=6||b->crc!=crc_rule(b))return false;
 for(unsigned i=0;i<MOTION_COUNT;i++)if(b->group[i]>6||(i>0&&b->group[i]==6))return false;
 return true;
}
static bool auth_live(void){
 if(!auth)return false;
 if((int32_t)(xTaskGetTickCount()-auth_deadline)>=0){auth=false;return false;}
 return true;
}
void r133_rules_init(void){
 memset(&active,0,sizeof(active));active.magic=RULE_MAGIC;active.version=1;active.n=MOTION_COUNT;
 memcpy(active.group,defaults,sizeof(defaults));active.crc=crc_rule(&active);
 if(nvs_flash_init()==ESP_OK){
   nvs_ok=true;nvs_handle_t h;
   if(nvs_open("dftrigger",NVS_READONLY,&h)==ESP_OK){
     RuleBlob saved={0};size_t len=sizeof(saved);
     if(nvs_get_blob(h,"map1",&saved,&len)==ESP_OK&&len==sizeof(saved)&&valid(&saved))active=saved;
     nvs_close(h);
   }
 }
 staged=active;
}
unsigned r133_rules_pick(unsigned group,unsigned round,unsigned fallback){
 if(group<1||group>5)return fallback;
 unsigned found=0,selected=fallback;
 taskENTER_CRITICAL(&rule_mux);
 for(unsigned i=0;i<MOTION_COUNT;i++)if(active.group[i]==group)found++;
 if(found){
   unsigned n=round%found;
   for(unsigned i=0;i<MOTION_COUNT;i++)if(active.group[i]==group && n--==0){
       selected=ids[i];break;
   }
 }
 taskEXIT_CRITICAL(&rule_mux);
 return selected;
}
bool r133_rules_arm_tap(void){
 if(!wait_touch)return false;
 wait_touch=false;
 if((int32_t)(xTaskGetTickCount()-touch_deadline)>=0)return false;
 auth=true;auth_deadline=xTaskGetTickCount()+pdMS_TO_TICKS(60000);return true;
}
void r133_rules_command(const char *cmd,bool busy,bool (*send)(const char*,size_t)){
 send_line=send;if(!cmd)return;
 if(strcmp(cmd,"@@DFTRIGGER1 CAPS")==0){
   emit(nvs_ok?
      "@@DFTRIGGER1 READY version=1 persistent=nvs local_confirmation=1 dynamic=1\n":
      "@@DFTRIGGER1 UNAVAILABLE reason=nvs_unavailable\n");return;
 }
 if(strcmp(cmd,"@@DFTRIGGER1 STATUS")==0){
   char r[115];snprintf(r,sizeof(r),"@@DFTRIGGER1 STATE count=35 crc32=%08lx stage=%u armed=%u nvs=%u\n",
      (unsigned long)active.crc,(unsigned)stage_open,(unsigned)auth_live(),(unsigned)nvs_ok);
   emit(r);return;
 }
 if(busy){nack("audio_busy");return;}
 if(strcmp(cmd,"@@DFTRIGGER1 ARM_REQUEST")==0){
   if(stage_open){nack("stage_busy");return;}
   auth=false;wait_touch=true;touch_deadline=xTaskGetTickCount()+pdMS_TO_TICKS(30000);
   emit("@@DFTRIGGER1 WAIT_LOCAL_TOUCH seconds=30\n");return;
 }
 if(strcmp(cmd,"@@DFTRIGGER1 BEGIN")==0){
   if(!auth_live()){nack("physical_tap_required");return;}
   staged=active;stage_open=true;emit("@@DFTRIGGER1 STAGING\n");return;
 }
 if(strcmp(cmd,"@@DFTRIGGER1 ABORT")==0){
   staged=active;stage_open=false;auth=false;emit("@@DFTRIGGER1 ABORTED\n");return;
 }
 if(strncmp(cmd,"@@DFTRIGGER1 SET ",17)==0){
   if(!stage_open||!auth_live()){nack("not_authorized");return;}
   unsigned id=999;char kind[15]={0},extra=0;
   if(sscanf(cmd,"@@DFTRIGGER1 SET id=m%u group=%14[a-z]%c",&id,kind,&extra)!=2){nack("bad_binding");return;}
   int index=find_id(id);if(index<1){nack("protected_id");return;}
   static const char *allowed[]={"manual","tap","idle","bonus","work","drag"};
   int match=-1;for(int k=0;k<6;k++)if(strcmp(kind,allowed[k])==0)match=k;
   if(match<0){nack("bad_group");return;}
   staged.group[index]=(uint8_t)match;
   char row[95];snprintf(row,sizeof(row),"@@DFTRIGGER1 STAGED id=m%03u group=%s\n",id,kind);
   emit(row);return;
 }
 if(strcmp(cmd,"@@DFTRIGGER1 COMMIT")==0){
   if(!stage_open||!auth_live()||!nvs_ok){nack("not_authorized");return;}
   staged.crc=crc_rule(&staged);
   if(!valid(&staged)){nack("invalid_rule_map");return;}
   nvs_handle_t h;esp_err_t rc=nvs_open("dftrigger",NVS_READWRITE,&h);
   if(rc!=ESP_OK){nack("nvs_open");return;}
   rc=nvs_set_blob(h,"map1",&staged,sizeof(staged));
   if(rc==ESP_OK)rc=nvs_commit(h);
   nvs_close(h);
   if(rc!=ESP_OK){nack("nvs_commit");return;}
   RuleBlob check={0};size_t bytes=sizeof(check);
   rc=nvs_open("dftrigger",NVS_READONLY,&h);
   if(rc!=ESP_OK){nack("nvs_verify_open");return;}
   rc=nvs_get_blob(h,"map1",&check,&bytes);nvs_close(h);
   if(rc!=ESP_OK||bytes!=sizeof(check)||!valid(&check)||
      memcmp(&staged,&check,sizeof(check))!=0){nack("nvs_verify_failed");return;}
   taskENTER_CRITICAL(&rule_mux);
   active=check;
   taskEXIT_CRITICAL(&rule_mux);
   stage_open=false;auth=false;
   char row[105];snprintf(row,sizeof(row),
      "@@DFTRIGGER1 APPLIED count=35 crc32=%08lx\n",(unsigned long)active.crc);
   emit(row);return;
 }
 if(strncmp(cmd,"@@DFTRIGGER1 GET id=m",21)==0){
   unsigned id=999;char tail=0;
   if(sscanf(cmd,"@@DFTRIGGER1 GET id=m%u%c",&id,&tail)!=1){nack("bad_get");return;}
   int at=find_id(id);if(at<0){nack("unknown_id");return;}
   static const char* names[]={"manual","tap","idle","bonus","work","drag","boot"};
   char row[110];snprintf(row,sizeof(row),
     "@@DFTRIGGER1 RULE id=m%03u group=%s crc32=%08lx\n",
     id,names[active.group[at]],(unsigned long)active.crc);emit(row);return;
 }
 nack("unsupported_command");
}
static uint8_t *screen_buf=NULL;
static unsigned screen_index=0;
static uint32_t screen_crc=0;
static TickType_t screen_until=0;
static volatile bool screen_cancel=false;
void r133_screen_abort_requested(void){if(screen_buf)screen_cancel=true;}
static void screen_drop(void){
 if(screen_buf)heap_caps_free(screen_buf);
 screen_buf=NULL;screen_index=0;screen_cancel=false;
}
void r133_screen_command(const char *cmd,bool busy,bool (*send)(const char*,size_t)){
 send_line=send;if(!cmd)return;
 if(strcmp(cmd,"@@DFSCREEN3 CAPS")==0){
  emit("@@DFSCREEN3 READY width=480 height=480 format=rgb565 chunks=600 pull=1\n");return;
 }
 if(strcmp(cmd,"@@DFSCREEN3 ABORT")==0){screen_drop();emit("@@DFSCREEN3 ABORTED\n");return;}
 if(busy||screen_cancel){screen_drop();emit("@@DFSCREEN3 NACK reason=audio_priority\n");return;}
 if(strcmp(cmd,"@@DFSCREEN3 START")==0){
   screen_drop();screen_buf=heap_caps_aligned_alloc(16,SCREEN_BYTES,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
   if(!screen_buf){emit("@@DFSCREEN3 NACK reason=psram\n");return;}
   lv_image_dsc_t snap={0};lv_result_t rc=LV_RESULT_INVALID;
   if(esp_lv_adapter_lock(1200)==ESP_OK){
     rc=lv_snapshot_take_to_buf(lv_screen_active(),LV_COLOR_FORMAT_RGB565,&snap,screen_buf,SCREEN_BYTES);
     esp_lv_adapter_unlock();
   }
   if(rc!=LV_RESULT_OK||snap.header.w!=480||snap.header.h!=480||snap.header.stride!=960||snap.data!=screen_buf||snap.data_size>SCREEN_BYTES){
     screen_drop();emit("@@DFSCREEN3 NACK reason=invalid_snapshot\n");return;
   }
   screen_crc=esp_rom_crc32_le(0,screen_buf,SCREEN_BYTES);
   screen_until=xTaskGetTickCount()+pdMS_TO_TICKS(60000);
   char row[120];snprintf(row,sizeof(row),"@@DFSCREEN3 BEGIN bytes=460800 chunks=600 crc32=%08lx\n",(unsigned long)screen_crc);
   emit(row);return;
 }
 if(strncmp(cmd,"@@DFSCREEN3 NEXT index=",23)==0){
   unsigned index=999;char tail=0;
   if(sscanf(cmd,"@@DFSCREEN3 NEXT index=%u%c",&index,&tail)!=1||!screen_buf||index!=screen_index){
     screen_drop();emit("@@DFSCREEN3 NACK reason=bad_seq\n");return;
   }
   if((int32_t)(xTaskGetTickCount()-screen_until)>=0){screen_drop();emit("@@DFSCREEN3 NACK reason=expired\n");return;}
   uint8_t encoded[1032]={0};size_t written=0;
   if(mbedtls_base64_encode(encoded,sizeof(encoded),&written,screen_buf+index*768u,768u)!=0){
     screen_drop();emit("@@DFSCREEN3 NACK reason=encode\n");return;
   }
   char row[1090];int n=snprintf(row,sizeof(row),"@@DFSCREEN3 DATA index=%u b64=%s\n",index,encoded);
   if(n<=0||n>=(int)sizeof(row)||!send(row,(size_t)n)){screen_drop();return;}
   screen_index++;screen_until=xTaskGetTickCount()+pdMS_TO_TICKS(30000);
   if(screen_index==600u){emit("@@DFSCREEN3 END count=600\n");screen_drop();}
   return;
 }
 emit("@@DFSCREEN3 NACK reason=unknown_command\n");
}
// Run only on the USB owner's task. Never free the framebuffer from mic ISR.
void r133_screen_tick(bool audio_busy){
 if(!screen_buf)return;
 if(audio_busy||screen_cancel||(int32_t)(xTaskGetTickCount()-screen_until)>=0)
   screen_drop();
}
