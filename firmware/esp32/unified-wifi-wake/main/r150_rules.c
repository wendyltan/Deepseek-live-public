// R150 opt-in all-106 native rule sidecar, preserves R133 map1 in NVS.
#include "r150_rules.h"
#include "r150_rules_model.h"
#include "r133_features.h"
#include "esp_rom_crc.h"
#include "nvs.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stddef.h>
#include <string.h>
#define R150_MAGIC 0x52313530u
#define R150_LEGACY_MAGIC 0x52543133u
static r150_map_blob active,staged;
static volatile bool have_new=false,open_stage=false,wait_touch=false,approved=false;
static volatile TickType_t touch_deadline,approval_deadline;
static portMUX_TYPE mutex=portMUX_INITIALIZER_UNLOCKED;
static bool nvs_ready=false;
static bool (*sender)(const char*,size_t);
static void send_text(const char *line){if(sender)(void)sender(line,strlen(line));}
static void nack(const char *msg){
    char line[90];snprintf(line,sizeof(line),"@@DFTRIGGER2 NACK reason=%s\n",msg);send_text(line);
}
static uint32_t crc_v2(const r150_map_blob *blob){
    return esp_rom_crc32_le(0,(const uint8_t*)blob,offsetof(r150_map_blob,crc));
}
static bool valid_v2(const r150_map_blob *blob){
    return blob->magic==R150_MAGIC&&blob->version==2&&blob->n==R150_TOTAL&&
           r150_wellformed(blob->group,blob->n)&&blob->crc==crc_v2(blob);
}
static bool valid_old(const r150_legacy_blob *blob){
    if(blob->magic!=R150_LEGACY_MAGIC||blob->version!=1||
       blob->n!=R150_OLD_COUNT||blob->group[0]!=6)return false;
    for(unsigned i=1;i<R150_OLD_COUNT;i++)if(blob->group[i]>5)return false;
    uint32_t crc=esp_rom_crc32_le(0,(const uint8_t*)blob,
                                  offsetof(r150_legacy_blob,crc));
    return crc==blob->crc;
}
void r150_rules_init(void){
    static const uint8_t original35[R150_OLD_COUNT]={
        6,0,2,2,0,2,2,1,1,1,1,0,0,0,0,4,4,4,4,0,0,
        3,3,3,0,0,0,0,0,0,0,3,3,3,3
    };
    memset(&active,0,sizeof(active));
    active.magic=R150_MAGIC;active.version=2;active.n=R150_TOTAL;
    r150_from_legacy(active.group,original35);
    nvs_handle_t handle;
    if(nvs_open("dftrigger",NVS_READONLY,&handle)==ESP_OK){
        nvs_ready=true;
        r150_legacy_blob legacy={0};size_t size=sizeof(legacy);
        if(nvs_get_blob(handle,"map1",&legacy,&size)==ESP_OK&&
           size==sizeof(legacy)&&valid_old(&legacy))
            r150_from_legacy(active.group,legacy.group);
        active.crc=crc_v2(&active);
        r150_map_blob newer={0};size=sizeof(newer);
        if(nvs_get_blob(handle,"map2",&newer,&size)==ESP_OK&&
           size==sizeof(newer)&&valid_v2(&newer)){
            active=newer;have_new=true;
        }
        nvs_close(handle);
    }else{
        nvs_ready=false;
        active.crc=crc_v2(&active);
    }
    staged=active;
}
bool r150_rules_v2_active(void){return have_new;}
unsigned r150_rules_pick(unsigned group,unsigned round,unsigned fallback){
    if(!have_new)return r133_rules_pick(group,round,fallback);
    taskENTER_CRITICAL(&mutex);
    unsigned result=(unsigned)r150_choose(active.group,group,round,fallback);
    taskEXIT_CRITICAL(&mutex);
    return result;
}
static bool approved_now(void){
    if(!approved)return false;
    if((int32_t)(xTaskGetTickCount()-approval_deadline)>=0){
        approved=false;return false;
    }
    return true;
}
bool r150_rules_arm_tap(void){
    if(!wait_touch)return false;
    wait_touch=false;
    if((int32_t)(xTaskGetTickCount()-touch_deadline)>=0)return false;
    approved=true;
    approval_deadline=xTaskGetTickCount()+pdMS_TO_TICKS(60000);
    return true;
}
void r150_rules_command(const char*cmd,bool busy,bool(*send)(const char*,size_t)){
    sender=send;if(!cmd)return;
    if(!strcmp(cmd,"@@DFTRIGGER2 CAPS")){
        send_text(nvs_ready?"@@DFTRIGGER2 READY version=2 count=106 legacy_nvs_preserved=1 touch=1\n":
                "@@DFTRIGGER2 UNAVAILABLE reason=nvs_unavailable\n");return;
    }
    if(!strcmp(cmd,"@@DFTRIGGER2 STATUS")){
        char line[130];snprintf(line,sizeof(line),
           "@@DFTRIGGER2 STATE count=106 crc32=%08lx active=%u stage=%u armed=%u\n",
           (unsigned long)active.crc,have_new,open_stage,approved_now());
        send_text(line);return;
    }
    if(!strncmp(cmd,"@@DFTRIGGER2 GET id=m",21)){
        unsigned ident=999;char trailing=0;
        if(sscanf(cmd,"@@DFTRIGGER2 GET id=m%u%c",&ident,&trailing)!=1 ||
           ident>=R150_TOTAL){nack("invalid_id");return;}
        static const char*names[]={"manual","tap","idle","bonus","work","drag","boot"};
        char line[128];snprintf(line,sizeof(line),
           "@@DFTRIGGER2 RULE id=m%03u group=%s crc32=%08lx\n",
           ident,names[active.group[ident]],(unsigned long)active.crc);
        send_text(line);return;
    }
    if(busy){nack("audio_busy");return;}
    if(!strcmp(cmd,"@@DFTRIGGER2 ARM_REQUEST")){
        if(open_stage){nack("staging");return;}
        wait_touch=true;approved=false;
        touch_deadline=xTaskGetTickCount()+pdMS_TO_TICKS(30000);
        send_text("@@DFTRIGGER2 WAIT_LOCAL_TOUCH seconds=30\n");return;
    }
    if(!strcmp(cmd,"@@DFTRIGGER2 BEGIN")){
        if(!approved_now()){nack("tap_required");return;}
        staged=active;open_stage=true;
        send_text("@@DFTRIGGER2 STAGING\n");return;
    }
    if(!strcmp(cmd,"@@DFTRIGGER2 ABORT")){
        staged=active;open_stage=false;approved=false;
        send_text("@@DFTRIGGER2 ABORTED\n");return;
    }
    if(!strncmp(cmd,"@@DFTRIGGER2 SET ",17)){
        if(!open_stage||!approved_now()){nack("not_authorized");return;}
        unsigned ident=999;char kind[15]={0};char tail=0;
        if(sscanf(cmd,"@@DFTRIGGER2 SET id=m%u group=%14[a-z]%c",
                  &ident,kind,&tail)!=2||ident==0||ident>=R150_TOTAL){
            nack("invalid_rule");return;
        }
        static const char*allowed[]={"manual","tap","idle","bonus","work","drag"};
        int match=-1;for(int i=0;i<6;i++)if(!strcmp(kind,allowed[i]))match=i;
        if(match<0){nack("invalid_group");return;}
        staged.group[ident]=(uint8_t)match;
        char line[98];snprintf(line,sizeof(line),
            "@@DFTRIGGER2 STAGED id=m%03u group=%s\n",ident,kind);
        send_text(line);return;
    }
    if(!strcmp(cmd,"@@DFTRIGGER2 COMMIT")){
        if(!nvs_ready||!open_stage||!approved_now()){nack("not_authorized");return;}
        staged.crc=crc_v2(&staged);
        if(!valid_v2(&staged)){nack("invalid_map");return;}
        nvs_handle_t h;
        if(nvs_open("dftrigger",NVS_READWRITE,&h)!=ESP_OK){nack("open_failed");return;}
        esp_err_t result=nvs_set_blob(h,"map2",&staged,sizeof(staged));
        if(result==ESP_OK)result=nvs_commit(h);
        nvs_close(h);
        if(result!=ESP_OK){nack("commit_failed");return;}
        r150_map_blob readback={0};size_t size=sizeof(readback);
        if(nvs_open("dftrigger",NVS_READONLY,&h)!=ESP_OK){nack("verify_open_failed");return;}
        result=nvs_get_blob(h,"map2",&readback,&size);nvs_close(h);
        if(result!=ESP_OK||size!=sizeof(readback)||!valid_v2(&readback)||
           memcmp(&staged,&readback,sizeof(readback))!=0){
            nack("readback_failed");return;
        }
        taskENTER_CRITICAL(&mutex);
        active=readback;have_new=true;
        taskEXIT_CRITICAL(&mutex);
        open_stage=false;approved=false;
        char line[104];snprintf(line,sizeof(line),
         "@@DFTRIGGER2 APPLIED count=106 crc32=%08lx\n",(unsigned long)active.crc);
        send_text(line);return;
    }
    nack("unsupported");
}
