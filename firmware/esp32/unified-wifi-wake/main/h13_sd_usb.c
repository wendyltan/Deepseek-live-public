// SPDX-License-Identifier: MIT
// ESP32-only USB-JTAG to in-slot exFAT, no Mac disk access and no /dev access.
#include "h13_sd_usb.h"
#include "r83_user_sd.h"
#include "h12_sd_motion.h"
#include "h12_motion_hashes.h"
#ifdef DF_R150_ALL106
#include "r150_rules_model.h"
#endif
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "esp_log.h"
#include "esp_heap_caps.h"
#include "driver/usb_serial_jtag.h"
#include "ff.h"
#include "diskio_impl.h"
#include "diskio_sdmmc.h"
#include "mbedtls/base64.h"
#include "mbedtls/sha256.h"
#include "freertos/FreeRTOS.h"
#define MAX_CHUNK 8192
static const char *TAG="H13_USB_SD";
static FATFS fs;
static BYTE drive_number=FF_DRV_NOT_USED;
static char root[8]={0};
static bool mounted=false;
static bool opened=false;
static FIL file;
static const h12_trusted_hash *expected;
static size_t received;
static uint32_t next_seq;
// Scoped R161 repair of exactly one R156 interrupted, never-verified file.
// This deliberately cannot unlink ANY of the factory35 or other assets.
static unsigned r161_m037_short_bytes=0;
static TickType_t r161_m037_inspected_tick=0;
static mbedtls_sha256_context sha;
static FIL playback_file;
static bool playback_open=false;
static uint32_t playback_length=0;
// R48: One-boot authenticated motion cache. Full content SHA must pass before
// caching. The cache never persists to SD/NVS; any normal upload invalidates
// its entry before truncation. Cache hits additionally check FatFs metadata.
#define R48_TRUSTED_COUNT (sizeof(h12_trusted_motions)/sizeof(h12_trusted_motions[0]))
static bool r48_verified[R48_TRUSTED_COUNT];
static WORD r48_date[R48_TRUSTED_COUNT],r48_time[R48_TRUSTED_COUNT];
uint64_t h13_sd_known_motion_bytes(void){
    uint64_t bytes=0;
    for(size_t i=0;i<R48_TRUSTED_COUNT;i++)bytes+=h12_trusted_motions[i].size;
    return bytes;  // SHA-pinned known files only; never claim entire SD usage
}
static int r48_index(unsigned id){
    for(size_t i=0;i<R48_TRUSTED_COUNT;i++)
        if(h12_trusted_motions[i].id==id)return (int)i;
    return -1;
}
static void r48_invalidate(unsigned id){
    int i=r48_index(id);
    if(i>=0)r48_verified[i]=false;
}

