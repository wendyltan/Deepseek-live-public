// SPDX-License-Identifier: MIT
// R83 isolated prototype. Do not flash until physical LCD/SD QA passes.
// Separate user IDs 200-207; immutable original selected35 stored elsewhere.
// Never writes without a local avatar tap after a specific USB ARM_REQUEST.
#include "r83_user_sd.h"
#include "h13_sd_usb.h"
#include "h12_sd_motion.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "driver/usb_serial_jtag.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "ff.h"
#include "mbedtls/base64.h"
#include "mbedtls/sha256.h"
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>

#define USER_FIRST 200u
#define USER_LAST 207u
#define CHUNK 1536u
#define MIN_FILE 128u
#define MAX_FILE 8000000u
#define PHYSICAL_ARM_MS 30000u
#define WRITE_ALLOW_MS 60000u
static const char *TAG="R83_USER_SD";
static volatile TickType_t local_pending_until=0,authorized_until=0;
static volatile bool local_pending=false,local_authorized=false;
static volatile unsigned last_committed_slot=0;
static volatile TickType_t readback_until=0;
static volatile bool upload_in_progress=false;
// Shared SD hardware is read by a separate custom exFAT task. FatFs writes
// must not begin until that task explicitly reaches a quiescent boundary.
static volatile bool sd_writer_pause_requested=false;
static volatile bool sd_animation_quiesced=false;
static volatile TickType_t last_data_tick=0;
static bool r136_pause_sd_for_usb(void){
    sd_animation_quiesced=false;
    sd_writer_pause_requested=true;
    TickType_t deadline=xTaskGetTickCount()+pdMS_TO_TICKS(5000);
    while(!sd_animation_quiesced &&
          (int32_t)(xTaskGetTickCount()-deadline)<0)
        vTaskDelay(pdMS_TO_TICKS(15));
    if(!sd_animation_quiesced){sd_writer_pause_requested=false;return false;}
    return true;
}
static void r136_resume_animation(void){
    sd_writer_pause_requested=false;
    sd_animation_quiesced=false;
}
void r83_animation_sd_quiescent_boundary(void){
    sd_animation_quiesced=sd_writer_pause_requested;
}

