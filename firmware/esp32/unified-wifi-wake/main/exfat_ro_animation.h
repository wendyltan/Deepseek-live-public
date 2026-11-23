// Strict, read-only exFAT sprite locator. No FATFS mount, writes or formatting.
#ifndef DAFEIYU_EXFAT_RO_ANIMATION_H
#define DAFEIYU_EXFAT_RO_ANIMATION_H
#include <stdint.h>
#include <stddef.h>

typedef int (*df_ro_sector_reader)(void *context,uint32_t lba,uint8_t buffer[512]);
typedef struct {
  df_ro_sector_reader read;void *context;
  uint32_t start_lba,volume_sectors,fat_lba,heap_lba,cluster_count,root_cluster;
  uint32_t sectors_per_cluster;
} df_ro_exfat;
typedef struct {
  uint32_t first_cluster;
  uint64_t length;
  uint8_t no_fat_chain,is_directory;
} df_ro_file;
// All functions return 0 on success; no card writes exist in this API.
int df_ro_exfat_mount(df_ro_exfat *out,df_ro_sector_reader read,void *ctx,
                      uint32_t volume_lba,uint32_t sector_count);
int df_ro_exfat_locate_motion(df_ro_exfat *vol,unsigned motion_id,df_ro_file *out);
size_t df_ro_exfat_read(df_ro_exfat *vol,const df_ro_file *file,
                        uint64_t offset,uint8_t *dst,size_t count);
#endif