static void reply(const char*line){
    (void)usb_serial_jtag_write_bytes(line,strlen(line),pdMS_TO_TICKS(3000));
}
static void nack(const char *cause){
    char line[94];int n=snprintf(line,sizeof(line),"@@DFSD2 ERROR code=%s\n",cause);
    if(n>0&&(size_t)n<sizeof(line))reply(line);
}
static void close_current(bool discard){
    if(!opened)return;
    (void)f_close(&file);
    if(discard){
        char path[35];
        if(expected){
            snprintf(path,sizeof(path),"%s/DAFEIYU/MOTIONS/M%03u.DFS",root,expected->id);
            (void)f_unlink(path); // only the particular named selected file
        }
    }
    mbedtls_sha256_free(&sha);
    opened=false;expected=NULL;received=0;next_seq=0;
}
/* R87: first H13 FatFs mount/drive cause, read-only scalar receipts. */
static volatile unsigned r87_mount_step=0,r87_capacity=0,r87_sector=0,r87_drive=999;
static volatile int r87_esp_err=0,r87_fatfs_err=999;
void h13_r87_mount_trace(unsigned *step,unsigned *sector,unsigned *capacity,
                          unsigned *drive,int *esp_err,int *fresult){
    if(step)*step=r87_mount_step;
    if(sector)*sector=r87_sector;
    if(capacity)*capacity=r87_capacity;
    if(drive)*drive=r87_drive;
    if(esp_err)*esp_err=r87_esp_err;
    if(fresult)*fresult=r87_fatfs_err;
}
static bool ready(void){
    if(mounted){r87_mount_step=8;return true;}
    r87_mount_step=1;r87_esp_err=0;r87_fatfs_err=999;r87_drive=999;
    sdmmc_card_t *card=h12_sd_card_for_usb_upload();
    r87_mount_step=2;
    r87_capacity=card?(unsigned)card->csd.capacity:0;
    r87_sector=card?(unsigned)card->csd.sector_size:0;
    if(!card||card->csd.sector_size!=512 || card->csd.capacity<110000000U ||
       card->csd.capacity>140000000U){
        r87_mount_step=91;
        nack("missing_real_sd_card");return false;
    }
    r87_mount_step=3;
    esp_err_t e=ff_diskio_get_drive(&drive_number);
    r87_esp_err=(int)e;r87_drive=(unsigned)drive_number;
    if(e!=ESP_OK||drive_number==FF_DRV_NOT_USED){
        r87_mount_step=92;
        nack("drive_unavailable");return false;
    }
    r87_mount_step=4;
    ff_diskio_register_sdmmc(drive_number,card);
    snprintf(root,sizeof(root),"%u:",(unsigned)drive_number);
    r87_mount_step=5;
    FRESULT r=f_mount(&fs,root,1);
    r87_fatfs_err=(int)r;
    if(r!=FR_OK){
        r87_mount_step=93;
        ESP_LOGW(TAG,"existing_exfat_mount_failed res=%u",(unsigned)r);
        ff_diskio_unregister(drive_number);
        drive_number=FF_DRV_NOT_USED;
        nack("exfat_mount_failed_no_format");return false;
    }
    // Before any writing, insist on exFAT as previously selected by user.
    // Read-only boot parser in H12 already checked this same volume.
    mounted=true;r87_mount_step=8;
    ESP_LOGI(TAG,"H13_EXFAT_MOUNT_OK card_sector=512 volume=user_micro_sd");
    return true;
}
const char *h13_sd_user_root(void){return ready()?root:NULL;}
// Only called from the optional background storage-stats task.
// It uses exFAT allocation information, not the fixed manifest-size sum.
int h13_sd_usage_bytes(uint64_t *total,uint64_t *used){
    if(!total||!used||h13_sd_usb_active())return -1;
    *total=0;*used=0;
    const char *drive=h13_sd_user_root();
    if(!drive)return -2;
    DWORD free_clusters=0;FATFS *actual=NULL;
    FRESULT rc=f_getfree(drive,&free_clusters,&actual);
    if(rc!=FR_OK||!actual||actual->n_fatent<2||
       free_clusters>actual->n_fatent-2||!actual->csize)return -3;
    uint64_t clusters=(uint64_t)(actual->n_fatent-2);
    uint64_t sectors=clusters*(uint64_t)actual->csize;
    uint64_t empty=(uint64_t)free_clusters*actual->csize;
    // A forged/corrupted exFAT header must not overflow bytes or advertise
    // a filesystem larger than the physical card whose CSD was verified.
    // No SD writes, format operations or USB transfers in this code path.
    if(sectors>UINT64_MAX/512ULL || !r87_capacity ||
       sectors>(uint64_t)r87_capacity)return -3;
    *total=sectors*512ULL;
    *used=(sectors-empty)*512ULL;
    return *total>=*used && *total>0 ? 0 : -4;
}
// A write-stream digest is insufficient: verify actual FATFS data on SD
// *after* fsync/close before promising host a completed animation.
static bool verify_card_file(unsigned id,const h12_trusted_hash *manifest){
    char path[50];snprintf(path,sizeof(path),
        "%s/DAFEIYU/MOTIONS/M%03u.DFS",root,id);
    FIL check;
    if(f_open(&check,path,FA_READ)!=FR_OK)return false;
    bool good=(f_size(&check)==manifest->size);
    mbedtls_sha256_context ctx;mbedtls_sha256_init(&ctx);
    if(good && mbedtls_sha256_starts(&ctx,0)!=0)good=false;
    // R49: replace thousands of tiny 1KiB f_read calls with a bounded
    // 16KiB internal-RAM buffer. If resources are limited, retain the
    // previously validated 1KiB stack fallback, never skip SHA verification.
    unsigned char fallback[1024];
    unsigned char *block=heap_caps_malloc(16u*1024u,
                         MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT);
    const size_t block_cap=block?16u*1024u:sizeof(fallback);
    if(!block)block=fallback;
    uint32_t seen=0;
    while(good && seen<manifest->size){
        UINT n=0;
        size_t wanted=manifest->size-seen;
        if(wanted>block_cap)wanted=block_cap;
        FRESULT fr=f_read(&check,block,(UINT)wanted,&n);
        if(fr!=FR_OK||n==0||n>manifest->size-seen||
           mbedtls_sha256_update(&ctx,block,n)!=0){good=false;break;}
        seen+=n;
    }
    unsigned char digest[32];
    if(good&&(seen!=manifest->size||
       mbedtls_sha256_finish(&ctx,digest)!=0||
       memcmp(digest,manifest->digest,sizeof(digest))!=0))good=false;
    mbedtls_sha256_free(&ctx);
    if(block!=fallback)heap_caps_free(block);
    if(f_close(&check)!=FR_OK)good=false;
    return good;
}
// R57 text-only offline preset cards. Provision once into a dedicated SD
// folder, never overwrite a user-edited preset and never touch MOTIONS.
// All SD I/O is finished before the animation worker starts; runtime reads
// only the tiny bounded in-RAM cache, avoiding concurrent SDMMC readers.
#define R57_PRESET_COUNT 4
static char r57_presets[R57_PRESET_COUNT][128];
static const char *r57_default_presets[R57_PRESET_COUNT]={
    "你好，大肥鱼在这里！",
    "开心一下，今天也要元气满满！",
    "晚安，做个好梦。",
    "谢谢你，我会继续努力。"
};
int h13_sd_presets_prepare(void){
    if(!h12_sd_available() || !ready())return -1;
    char dir[40];snprintf(dir,sizeof(dir),"%s/DAFEIYU/PRESETS",root);
    FRESULT mk=f_mkdir(dir);
    if(mk!=FR_OK && mk!=FR_EXIST){
        ESP_LOGW(TAG,"R57_PRESET_SD_DIR_UNAVAILABLE status=%u",(unsigned)mk);
        return -1;
    }
    unsigned loaded=0;
    for(unsigned i=0;i<R57_PRESET_COUNT;i++){
        char path[65];
        snprintf(path,sizeof(path),"%s/P%03u.TXT",dir,i+1);
        FIL f;FRESULT fr=f_open(&f,path,FA_READ);
        if(fr==FR_NO_FILE){
            // Create only a missing named file; never truncate existing data.
            fr=f_open(&f,path,FA_CREATE_NEW|FA_WRITE);
            if(fr!=FR_OK)continue;
            const char *src=r57_default_presets[i];
            UINT wrote=0;unsigned n=(unsigned)strlen(src);
            bool ok=f_write(&f,src,n,&wrote)==FR_OK && wrote==n;
            if(ok)ok=f_sync(&f)==FR_OK;
            (void)f_close(&f);
            if(!ok)continue;
            fr=f_open(&f,path,FA_READ);
        }
        if(fr!=FR_OK)continue;
        FSIZE_t sz=f_size(&f);
        UINT got=0;
        if(sz>0 && sz<sizeof(r57_presets[i]) &&
            f_read(&f,r57_presets[i],(UINT)sz,&got)==FR_OK &&
            got==sz){
            bool safe=true;
            for(unsigned k=0;k<got;k++){
                if((unsigned char)r57_presets[i][k]<32u){safe=false;break;}
            }
            if(safe){r57_presets[i][got]=0;loaded++;}
            else r57_presets[i][0]=0;
        }
        (void)f_close(&f);
    }
    ESP_LOGI(TAG,"R57_SD_PRESETS_READY count=%u/4 text_only=1",loaded);
    return loaded==R57_PRESET_COUNT?0:-1;
}
int h13_sd_preset_copy(unsigned index,char *dst,size_t cap){
    if(!dst||cap==0||index>=R57_PRESET_COUNT)return -1;
    size_t n=strlen(r57_presets[index]);
    if(n==0||n>=cap)return -1;
    memcpy(dst,r57_presets[index],n+1);
    return 0;
}
bool h13_sd_usb_active(void){return opened;}
// The same mount that *wrote* the exFAT file must read it for the renderer.
// H12's pre-existing raw-directory reader is retained only for older builds:
// FatFs-created exFAT directory geometry cannot be assumed identical to the
// synthetic host fixture, and no fake APPLIED receipt is permissible.
/* R86 last read-only selected35 scan, no SD writes. */
static volatile unsigned r86_stage=0,r86_bad_id=999,r86_expected=0,
                         r86_actual=0,r86_good=0;