static FIL file;
static bool opened=false;
static unsigned slot=0,declared_frames=0;
static unsigned length=0,received=0,next_seq=0;
static unsigned char expected_hash[32];
static char assigned_role[10];
static char temporary[74],final_path[74],class_path[74];
static mbedtls_sha256_context sha_ctx;
static void emit(const char *reply){
    (void)usb_serial_jtag_write_bytes(reply,strlen(reply),pdMS_TO_TICKS(1500));
}
static void reject(const char *reason){
    char msg[102];int n=snprintf(msg,sizeof(msg),"@@DFSD3 NACK reason=%s\n",reason);
    if(n>0 && n<(int)sizeof(msg))emit(msg);
}
static bool user_id(unsigned id){return id>=USER_FIRST && id<=USER_LAST;}
static bool role_ok(const char *role){
    return strcmp(role,"idle")==0 || strcmp(role,"work")==0 ||
           strcmp(role,"reaction")==0 || strcmp(role,"bonus")==0;
}
static bool parse_hash(const char *hex,unsigned char out[32]){
    if(strlen(hex)!=64)return false;
    for(unsigned k=0;k<32;k++){
        int a=-1,b=-1;char c=hex[k*2],d=hex[k*2+1];
        if(c>='0'&&c<='9')a=c-'0';
        else if(c>='a'&&c<='f')a=c-'a'+10;
        if(d>='0'&&d<='9')b=d-'0';
        else if(d>='a'&&d<='f')b=d-'a'+10;
        if(a<0||b<0)return false;
        out[k]=(unsigned char)((a<<4)|b);
    }
    return true;
}
static void fmt_hash(const unsigned char bytes[32],char dst[65]){
    static const char digits[]="0123456789abcdef";
    for(unsigned i=0;i<32;i++){
        dst[2*i]=digits[bytes[i]>>4];dst[2*i+1]=digits[bytes[i]&15u];
    }
    dst[64]=0;
}
static bool is_live(void){
    if(!local_authorized)return false;
    if((int32_t)(xTaskGetTickCount()-authorized_until)>=0){
        local_authorized=false;return false;
    }
    return true;
}
bool r83_arm_touch(void){
    if(!local_pending)return false;
    if((int32_t)(xTaskGetTickCount()-local_pending_until)>=0){
        local_pending=false;return false;
    }
    local_pending=false;
    local_authorized=true;
    authorized_until=xTaskGetTickCount()+pdMS_TO_TICKS(WRITE_ALLOW_MS);
    ESP_LOGI(TAG,"R83_PHYSICAL_TOUCH_AUTH_OK interval_ms=%u",WRITE_ALLOW_MS);
    return true;
}
bool r83_transfer_active(void){return upload_in_progress||sd_writer_pause_requested;}
bool r83_arm_pending(void){
    if(local_pending &&
       (int32_t)(xTaskGetTickCount()-local_pending_until)>=0)
        local_pending=false;
    return local_pending;
}
static void abort_file(void){
    bool owns_temporary=upload_in_progress;
    if(opened){
        (void)f_close(&file);
        mbedtls_sha256_free(&sha_ctx);
        opened=false;
    }
    if(owns_temporary && temporary[0]) (void)f_unlink(temporary);
    // Never remove a previous transaction's stale TMP on unsolicited ABORT.
    upload_in_progress=false;
    received=0;next_seq=0;length=0;
    temporary[0]=0;final_path[0]=0;class_path[0]=0;
    r136_resume_animation();
}
static bool sd_digest(const char *path,unsigned char hash[32],unsigned *bytes){
    FIL reader;
    if(f_open(&reader,path,FA_READ)!=FR_OK)return false;
    unsigned size=(unsigned)f_size(&reader);
    if(size<MIN_FILE||size>MAX_FILE){(void)f_close(&reader);return false;}
    mbedtls_sha256_context ctx;mbedtls_sha256_init(&ctx);
    bool ok=mbedtls_sha256_starts(&ctx,0)==0;
    unsigned pos=0;unsigned char block[1024];
    while(ok && pos<size){
        UINT n=0;UINT wanted=(UINT)(size-pos);
        if(wanted>sizeof(block))wanted=sizeof(block);
        if(f_read(&reader,block,wanted,&n)!=FR_OK||n!=wanted ||
           mbedtls_sha256_update(&ctx,block,n)!=0){ok=false;break;}
        pos+=n;
    }
    if(ok)ok=mbedtls_sha256_finish(&ctx,hash)==0;
    mbedtls_sha256_free(&ctx);
    if(f_close(&reader)!=FR_OK)ok=false;
    if(ok&&bytes)*bytes=size;
    return ok && pos==size;
}
static bool format_ok(const char *path){
    // Strict DFSP packet bounds; avoids accepting a misleading .DFS filename.
    FIL check;
    if(f_open(&check,path,FA_READ)!=FR_OK)return false;
    unsigned filesize=(unsigned)f_size(&check);
    uint8_t header[12]; UINT n=0;bool ok=filesize>=12;
    if(ok)ok=f_read(&check,header,sizeof(header),&n)==FR_OK&&n==sizeof(header);
    if(ok)ok=memcmp(header,"DFSP",4)==0 && header[4]==1u &&
       header[5]==0xf0 && header[6]==0x00 && header[7]==0xf0 && header[8]==0x00 &&
       header[9]==8 && header[10]==declared_frames && header[11]==0;
    uint32_t offset=12;
    for(unsigned i=0;ok&&i<declared_frames;i++){
        uint8_t packet[5];n=0;
        if(offset>filesize||filesize-offset<5u){ok=false;break;}
        if(f_lseek(&check,offset)!=FR_OK ||
           f_read(&check,packet,sizeof(packet),&n)!=FR_OK||n!=sizeof(packet)){
            ok=false;break;
        }
        uint32_t len=(uint32_t)packet[1]|((uint32_t)packet[2]<<8)|
                     ((uint32_t)packet[3]<<16)|((uint32_t)packet[4]<<24);
        if(((packet[0]!=1&&packet[0]!=2)||(i==0&&packet[0]!=1)) ||
           !len||len>65536||len>filesize-offset-5u){ok=false;break;}
        offset+=5u+len;
    }
    if(ok)ok=offset==filesize;
    if(f_close(&check)!=FR_OK)ok=false;
    return ok;
}

