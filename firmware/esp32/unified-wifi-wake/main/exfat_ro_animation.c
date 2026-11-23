// SPDX-License-Identifier: MIT
// exFAT-only minimum *read-only* file interface for selected MNNN.DFS.
// Restricts filenames to fixed in-project motion paths and validates geometry.
// Card block ownership / SDMMC card init are entirely the caller's job.
#include "exfat_ro_animation.h"
#include <string.h>
#include <stdio.h>
#include <limits.h>
#define DFR_MAX_CLUSTER_SECTORS 1024U
#define DFR_MAX_ANIM_BYTES (12U*1024U*1024U)
#define DFR_DIR_SCAN_LIMIT 8192U
static uint16_t u16(const uint8_t*p){return (uint16_t)p[0]|(uint16_t)(p[1]<<8);}
static uint32_t u32(const uint8_t*p){return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);}
static uint64_t u64(const uint8_t*p){return (uint64_t)u32(p)|((uint64_t)u32(p+4)<<32);}
static int sector(df_ro_exfat*v,uint32_t lba,uint8_t data[512]) {
  if(lba < v->start_lba || (uint64_t)lba >= (uint64_t)v->start_lba+v->volume_sectors)return -1;
  return v->read(v->context,lba,data);
}
static int cluster_lba(df_ro_exfat*v,uint32_t c,uint32_t*s){
  if(c<2||c>=v->cluster_count+2)return -1;
  uint64_t pos=(uint64_t)v->heap_lba+(uint64_t)(c-2)*v->sectors_per_cluster;
  if(pos>UINT32_MAX||pos+v->sectors_per_cluster>(uint64_t)v->start_lba+v->volume_sectors)return -1;
  *s=(uint32_t)pos;return 0;
}
static int next_cluster(df_ro_exfat*v,uint32_t c,uint32_t*next){
  uint8_t sec[512];
  uint64_t off=(uint64_t)c*4;
  uint64_t lba=(uint64_t)v->fat_lba+off/512;
  if(lba>UINT32_MAX||sector(v,(uint32_t)lba,sec))return -1;
  *next=u32(sec+(off%512));
  return (*next>=2&&*next<v->cluster_count+2)?0:-1;
}
int df_ro_exfat_mount(df_ro_exfat *out,df_ro_sector_reader read,void *ctx,
                      uint32_t volume_lba,uint32_t sector_count){
  uint8_t boot[512];
  if(!out||!read||!sector_count||volume_lba>=sector_count)return -1;
  memset(out,0,sizeof(*out));
  // During detection read the VBR once; every following read is strictly bounded.
  if(read(ctx,volume_lba,boot)!=0||memcmp(boot+3,"EXFAT   ",8)!=0||
     boot[510]!=0x55||boot[511]!=0xAA||boot[108]!=9||boot[109]>10||
     boot[110]!=1)return -1;
  uint64_t length=u64(boot+72);
  uint32_t fat=u32(boot+80),fatlen=u32(boot+84),heap=u32(boot+88),clusters=u32(boot+92),root=u32(boot+96);
  uint32_t spc=1U<<boot[109];
  if(length==0||length>sector_count-volume_lba||clusters==0||
     clusters>0xFFFFFFFDu||fat==0||fatlen==0||fat>=length||
     (uint64_t)fat+fatlen>length||heap<=fat||(uint64_t)heap+clusters*(uint64_t)spc>length||
     root<2||root>=clusters+2)return -1;
  out->read=read;out->context=ctx;out->start_lba=volume_lba;
  out->volume_sectors=(uint32_t)length;out->fat_lba=volume_lba+fat;
  out->heap_lba=volume_lba+heap;out->cluster_count=clusters;
  out->root_cluster=root;out->sectors_per_cluster=spc;
  return 0;
}
static int location(df_ro_exfat*v,const df_ro_file*f,uint64_t off,uint32_t*lba,uint32_t*in_sector){
  const uint64_t per=(uint64_t)v->sectors_per_cluster*512;
  const uint64_t idx=off/per;
  if(idx>=v->cluster_count||idx>DFR_DIR_SCAN_LIMIT)return -1;
  uint32_t cluster=f->first_cluster;
  if(f->no_fat_chain){
    if(idx>UINT32_MAX-(uint64_t)cluster)return -1;
    cluster+=(uint32_t)idx;
  }else{
    for(uint64_t n=0;n<idx;n++){
      uint32_t following;
      if(next_cluster(v,cluster,&following)!=0)return -1;
      cluster=following;
    }
  }
  uint32_t cbase;
  if(cluster_lba(v,cluster,&cbase))return -1;
  uint64_t sec_idx=(off%per)/512;
  *lba=cbase+(uint32_t)sec_idx;*in_sector=(uint32_t)(off%512);
  return 0;
}
size_t df_ro_exfat_read(df_ro_exfat*v,const df_ro_file*f,uint64_t offset,uint8_t*dst,size_t count){
  if(!v||!f||!dst||!v->read||offset>=f->length)return 0;
  if(count>f->length-offset)count=(size_t)(f->length-offset);
  size_t read_count=0;
  while(read_count<count){
    uint32_t lba,inside;uint8_t sec[512];
    if(location(v,f,offset+read_count,&lba,&inside)||sector(v,lba,sec))break;
    size_t take=512-inside;
    if(take>count-read_count)take=count-read_count;
    memcpy(dst+read_count,sec+inside,take);
    read_count+=take;
  }
  return read_count;
}
static int get_entry(df_ro_exfat*v,const df_ro_file*dir,uint64_t entry_index,uint8_t out[32]){
  return df_ro_exfat_read(v,dir,entry_index*32,out,32)==32?0:-1;
}
static int find_entry(df_ro_exfat*v,const df_ro_file*parent,const char*name,df_ro_file*out){
  uint8_t primary[32],stream[32],fn[32];
  const size_t n=strlen(name);
  if(n==0||n>15)return -1; // all required DAFEIYU/MOTIONS/MNNN.DFS fit
  for(uint64_t pos=0;pos<DFR_DIR_SCAN_LIMIT;pos++){
    if(get_entry(v,parent,pos,primary))return -1;
    if(primary[0]==0x00)return -1;
    if(primary[0]!=0x85)continue;
    const uint8_t secondaries=primary[1];
    if(secondaries<2||secondaries>18||pos+secondaries>=DFR_DIR_SCAN_LIMIT)return -1;
    if(get_entry(v,parent,pos+1,stream)||get_entry(v,parent,pos+2,fn))return -1;
    if(stream[0]!=0xC0||fn[0]!=0xC1)return -1;
    if(stream[3]!=n){pos+=secondaries;continue;}
    int good=1;
    for(unsigned j=0;j<n;j++){
      uint16_t point=u16(fn+2+2*j);
      // Bounded ASCII-only filenames; never take paths supplied by the host.
      if(point!=(uint8_t)name[j]){good=0;break;}
    }
    if(good){
      uint64_t length=u64(stream+24);uint32_t start=u32(stream+20);
      int dir=(u16(primary+4)&0x10)!=0;
      if(start<2||start>=v->cluster_count+2||length==0||
         length>(dir?16U*1024U*1024U:DFR_MAX_ANIM_BYTES))return -1;
      *out=(df_ro_file){start,length,(stream[1]&0x02)!=0,(uint8_t)dir};
      return 0;
    }
    pos+=secondaries;
  }
  return -1;
}
int df_ro_exfat_locate_motion(df_ro_exfat*v,unsigned motion_id,df_ro_file*out){
  if(!v||!out||motion_id>999||!v->read)return -1;
  df_ro_file root={v->root_cluster,(uint64_t)DFR_DIR_SCAN_LIMIT*32,0,1};
  df_ro_file dir,files;
  if(find_entry(v,&root,"DAFEIYU",&dir)||!dir.is_directory)return -1;
  if(find_entry(v,&dir,"MOTIONS",&files)||!files.is_directory)return -1;
  char filename[16];
  snprintf(filename,sizeof(filename),"M%03u.DFS",motion_id);
  if(find_entry(v,&files,filename,out)||out->is_directory)return -1;
  return 0;
}
