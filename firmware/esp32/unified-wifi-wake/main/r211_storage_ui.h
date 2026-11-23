#pragma once
// R211 storage overview. SD: actual exFAT allocation bitmap via f_getfree in
// a low-priority one-shot worker; never sum the hardcoded animation manifest.
// Flash: explicitly *partitioned* capacity, not a fabricated usage estimate.
#include "esp_flash.h"
static lv_obj_t *r211_sd_text=NULL,*r211_sd_meta=NULL,*r211_sd_bar=NULL;
static lv_obj_t *r211_flash_text=NULL;
static volatile uint32_t r211_sd_total_mib=0,r211_sd_used_mib=0;
static volatile unsigned r211_stats_phase=0; // 0 new, 1 reading, 2 real, 3 unavailable
static unsigned r211_rendered_phase=255;
static void r211_stats_worker(void *unused){
    (void)unused;
    uint64_t total=0,used=0;
    // Never contend with a host-requested upload. f_getfree uses the existing
    // exFAT filesystem and never formats or writes the card.
    int rc=h13_sd_usb_active()?-5:h13_sd_usage_bytes(&total,&used);
    if(rc==0&&total>=used&&total>=1048576){
        r211_sd_total_mib=(uint32_t)(total/1048576ULL);
        r211_sd_used_mib=(uint32_t)((used+524288ULL)/1048576ULL);
        r211_stats_phase=2;
    }else r211_stats_phase=3;
    vTaskDelete(NULL);
}
static void r211_stats_start(void){
    if(r211_stats_phase==1)return;
    r211_stats_phase=1;
    if(xTaskCreate(r211_stats_worker,"r211_sd_stat",6144,NULL,1,NULL)!=pdPASS)
        r211_stats_phase=3;
}
static void r211_storage_refresh(void){
    if(r57_page!=9||!r57_root||!r211_sd_text||!r211_sd_bar)return;
    unsigned phase=r211_stats_phase;
    if(phase==r211_rendered_phase)return;
    r211_rendered_phase=phase;
    char label[120];
    char meta[120];
    if(phase==1){
        snprintf(label,sizeof(label),"读取中");
        snprintf(meta,sizeof(meta),"正在统计文件实际占用");
        lv_bar_set_value(r211_sd_bar,0,LV_ANIM_OFF);
    }else if(phase==2&&r211_sd_total_mib){
        uint32_t used=r211_sd_used_mib,total=r211_sd_total_mib;
        if(used>total)used=total;
        unsigned permille=(unsigned)((uint64_t)used*1000/total);
        lv_bar_set_value(r211_sd_bar,used && !permille?1:
                         permille?(permille+9)/10:0,LV_ANIM_OFF);
        snprintf(label,sizeof(label),"%lu MiB",(unsigned long)used);
        snprintf(meta,sizeof(meta),"总量 %lu MiB  ·  已用 %u.%u%%",
            (unsigned long)total,permille/10,permille%10);
    }else{
        snprintf(label,sizeof(label),"无法读取");
        snprintf(meta,sizeof(meta),"请检查 SD 卡后重试");
        lv_bar_set_value(r211_sd_bar,0,LV_ANIM_OFF);
    }
    lv_label_set_text(r211_sd_text,label);
    if(r211_sd_meta)lv_label_set_text(r211_sd_meta,meta);
}
static void r211_refresh_clicked(lv_event_t *ev){
    (void)ev;
    if(r211_stats_phase==1)return;
    r211_rendered_phase=255;
    r211_stats_start();
    r211_storage_refresh();
}
static void r211_storage_page(void){
    lv_obj_set_style_bg_color(r57_root,lv_color_hex(0xF4F7F9),0);
    lv_obj_t *back=r481_action(r57_root,"返回",26,30,98,49,12,false);
    r487_rounded_action(back,false);
    r481_ink(r57_root,"存储空间",166,37,211,true,0x243F51);
    lv_obj_t *refresh=r57_button(r57_root,"刷新",361,30,93,49,
                                 r211_refresh_clicked,0,0xE9F2F6);
    lv_obj_set_style_radius(refresh,19,0);
    lv_obj_t *rlabel=lv_obj_get_child(refresh,0);
    if(rlabel)lv_obj_set_style_text_font(rlabel,&lv_font_r487_cn_18,0);

    r481_plate(r57_root,26,111,428,173,0xFFFFFF,23);
    r481_ink(r57_root,"MicroSD",51,134,226,false,0x2C4C61);
    r481_plate(r57_root,346,131,82,32,0xE8F2F7,16);
    r487_caption(r57_root,"exFAT",356,138,71,0x52849F);
    r211_sd_text=r481_ink(r57_root,"读取中",52,175,363,true,0x2A4E65);
    r211_sd_meta=r487_caption(r57_root,"正在统计文件实际占用",
                              53,218,364,0x7793A3);
    r211_sd_bar=lv_bar_create(r57_root);
    lv_obj_set_size(r211_sd_bar,373,10);
    lv_obj_align(r211_sd_bar,LV_ALIGN_TOP_LEFT,52,246);
    lv_bar_set_range(r211_sd_bar,0,100);
    lv_bar_set_value(r211_sd_bar,0,LV_ANIM_OFF);
    lv_obj_set_style_bg_color(r211_sd_bar,lv_color_hex(0xE8F0F4),LV_PART_MAIN);
    lv_obj_set_style_bg_color(r211_sd_bar,lv_color_hex(0x6F9EBA),LV_PART_INDICATOR);
    lv_obj_set_style_radius(r211_sd_bar,5,LV_PART_MAIN);
    lv_obj_set_style_radius(r211_sd_bar,5,LV_PART_INDICATOR);

    r481_plate(r57_root,26,302,428,151,0xFFFFFF,23);
    r481_ink(r57_root,"内部 Flash",51,322,253,false,0x2C4C61);
    uint32_t bytes=0;
    esp_err_t e=esp_flash_get_size(esp_flash_default_chip,&bytes);
    char line[105];
    if(e==ESP_OK&&bytes)
        snprintf(line,sizeof(line),"%lu MiB",(unsigned long)(bytes/1048576U));
    else snprintf(line,sizeof(line),"不可读取");
    r481_ink(r57_root,line,323,321,101,false,0x467B99);
    r487_rule(r57_root,51,368,376);
    const esp_partition_t *app=esp_partition_find_first(
        ESP_PARTITION_TYPE_APP,ESP_PARTITION_SUBTYPE_ANY,NULL);
    const esp_partition_t *model=esp_partition_find_first(
        ESP_PARTITION_TYPE_DATA,ESP_PARTITION_SUBTYPE_ANY,"model");
    const esp_partition_t *store=esp_partition_find_first(
        ESP_PARTITION_TYPE_DATA,ESP_PARTITION_SUBTYPE_ANY,"storage");
    if(app&&model)
        snprintf(line,sizeof(line),"程序 %.1f MiB  ·  模型 %.1f MiB",
                 app->size/1048576.0,model->size/1048576.0);
    else snprintf(line,sizeof(line),"程序与模型：暂无数据");
    r487_caption(r57_root,line,52,384,369,0x678597);
    if(store)
        snprintf(line,sizeof(line),"数据分区 %.1f MiB",store->size/1048576.0);
    else snprintf(line,sizeof(line),"数据分区：暂无数据");
    r487_caption(r57_root,line,52,416,368,0x678597);
    r211_rendered_phase=255;
    if(r211_stats_phase!=1)r211_stats_start();
    r211_storage_refresh();
}