bool r83_user_slot_verified(unsigned id,unsigned *bytes){
    /* Run only from animation worker, with no in-flight user SD transaction. */
    if(!user_id(id)||upload_in_progress||opened)return false;
    const char *root=h13_sd_user_root();
    if(!root)return false;
    char dfsp[74],clsfile[74];
    snprintf(dfsp,sizeof(dfsp),"%s/DAFEIYU/USER/M%03u.DFS",root,id);
    snprintf(clsfile,sizeof(clsfile),"%s/DAFEIYU/USER/M%03u.CLS",root,id);
    FILINFO fileinfo={0};
    if(f_stat(dfsp,&fileinfo)!=FR_OK ||
       fileinfo.fsize<MIN_FILE||fileinfo.fsize>MAX_FILE)return false;
    unsigned char digest[32];unsigned size=0;char hex[65];
    if(!sd_digest(dfsp,digest,&size))return false;
    fmt_hash(digest,hex);
    FIL meta;
    if(f_open(&meta,clsfile,FA_READ)!=FR_OK)return false;
    FSIZE_t n=f_size(&meta);
    char txt[130]={0};UINT got=0;
    bool ok=n>0 && n<sizeof(txt) &&
       f_read(&meta,txt,(UINT)n,&got)==FR_OK && got==(UINT)n;
    if(f_close(&meta)!=FR_OK)ok=false;
    char role[10]={0},expected[65]={0},trailing=0;
    unsigned frames=0,stored_bytes=0;
    if(!ok || sscanf(txt,"%9[a-z] %u %u %64[0-9a-f]%c",
                    role,&frames,&stored_bytes,expected,&trailing)!=4 ||
       !role_ok(role)||frames<1||frames>80||size!=stored_bytes ||
       strcmp(expected,hex)!=0)return false;
    FIL sample;
    if(f_open(&sample,dfsp,FA_READ)!=FR_OK)return false;
    uint8_t header[12]={0};got=0;
    ok=f_read(&sample,header,sizeof(header),&got)==FR_OK &&
       got==sizeof(header) && memcmp(header,"DFSP",4)==0 &&
       header[4]==1 && header[5]==0xf0 && header[6]==0 &&
       header[7]==0xf0 && header[8]==0 && header[9]==8 &&
       header[10]==frames && header[11]==0;
    if(f_close(&sample)!=FR_OK)ok=false;
    if(ok&&bytes)*bytes=size;
    return ok;
}