static volatile int r86_fresult=0;
void h13_r86_trace(unsigned *stage,unsigned *bad_id,int *fs_error,
                    unsigned *expected,unsigned *actual,unsigned *found){
    if(stage)*stage=r86_stage;
    if(bad_id)*bad_id=r86_bad_id;
    if(fs_error)*fs_error=r86_fresult;
    if(expected)*expected=r86_expected;
    if(actual)*actual=r86_actual;
    if(found)*found=r86_good;
}
int h13_sd_verify_all35(void){
    r86_stage=1;r86_bad_id=999;r86_expected=0;r86_actual=0;r86_good=0;r86_fresult=0;
    if(!ready()){r86_stage=90;return -1;}
    r86_stage=2;
    unsigned found=0;
    for(unsigned i=0;i<sizeof(h12_trusted_motions)/sizeof(h12_trusted_motions[0]);i++){
        const h12_trusted_hash *item=&h12_trusted_motions[i];
#ifdef DF_R150_ALL106
        // Upgrade keeps exactly the original35 boot requirement. Other71 can
        // be incrementally imported; never strand a working pre-update SD.
        bool factory=false;
        for(unsigned j=0;j<35u;j++)if(r150_factory35_ids[j]==item->id){factory=true;break;}
        if(!factory)continue;
#endif
        char path[60];FILINFO info;
        snprintf(path,sizeof(path),"%s/DAFEIYU/MOTIONS/M%03u.DFS",root,item->id);
        FRESULT res=f_stat(path,&info);
        if(res==FR_OK&&info.fsize==item->size){found++;continue;}
        if(r86_bad_id==999){
            r86_bad_id=item->id;r86_expected=item->size;
            r86_actual=res==FR_OK?(unsigned)info.fsize:0;
            r86_fresult=(int)res;
        }
    }
    r86_good=found;
    // Count the compiled and SHA-approved catalog; new authorized motions
    // may be added without changing this verifier or deleting old entries.
#ifdef DF_R150_ALL106
    const unsigned approved=35u;
#else
    const unsigned approved=(unsigned)(sizeof(h12_trusted_motions)/sizeof(h12_trusted_motions[0]));
#endif
    r86_stage=(found==approved?3:91);
    return found==approved?0:(int)found-(int)approved;
}
int h13_sd_select_verified(unsigned id){
    if(opened||!h12_selected_id(id)||!ready())return -1;
    if(id>=200u && id<=207u){
        unsigned size=0;
        if(!r83_user_slot_verified(id,&size))return -1;
        char user_path[74];
        snprintf(user_path,sizeof(user_path),
                 "%s/DAFEIYU/USER/M%03u.DFS",root,id);
        if(playback_open){(void)f_close(&playback_file);playback_open=false;}
        if(f_open(&playback_file,user_path,FA_READ)!=FR_OK)return -1;
        if(f_size(&playback_file)!=size){
            (void)f_close(&playback_file);return -1;
        }
        playback_length=size;playback_open=true;
        ESP_LOGI(TAG,"R103_USER_SD_PLAYBACK_VERIFIED id=m%03u bytes=%u",id,size);
        return 0;
    }
    const h12_trusted_hash *approved=h12_lookup_hash(id);
    if(!approved)return -1;
    char path[60];snprintf(path,sizeof(path),
             "%s/DAFEIYU/MOTIONS/M%03u.DFS",root,id);
    FILINFO info;
    if(f_stat(path,&info)!=FR_OK||info.fsize!=approved->size){
        r48_invalidate(id);
        return -1;
    }
    int index=r48_index(id);
    bool verified=(index>=0 && r48_verified[index] &&
        r48_date[index]==info.fdate && r48_time[index]==info.ftime);
    if(!verified){
        TickType_t started=xTaskGetTickCount();
        if(!verify_card_file(id,approved)){
            r48_invalidate(id);
            ESP_LOGW(TAG,"H13_MOTION_SHA_FAILED id=%u",id);
            return -1;
        }
        ESP_LOGI(TAG,"R48_MOTION_FIRST_SHA_MS id=%u elapsed=%lu",
            id,(unsigned long)((xTaskGetTickCount()-started)*portTICK_PERIOD_MS));
        if(index>=0){
            r48_date[index]=info.fdate;r48_time[index]=info.ftime;
            r48_verified[index]=true;
        }
    }else{
        ESP_LOGI(TAG,"R48_MOTION_SHA_CACHE_HIT id=%u",id);
    }
    if(playback_open){(void)f_close(&playback_file);playback_open=false;}
    if(f_open(&playback_file,path,FA_READ)!=FR_OK)return -1;
    if(f_size(&playback_file)!=approved->size){
        (void)f_close(&playback_file);return -1;
    }
    playback_length=approved->size;
    playback_open=true;
    ESP_LOGI(TAG,"H13_MOTION_SHA_VERIFIED id=%u bytes=%lu",
            id,(unsigned long)playback_length);
    return 0;
}
void h13_sd_release_selected(void){
    if(playback_open){(void)f_close(&playback_file);playback_open=false;}
    playback_length=0;
}
size_t h13_sd_selected_length(void){return playback_open?playback_length:0;}
size_t h13_sd_selected_read(size_t off,uint8_t *dst,size_t count){
    if(!playback_open||!dst||off>playback_length ||
       count>playback_length-off)return 0;
    if(f_tell(&playback_file)!=(FSIZE_t)off &&
       f_lseek(&playback_file,(FSIZE_t)off)!=FR_OK)return 0;
    UINT got=0;
    if(f_read(&playback_file,dst,(UINT)count,&got)!=FR_OK)return 0;
    return got;
}
void h13_sd_usb_handle(const char *line){
    if(!line||strncmp(line,"@@DFSD2 ",8))return;
    if(strcmp(line,"@@DFSD2 CAPS")==0){
        if(ready())reply("@@DFSD2 READY media=in_slot_sd filesystem=exfat selected=35\n");
        return;
    }
    if(strcmp(line,"@@DFSD2 STATUS")==0){
        if(!opened||!expected){
            reply("@@DFSD2 STATE idle\n");return;
        }
        char state[108];
        int size=snprintf(state,sizeof(state),
            "@@DFSD2 STATE id=m%03u next_seq=%lu bytes=%lu\n",
            expected->id,(unsigned long)next_seq,(unsigned long)received);
        if(size>0 && size<(int)sizeof(state))reply(state);
        return;
    }
    if(strcmp(line,"@@DFSD2 ABORT")==0){
        close_current(true);reply("@@DFSD2 ABORTED\n");return;
    }
    // R170 bounded two-phase forensic check / rename-only recovery.
    // m037 is NOT one of the 35 legacy IDs. Never unlink user or
    // legacy files. Keep the suspect data as M037.BAD for inspection.
    if(strcmp(line,"@@DFSD2 M037_AUDIT")==0){
#ifdef DF_R150_ALL106
        r161_m037_short_bytes=0; // clear stale approval immediately
        if(opened){nack("upload_busy");return;}
        const h12_trusted_hash *trusted=h12_lookup_hash(37u);
        if(!trusted || !ready()){nack("m037_trust_missing");return;}
        char original[65],quarantine[65],out[160];
        snprintf(original,sizeof(original),"%s/DAFEIYU/MOTIONS/M037.DFS",root);
        snprintf(quarantine,sizeof(quarantine),"%s/DAFEIYU/MOTIONS/M037.BAD",root);
        FILINFO info={0};
        FRESULT check=f_stat(original,&info);
        if(check==FR_NO_FILE){
            reply("@@DFSD2 M037_AUDIT state=missing bytes=0\n");
            return;
        }
        if(check!=FR_OK){nack("m037_stat_failure");return;}
        FILINFO backup={0};
        FRESULT backup_check=f_stat(quarantine,&backup);
        if(backup_check!=FR_OK && backup_check!=FR_NO_FILE){
            nack("m037_backup_stat_failure");return;
        }
        bool valid=(info.fsize==trusted->size) &&
             verify_card_file(37u,trusted);
        if(valid){
            snprintf(out,sizeof(out),
                 "@@DFSD2 M037_AUDIT state=valid bytes=%lu expected=%lu backup=%u\n",
                 (unsigned long)info.fsize,(unsigned long)trusted->size,
                 backup_check==FR_OK?1u:0u);
            reply(out);return; // even if playback fails, do not rename
        }
        if(info.fsize > trusted->size){
            // Oversize may be unrelated user content. Diagnose, but refuse.
            snprintf(out,sizeof(out),
                 "@@DFSD2 M037_AUDIT state=oversize bytes=%lu expected=%lu backup=%u\n",
                 (unsigned long)info.fsize,(unsigned long)trusted->size,
                 backup_check==FR_OK?1u:0u);
            reply(out);return;
        }
        const char *state=info.fsize==0?"zero":
            (info.fsize<trusted->size?"short":"sha_mismatch");
        if(backup_check==FR_NO_FILE){
            r161_m037_short_bytes=(unsigned)info.fsize+1u;
            r161_m037_inspected_tick=xTaskGetTickCount();
        }
        snprintf(out,sizeof(out),
            "@@DFSD2 M037_AUDIT state=%s bytes=%lu expected=%lu backup=%u\n",
            state,(unsigned long)info.fsize,(unsigned long)trusted->size,
            backup_check==FR_OK?1u:0u);
        reply(out);return;
#else
        nack("unsupported");return;
#endif
    }
    if(strncmp(line,"@@DFSD2 M037_QUARANTINE bytes=",30)==0){
#ifdef DF_R150_ALL106
        unsigned user_bytes=0;char extra=0;
        if(opened || sscanf(line,"@@DFSD2 M037_QUARANTINE bytes=%u%c",
                            &user_bytes,&extra)!=1 ||
            r161_m037_short_bytes==0 ||
            user_bytes!=r161_m037_short_bytes-1u ||
            (int32_t)(xTaskGetTickCount()-r161_m037_inspected_tick)
              >=pdMS_TO_TICKS(15000)){
            nack("m037_no_recent_audit");return;
        }
        r161_m037_short_bytes=0; // single use even on failed action
        const h12_trusted_hash *trusted=h12_lookup_hash(37u);
        if(!trusted || !ready()){nack("m037_trust_missing");return;}
        char original[65],quarantine[65],out[142];
        snprintf(original,sizeof(original),"%s/DAFEIYU/MOTIONS/M037.DFS",root);
        snprintf(quarantine,sizeof(quarantine),"%s/DAFEIYU/MOTIONS/M037.BAD",root);
        FILINFO found={0},saved={0};
        if(f_stat(original,&found)!=FR_OK || found.fsize!=user_bytes
          || found.fsize>trusted->size || f_stat(quarantine,&saved)!=FR_NO_FILE){
            nack("m037_state_changed_or_backup_exists");return;
        }
        // Full-sized but valid data must never be renamed.
        if(found.fsize==trusted->size && verify_card_file(37u,trusted)){
            nack("m037_valid_refuse_rename");return;
        }
        r48_invalidate(37u);
        if(f_rename(original,quarantine)!=FR_OK){
            nack("m037_rename_failed");return;
        }
        FILINFO now={0},prior={0};
        if(f_stat(original,&now)!=FR_NO_FILE ||
           f_stat(quarantine,&prior)!=FR_OK || prior.fsize!=user_bytes){
            nack("m037_rename_readback_failed");return;
        }
        snprintf(out,sizeof(out),
           "@@DFSD2 M037_QUARANTINED old_bytes=%u backup=M037.BAD\n",
           user_bytes);
        reply(out);return;
#else
        nack("unsupported");return;
#endif
    }
    if(strncmp(line,"@@DFSD2 OPEN ",13)==0){
        unsigned id=0;char after=0;
        if(opened){nack("upload_busy");return;}
        if(sscanf(line,"@@DFSD2 OPEN id=m%u%c",&id,&after)!=1 ||
           !h12_selected_id(id)||(expected=h12_lookup_hash(id))==NULL){
            nack("not_user_selected");return;
        }
        if(!ready()){expected=NULL;return;}
        char folder[38],path[50];
        snprintf(folder,sizeof(folder),"%s/DAFEIYU",root);
        FRESULT result=f_mkdir(folder);
        if(result!=FR_OK&&result!=FR_EXIST){nack("mkdir_failed");expected=NULL;return;}
        snprintf(folder,sizeof(folder),"%s/DAFEIYU/MOTIONS",root);
        result=f_mkdir(folder);
        if(result!=FR_OK&&result!=FR_EXIST){nack("mkdir_failed");expected=NULL;return;}
        snprintf(path,sizeof(path),"%s/M%03u.DFS",folder,id);
        r48_invalidate(id); // invalidate BEFORE the file is created/truncated
#ifdef DF_R150_ALL106
        FILINFO existing={0};
        FRESULT stat=f_stat(path,&existing);
        if(stat!=FR_NO_FILE){
            nack(stat==FR_OK?"motion_already_installed_no_overwrite":"sd_stat_failed");
            expected=NULL;return;
        }
        result=f_open(&file,path,FA_WRITE|FA_CREATE_NEW);
#else
        result=f_open(&file,path,FA_WRITE|FA_CREATE_ALWAYS);
#endif
        if(result!=FR_OK){ESP_LOGE(TAG,"SD_OPEN_FAILED fresult=%d",(int)result);
            nack("file_open_failed");expected=NULL;return;}
        mbedtls_sha256_init(&sha);
        if(mbedtls_sha256_starts(&sha,0)!=0){
            opened=true;close_current(true);nack("hash_init_failed");return;
        }
        opened=true;received=0;next_seq=0;
        char ack[108];
        snprintf(ack,sizeof(ack),"@@DFSD2 OPENED id=m%03u size=%u chunk=%u\n",
                 id,expected->size,MAX_CHUNK);
        reply(ack);return;
    }
    if(strncmp(line,"@@DFSD2 DATA ",13)==0){
        if(!opened||!expected){nack("file_not_open");return;}
        unsigned seq=0;int prefix=0;
        if(sscanf(line,"@@DFSD2 DATA seq=%u %n",&seq,&prefix)!=1||prefix<=0 ||
           seq!=next_seq || next_seq>=1000000){nack("bad_seq");return;}
        const char *b64=line+prefix;
        size_t bytes64=strlen(b64),produced=0;
        if(!bytes64||bytes64>10924||bytes64%4){nack("bad_b64_len");return;}
        static unsigned char data[MAX_CHUNK]; // single USB worker; avoid stack overflow
        if(mbedtls_base64_decode(data,sizeof(data),&produced,
                (const unsigned char*)b64,bytes64)!=0 ||
           !produced || produced>expected->size-received){nack("bad_data");return;}
        UINT written=0;
        FRESULT r=f_write(&file,data,(UINT)produced,&written);
        if(r!=FR_OK||written!=produced){
            ESP_LOGE(TAG,"SD_WRITE_FAILED fresult=%d",(int)r);
            close_current(true);nack("sd_write_failed");return;
        }
        if(mbedtls_sha256_update(&sha,data,produced)!=0){
            close_current(true);nack("hash_error");return;
        }
        received+=produced;next_seq++;
        char ack[76];snprintf(ack,sizeof(ack),"@@DFSD2 ACK seq=%u\n",seq);
        reply(ack);return;
    }
    if(strcmp(line,"@@DFSD2 CLOSE")==0){
        if(!opened||!expected){nack("file_not_open");return;}
        uint8_t digest[32];
        if(received!=expected->size||mbedtls_sha256_finish(&sha,digest)!=0||
           memcmp(digest,expected->digest,sizeof(digest))!=0){
            close_current(true);nack("full_file_sha_mismatch");return;
        }
        unsigned id=expected->id;
        const h12_trusted_hash *manifest=expected;
        if(f_sync(&file)!=FR_OK){close_current(true);nack("fsync_failed");return;}
        close_current(false);
        if(!verify_card_file(id,manifest)){
            char badpath[50];
            snprintf(badpath,sizeof(badpath),"%s/DAFEIYU/MOTIONS/M%03u.DFS",root,id);
            (void)f_unlink(badpath);
            nack("sd_readback_sha_mismatch");return;
        }
        char ack[92];snprintf(ack,sizeof(ack),
                     "@@DFSD2 DONE id=m%03u sha256=verified\n",id);
        reply(ack);return;
    }
    nack("unrecognized_command");
}