static void r83_usb_command_inner(const char *cmd){
    if(!cmd||strncmp(cmd,"@@DFSD3 ",8)!=0)return;
    if(strcmp(cmd,"@@DFSD3 ARM_REQUEST")==0){
        if(upload_in_progress){reject("write_busy");return;}
        local_authorized=false;
        local_pending=true;
        local_pending_until=xTaskGetTickCount()+pdMS_TO_TICKS(PHYSICAL_ARM_MS);
        emit("@@DFSD3 WAIT_LOCAL_TOUCH seconds=30\n");
        return;
    }
    if(strcmp(cmd,"@@DFSD3 CAPS")==0){
        if(is_live() && h12_sd_available() && !h13_sd_usb_active()){
            emit("@@DFSD3 READY version=1 slots=m200-m207 mode=transactional sha256=1 readback=1 local_confirm=1\n");
        }else emit("@@DFSD3 UNAVAILABLE\n");
        return;
    }
    if(strncmp(cmd,"@@DFSD3 INSPECT id=m",21)==0){
        unsigned id=0;char extra=0;
        if(sscanf(cmd,"@@DFSD3 INSPECT id=m%u%c",&id,&extra)!=1||!user_id(id)){
            reject("invalid_inspect_slot");return;
        }
        if(!is_live()){reject("local_approval_required");return;}
        const char *root=h13_sd_user_root();
        if(!root){reject("sd_unavailable");return;}
        char file_path[74],cls_path[74];
        snprintf(file_path,sizeof(file_path),"%s/DAFEIYU/USER/M%03u.DFS",root,id);
        snprintf(cls_path,sizeof(cls_path),"%s/DAFEIYU/USER/M%03u.CLS",root,id);
        FILINFO stat={0};FRESULT a=f_stat(file_path,&stat);
        FRESULT b=f_stat(cls_path,&stat);
        if(a==FR_NO_FILE && b==FR_NO_FILE){
            char response[65];
            snprintf(response,sizeof(response),"@@DFSD3 MISSING id=m%03u\n",id);
            emit(response);return;
        }
        if(a!=FR_OK||b!=FR_OK){reject("incomplete_or_invalid_slot");return;}
        unsigned char digest[32];unsigned bytes=0;
        if(!sd_digest(file_path,digest,&bytes)){reject("inspect_sd_sha_failed");return;}
        char sha[65];fmt_hash(digest,sha);
        FIL meta;
        if(f_open(&meta,cls_path,FA_READ)!=FR_OK){
            reject("inspect_meta_failed");return;
        }
        char text[130]={0},stored_sha[65]={0},role[10]={0},trailing=0;
        unsigned frames=0,stored_bytes=0;UINT got=0;
        FSIZE_t size=f_size(&meta);
        bool valid=size>0&&size<sizeof(text)&&
                   f_read(&meta,text,(UINT)size,&got)==FR_OK&&got==(UINT)size;
        if(f_close(&meta)!=FR_OK)valid=false;
        if(!valid||sscanf(text,"%9[a-z] %u %u %64[0-9a-f]%c",
            role,&frames,&stored_bytes,stored_sha,&trailing)!=4||
            !role_ok(role)||frames<1||frames>80||stored_bytes!=bytes||
            strcmp(stored_sha,sha)!=0){
            reject("inspect_role_metadata_mismatch");return;
        }
        char response[174];snprintf(response,sizeof(response),
            "@@DFSD3 PRESENT id=m%03u bytes=%u sha256=%s role=%s\n",
            id,bytes,sha,role);
        emit(response);return;
    }
    if(strcmp(cmd,"@@DFSD3 ABORT")==0){
        abort_file();emit("@@DFSD3 ABORTED\n");return;
    }
    if(strcmp(cmd,"@@DFSD3 STATUS")==0){
        char line[109];int n=snprintf(line,sizeof(line),
            "@@DFSD3 STATE armed=%u writing=%u received=%u\n",
            (unsigned)is_live(),(unsigned)upload_in_progress,received);
        if(n>0&&n<(int)sizeof(line))emit(line);
        return;
    }
    if(strncmp(cmd,"@@DFSD3 OPEN ",13)==0){
        if(upload_in_progress||opened||h13_sd_usb_active()){reject("busy");return;}
        if(!is_live()){reject("physical_touch_required");return;}
        unsigned id=0,bytes=0,frames=0;char hex[65]={0},role[10]={0},extra=0;
        if(sscanf(cmd,"@@DFSD3 OPEN id=m%u bytes=%u sha256=%64[0-9a-f] role=%9[a-z] frames=%u%c",
                  &id,&bytes,hex,role,&frames,&extra)!=5 ||
           !user_id(id)||bytes<MIN_FILE||bytes>MAX_FILE||frames<1||frames>80 ||
           !role_ok(role)||!parse_hash(hex,expected_hash)){
            reject("invalid_user_slot_metadata");return;
        }
        const char *root=h13_sd_user_root();
        if(!root){reject("sd_exfat_unavailable");return;}
        if(!r136_pause_sd_for_usb()){reject("animation_not_quiescent");return;}
        char directory[45];snprintf(directory,sizeof(directory),"%s/DAFEIYU/USER",root);
        FRESULT mk=f_mkdir(directory);
        if(mk!=FR_OK&&mk!=FR_EXIST){r136_resume_animation();reject("folder_unavailable");return;}
        snprintf(temporary,sizeof(temporary),"%s/M%03u.TMP",directory,id);
        snprintf(final_path,sizeof(final_path),"%s/M%03u.DFS",directory,id);
        snprintf(class_path,sizeof(class_path),"%s/M%03u.CLS",directory,id);
        FILINFO meta;
        FRESULT old_file=f_stat(final_path,&meta);
        FRESULT old_class=f_stat(class_path,&meta);
        if(old_file!=FR_NO_FILE||old_class!=FR_NO_FILE){
            r136_resume_animation();reject("user_slot_occupied_or_sd_stat_error");return;
        }
        // No overwrite, including power-loss stale temp files.
        if(f_open(&file,temporary,FA_WRITE|FA_CREATE_NEW)!=FR_OK){
            r136_resume_animation();reject("temporary_file_exists_or_unavailable");return;
        }
        mbedtls_sha256_init(&sha_ctx);
        if(mbedtls_sha256_starts(&sha_ctx,0)!=0){
            opened=true;abort_file();reject("hash_init_failed");return;
        }
        slot=id;declared_frames=frames;length=bytes;received=0;next_seq=0;
        snprintf(assigned_role,sizeof(assigned_role),"%s",role);
        opened=true;upload_in_progress=true;
        last_data_tick=xTaskGetTickCount();
        // The animation worker already ACKed its safe boundary above; no
        // fixed 110ms guess after opening the SD file is considered a lock.
        char response[90];snprintf(response,sizeof(response),
             "@@DFSD3 OPENED id=m%03u chunk=1536\n",id);
        emit(response);return;
    }
    if(strncmp(cmd,"@@DFSD3 DATA ",13)==0){
        if(!opened||!upload_in_progress){reject("nothing_open");return;}
        unsigned seq=0;int prefix=0;
        if(sscanf(cmd,"@@DFSD3 DATA seq=%u b64=%n",&seq,&prefix)!=1||
           !prefix||seq!=next_seq){reject("seq_mismatch");return;}
        const char *encoded=cmd+prefix;
        size_t b64len=strlen(encoded),outlen=0;
        if(b64len==0||b64len>2048||b64len%4){reject("encoded_chunk_length");return;}
        static unsigned char raw[CHUNK]; // only one USB worker
        if(mbedtls_base64_decode(raw,sizeof(raw),&outlen,
               (const unsigned char *)encoded,b64len)!=0 ||
           !outlen||outlen>length-received){
            reject("decoded_chunk_invalid");return;
        }
        UINT wrote=0;
        if(f_write(&file,raw,(UINT)outlen,&wrote)!=FR_OK||wrote!=outlen ||
           mbedtls_sha256_update(&sha_ctx,raw,outlen)!=0){
            abort_file();reject("sd_write_failed");return;
        }
        received+=(unsigned)outlen;next_seq++;
        last_data_tick=xTaskGetTickCount();
        char response[72];snprintf(response,sizeof(response),
             "@@DFSD3 ACK seq=%u\n",seq);
        emit(response);return;
    }
    if(strcmp(cmd,"@@DFSD3 COMMIT")==0){
        if(!opened||received!=length){reject("incomplete_transaction");return;}
        unsigned char digest[32];
        if(mbedtls_sha256_finish(&sha_ctx,digest)!=0 ||
           memcmp(digest,expected_hash,32)!=0){
            abort_file();reject("stream_sha_mismatch");return;
        }
        if(f_sync(&file)!=FR_OK){abort_file();reject("fsync_failed");return;}
        (void)f_close(&file);opened=false;mbedtls_sha256_free(&sha_ctx);
        unsigned char readback[32];unsigned seen=0;
        if(!format_ok(temporary)||!sd_digest(temporary,readback,&seen)||
           seen!=length||memcmp(readback,expected_hash,32)!=0){
            abort_file();reject("readback_sha_or_dfsp_invalid");return;
        }
        // Keep action class on device alongside the DFSP file. Never
        // truncate a pre-existing class entry. Verified after f_sync.
        FIL cls;FRESULT clsres=f_open(&cls,class_path,FA_WRITE|FA_CREATE_NEW);
        if(clsres!=FR_OK){abort_file();reject("metadata_file_conflict");return;}
        char metadata[120];char hex[65];fmt_hash(readback,hex);
        int n=snprintf(metadata,sizeof(metadata),"%s %u %u %s\n",
                 assigned_role,declared_frames,length,hex);
        UINT wrote=0;
        bool ok=n>0&&n<(int)sizeof(metadata)&&
                 f_write(&cls,metadata,(UINT)n,&wrote)==FR_OK&&wrote==(UINT)n&&
                 f_sync(&cls)==FR_OK;
        if(f_close(&cls)!=FR_OK)ok=false;
        if(!ok){(void)f_unlink(class_path);abort_file();reject("metadata_persist_failed");return;}
        // Transaction promotion; original35 directory is never opened.
        if(f_rename(temporary,final_path)!=FR_OK){
            (void)f_unlink(class_path);abort_file();reject("promote_failed");return;
        }
        char result[122];snprintf(result,sizeof(result),
             "@@DFSD3 STAGED id=m%03u sha256=%s\n",slot,hex);
        last_committed_slot=slot;
        readback_until=xTaskGetTickCount()+pdMS_TO_TICKS(30000u);
        temporary[0]=0;opened=false;upload_in_progress=false;local_authorized=false;
        r136_resume_animation();
        emit(result);return;
    }
    if(strncmp(cmd,"@@DFSD3 VERIFY id=m",20)==0){
        unsigned id=0;char tail=0;
        if(sscanf(cmd,"@@DFSD3 VERIFY id=m%u%c",&id,&tail)!=1||!user_id(id)){
            reject("invalid_verify_slot");return;
        }
        // Can reverify only after explicit physical approval; don't allow
        // unsolicited SD enumeration or interaction while Mac is away.
        bool this_commit=(id==last_committed_slot) &&
           ((int32_t)(xTaskGetTickCount()-readback_until)<0);
        if(!is_live() && !this_commit){reject("local_approval_required");return;}
        const char *root=h13_sd_user_root();
        if(!root){reject("sd_unavailable");return;}
        char path[74];snprintf(path,sizeof(path),
             "%s/DAFEIYU/USER/M%03u.DFS",root,id);
        unsigned char digest[32];unsigned actual=0;
        if(!sd_digest(path,digest,&actual)){reject("sd_file_readback_failed");return;}
        char hex[65];fmt_hash(digest,hex);
        // Device must *also* read the action-class sidecar from physical SD.
        char classfile[74];
        snprintf(classfile,sizeof(classfile),"%s/DAFEIYU/USER/M%03u.CLS",root,id);
        FIL metadata;
        if(f_open(&metadata,classfile,FA_READ)!=FR_OK){
            reject("missing_action_class_metadata");return;
        }
        char textbuf[130]={0}; UINT read=0;
        FSIZE_t sz=f_size(&metadata);
        bool got=sz>0 && sz<sizeof(textbuf) &&
                 f_read(&metadata,textbuf,(UINT)sz,&read)==FR_OK &&
                 read==(UINT)sz;
        if(f_close(&metadata)!=FR_OK)got=false;
        char cls[10]={0},saved_hash[65]={0},extra=0;
        unsigned frames=0,saved_size=0;
        if(!got || sscanf(textbuf,"%9[a-z] %u %u %64[0-9a-f]%c",
               cls,&frames,&saved_size,saved_hash,&extra)!=4 ||
           !role_ok(cls)||frames==0||frames>80||
           saved_size!=actual||strcmp(saved_hash,hex)!=0){
            reject("stored_action_class_mismatch");return;
        }
        char msg[160];snprintf(msg,sizeof(msg),
             "@@DFSD3 VERIFIED id=m%03u bytes=%u sha256=%s role=%s\n",
             id,actual,hex,cls);
        emit(msg);return;
    }
    reject("unsupported_command");
}

// Probes/verification also read the same physical SD. The wrapper guarantees
// a single release even when one of the many validation branches rejects.
void r83_usb_command(const char *cmd){
    bool inspect=cmd && (strncmp(cmd,"@@DFSD3 INSPECT ",16)==0 ||
                          strncmp(cmd,"@@DFSD3 VERIFY ",15)==0);
    if(inspect && !r136_pause_sd_for_usb()){
        reject("animation_not_quiescent");return;
    }
    r83_usb_command_inner(cmd);
    if(inspect)r136_resume_animation();
}
void r83_usb_housekeeping(bool audio_busy){
    if(upload_in_progress && audio_busy){
        ESP_LOGW(TAG,"R136_SD_UPLOAD_AUDIO_PRIORITY_ABORT");
        abort_file();
        emit("@@DFSD3 NACK reason=audio_priority\n");
        return;
    }
    if(upload_in_progress &&
       (int32_t)(xTaskGetTickCount()-last_data_tick)>=pdMS_TO_TICKS(45000)){
        ESP_LOGW(TAG,"R136_SD_UPLOAD_TIMEOUT_ABORT received=%u",received);
        abort_file(); // only unlinks this active transaction's temporary file
        emit("@@DFSD3 NACK reason=transfer_idle_timeout\n");
    }
}
