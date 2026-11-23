// SPDX-License-Identifier: MIT
// R57 display-only subpages + bounded hardware-local callbacks.
// Included once by main.c with DF_R33_BOARD_UI; no browser, no Wi-Fi, no Mac mic.
#pragma once
#include "esp_random.h"
#include "esp_app_desc.h"
LV_FONT_DECLARE(lv_font_r57_cn_16);
LV_FONT_DECLARE(lv_font_r57_cn_20);
LV_FONT_DECLARE(lv_font_r487_cn_18);
LV_FONT_DECLARE(lv_font_r487_cn_23);
LV_FONT_DECLARE(lv_font_r487_cn_30);


static lv_obj_t *r57_root=NULL,*r57_counter=NULL,*r57_timer_note=NULL;
// R479 control-center labels are real on-device observations, not historical
// DSH/TTS successes. Recreate on each page entry; clear before async deletion.
static lv_obj_t *r479_quick_usb=NULL,*r479_quick_wifi=NULL;
static lv_obj_t *r479_quick_phase=NULL,*r479_detail_status=NULL;
static lv_obj_t *r487_state_usb=NULL,*r487_state_wifi=NULL;
static lv_obj_t *r487_state_gateway=NULL,*r487_state_voice=NULL;
static lv_obj_t *r487_state_last=NULL;
static int r481_last_link_inks=-1;
static lv_obj_t *r223_wifi_icon=NULL,*r277_wifi_badge=NULL;
static lv_obj_t *r57_recent_labels[4]={0};
static volatile unsigned r57_local_motion_request=0;  // id+1, never changes host sequence
static char r57_recent[4][769]={{0}};
static unsigned r62_chat2_next[4]={0};
static volatile uint32_t r57_recent_revision=0;
static uint32_t r57_seen_revision=0;
static unsigned r57_page=0;
static uint32_t r57_timer_duration=60, r57_timer_remaining=60;
static TickType_t r57_timer_started=0;
static bool r57_timer_running=false, r57_timer_finished=false;
static lv_obj_t *r57_main_stop=NULL,*r59_mic_caption=NULL;
static const unsigned r57_motion_ids[]={0,1,2,3,8,10,11,13,14,15,16,18,19,20,
    23,24,25,26,27,28,30,61,62,67,70,71,72,73,75,80,81,83,97,99,105};

static void r57_open_page(unsigned page);
static lv_obj_t *r57_text(lv_obj_t *parent,const char *txt,int x,int y,int w,
                          bool large){
    lv_obj_t *o=lv_label_create(parent);
    lv_label_set_text(o,txt);
    lv_obj_set_style_text_font(o,large?&lv_font_r57_cn_20:&lv_font_r57_cn_16,0);
    lv_obj_set_style_text_color(o,lv_color_hex(0x293A53),0);
    lv_obj_set_width(o,w);
    lv_obj_align(o,LV_ALIGN_TOP_LEFT,x,y);
    lv_label_set_long_mode(o,LV_LABEL_LONG_DOT);
    return o;
}
static lv_obj_t *r57_button(lv_obj_t *parent,const char *txt,int x,int y,
                 int w,int h,lv_event_cb_t fn,uintptr_t data,uint32_t tint){
    lv_obj_t *o=lv_button_create(parent);
    lv_obj_set_size(o,w,h);
    lv_obj_align(o,LV_ALIGN_TOP_LEFT,x,y);
    lv_obj_set_style_radius(o,16,0);
    lv_obj_set_style_bg_color(o,lv_color_hex(tint),0);
    lv_obj_set_style_shadow_width(o,0,0);
    lv_obj_set_style_border_width(o,1,0);
    lv_obj_set_style_border_color(o,lv_color_hex(0xE3EAF2),0);
    if(fn)lv_obj_add_event_cb(o,fn,LV_EVENT_CLICKED,(void*)data);
    lv_obj_t *t=lv_label_create(o);
    lv_label_set_text(t,txt);
    lv_obj_set_style_text_font(t,&lv_font_r57_cn_16,0);
    lv_obj_set_style_text_color(t,lv_color_hex(0x235078),0);
    lv_obj_center(t);
    return o;
}
static void r57_nav(lv_event_t *ev);
// R482 premium control center: 480x480 SQUARE AMOLED. Solid LVGL widgets,
// no alpha blur, shadows, or extra frame buffers on the QSPI display.
static lv_obj_t *r481_plate(lv_obj_t *p,int x,int y,int w,int h,
                           uint32_t fill,int rad){
    lv_obj_t *o=lv_obj_create(p);
    lv_obj_set_size(o,w,h);
    lv_obj_align(o,LV_ALIGN_TOP_LEFT,x,y);
    lv_obj_set_style_radius(o,rad,0);
    lv_obj_set_style_bg_opa(o,LV_OPA_COVER,0);
    lv_obj_set_style_bg_color(o,lv_color_hex(fill),0);
    lv_obj_set_style_border_color(o,lv_color_hex(0xDEE7ED),0);
    lv_obj_set_style_border_width(o,1,0);
    lv_obj_set_style_shadow_width(o,0,0);
    lv_obj_set_style_pad_all(o,0,0);
    lv_obj_remove_flag(o,LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_remove_flag(o,LV_OBJ_FLAG_CLICKABLE);
    return o;
}
static lv_obj_t *r481_ink(lv_obj_t *p,const char *t,int x,int y,int w,
                         bool big,uint32_t color){
    // The bundled 20px CJK subset lacks some title glyphs (e.g. "备",
    // "息"). Select complete 16px text instead of drawing tofu boxes.
    // This checks the real LVGL font at runtime, including firmware versions.
    if(big && t){
        uint32_t offset=0;
        while(t[offset]){
            const unsigned char *bytes=(const unsigned char *)t+offset;
            uint32_t cp=bytes[0];
            unsigned span=cp<0x80?1:(cp>=0xC2&&cp<=0xDF)?2:
                          (cp>=0xE0&&cp<=0xEF)?3:
                          (cp>=0xF0&&cp<=0xF4)?4:0;
            if(!span){big=false;break;}
            cp=span==1?cp:(cp & (0x7F>>span));
            for(unsigned i=1;i<span;i++){
                if(!bytes[i] || (bytes[i]&0xC0)!=0x80){
                    big=false;break;
                }
                cp=(cp<<6)|(bytes[i]&0x3F);
            }
            if(!big)break;
            offset+=span;
            lv_font_glyph_dsc_t glyph={0};
            if(!lv_font_get_glyph_dsc(&lv_font_r487_cn_30,&glyph,cp,0) ||
                glyph.is_placeholder){big=false;break;}
        }
    }
    lv_obj_t *o=r57_text(p,t,x,y,w,false);
    lv_obj_set_style_text_font(o,big?&lv_font_r487_cn_30:&lv_font_r487_cn_23,0);
    lv_obj_set_style_text_color(o,lv_color_hex(color),0);
    return o;
}
static lv_obj_t *r481_action(lv_obj_t *p,const char *t,int x,int y,int w,int h,
                             unsigned dest,bool primary){
    lv_obj_t *o=r57_button(p,t,x,y,w,h,r57_nav,dest,
                         primary?0xDCECF5:0xFFFFFF);
    lv_obj_set_style_radius(o,18,0);
    lv_obj_set_style_border_color(o,lv_color_hex(primary?0xCEE0EC:0xDCE5EB),0);
    lv_obj_set_style_bg_color(o,lv_color_hex(0xC5DFEE),LV_STATE_PRESSED);
    lv_obj_set_style_shadow_width(o,0,0);
    lv_obj_t *l=lv_obj_get_child(o,0);
    if(l){
        lv_obj_set_style_text_color(l,lv_color_hex(0x23435C),0);
        lv_obj_set_style_text_font(l,&lv_font_r487_cn_23,0);
    }
    return o;
}
// R487 refined typography: title / main / detail are distinct roles.
static lv_obj_t *r487_caption(lv_obj_t *p,const char *t,int x,int y,
                              int w,uint32_t color){
    lv_obj_t *l=r57_text(p,t,x,y,w,false);
    lv_obj_set_style_text_font(l,&lv_font_r487_cn_18,0);
    lv_obj_set_style_text_color(l,lv_color_hex(color),0);
    return l;
}
static lv_obj_t *r487_rule(lv_obj_t *p,int x,int y,int w){
    lv_obj_t *o=r481_plate(p,x,y,w,1,0xE9EFF3,0);
    lv_obj_set_style_border_width(o,0,0);
    return o;
}
static lv_obj_t *r487_icon(lv_obj_t *p,const char *ch,int x,int y){
    lv_obj_t *o=r481_plate(p,x,y,38,38,0xE8F2F8,16);
    lv_obj_set_style_border_width(o,0,0);
    lv_obj_t *label=r481_ink(o,ch,0,5,38,false,0x4E829E);
    lv_obj_set_style_text_align(label,LV_TEXT_ALIGN_CENTER,0);
    return o;
}
static void r487_rounded_action(lv_obj_t *o,bool primary){
    lv_obj_set_style_radius(o,20,0);
    lv_obj_set_style_border_width(o,primary?0:1,0);
    lv_obj_set_style_bg_color(o,lv_color_hex(primary?0xDCEEF6:0xFFFFFF),0);
    lv_obj_set_style_border_color(o,lv_color_hex(0xE5EEF3),0);
}
static void r481_slider_skin(lv_obj_t *s){
    lv_obj_set_style_bg_color(s,lv_color_hex(0xE4EAF0),LV_PART_MAIN);
    lv_obj_set_style_bg_opa(s,LV_OPA_COVER,LV_PART_MAIN);
    lv_obj_set_style_border_width(s,0,LV_PART_MAIN);
    lv_obj_set_style_radius(s,LV_RADIUS_CIRCLE,LV_PART_MAIN);
    lv_obj_set_style_bg_color(s,lv_color_hex(0x6595B3),LV_PART_INDICATOR);
    lv_obj_set_style_bg_opa(s,LV_OPA_COVER,LV_PART_INDICATOR);
    lv_obj_set_style_radius(s,LV_RADIUS_CIRCLE,LV_PART_INDICATOR);
    lv_obj_set_style_bg_color(s,lv_color_hex(0xFFFFFF),LV_PART_KNOB);
    lv_obj_set_style_bg_opa(s,LV_OPA_COVER,LV_PART_KNOB);
    lv_obj_set_style_border_width(s,3,LV_PART_KNOB);
    lv_obj_set_style_border_color(s,lv_color_hex(0x6595B3),LV_PART_KNOB);
    lv_obj_set_style_shadow_width(s,0,LV_PART_KNOB);
    lv_obj_set_ext_click_area(s,15);
    lv_obj_remove_flag(s,LV_OBJ_FLAG_GESTURE_BUBBLE);
}
// R210: existing Wi-Fi-only page primitives are now reachable from the menu.
#include "r62_wifi_ui.h"

static void r57_close_page(void){
    if(r57_page==10){
        if(r62_wifi_field)lv_textarea_set_text(r62_wifi_field,"");
        r62_wifi_modal=NULL;r62_wifi_field=NULL;r62_wifi_keyboard=NULL;
        r211_forget_dialog=NULL;
        r62_wifi_status=NULL;
        memset(r62_wifi_selected_ssid,0,sizeof(r62_wifi_selected_ssid));
        memset(r62_wifi_rows,0,sizeof(r62_wifi_rows));
    }
    r57_page=0;
    if(r57_root){lv_obj_delete_async(r57_root);r57_root=NULL;}
    r57_counter=NULL;r57_timer_note=NULL;
    r479_quick_usb=NULL;r479_quick_wifi=NULL;
    r479_quick_phase=NULL;r479_detail_status=NULL;
    r487_state_usb=NULL;r487_state_wifi=NULL;r487_state_gateway=NULL;
    r487_state_voice=NULL;r487_state_last=NULL;
    r481_last_link_inks=-1;
    memset(r57_recent_labels,0,sizeof(r57_recent_labels));
    r36_brightness_slider=NULL;r36_volume_slider=NULL;
    r36_brightness_pct=NULL;r36_volume_pct=NULL;

}
static void r57_nav(lv_event_t *ev){
    uintptr_t dest=(uintptr_t)lv_event_get_user_data(ev);
    if(dest==0)r57_close_page();
    else r57_open_page((unsigned)dest);
}
#include "r211_storage_ui.h"
static void r57_gesture(lv_event_t *ev){
    (void)ev;
    lv_indev_t *indev=lv_indev_active();
    if(!indev)return;
    lv_dir_t dir=lv_indev_get_gesture_dir(indev);
    // Only the control center is dismissible by up-swipe. A Wi-Fi password
    // keyboard or a nested detail page must never be destroyed by a swipe.
    if(dir==LV_DIR_TOP && r57_page==1){
        r57_close_page();
        lv_indev_wait_release(indev);
    }else if(dir==LV_DIR_BOTTOM && r57_page==0){
        r57_open_page(1);
        lv_indev_wait_release(indev);
    }
}
static void r57_random_motion(unsigned id){
    if(capturing||speaking||h10_receiving||h28_mic_press_session ||
       h12_req_seq!=h12_done_seq || !h12_sd_available()){
        lv_label_set_text(status_label,"动作库忙碌，请稍后");
        return;
    }
    if(!h12_selected_id(id))return;
    r57_local_motion_request=id+1;  // picked up by animation_worker only
    h28_touch_requested=true;
    h30_touch_requested_at=xTaskGetTickCount();
    lv_label_set_text(status_label,"正在播放本地动作");
}
static void r57_random_cb(lv_event_t *ev){
    (void)ev;
    unsigned count=sizeof(r57_motion_ids)/sizeof(r57_motion_ids[0]);
    unsigned id=r57_motion_ids[esp_random()%count];
    r57_random_motion(id);
    r57_close_page();
}
static void r57_timer_adjust(lv_event_t *ev){
    uintptr_t idx=(uintptr_t)lv_event_get_user_data(ev);
    if(idx>=6 || r57_timer_running)return;
    static const uint32_t step[]={3600,3600,60,60,1,1};
    uint32_t amount=step[idx];
    if(idx%2==0) {
        if(r57_timer_duration<=86400-amount)r57_timer_duration+=amount;
        else r57_timer_duration=86400;
    }else{
        if(r57_timer_duration>amount)r57_timer_duration-=amount;
        else r57_timer_duration=1;
    }
    r57_timer_remaining=r57_timer_duration;r57_timer_finished=false;
}
static void r57_timer_toggle(lv_event_t *ev){
    (void)ev;
    TickType_t now=xTaskGetTickCount();
    if(r57_timer_running){
        unsigned elapsed=(unsigned)((uint32_t)(now-r57_timer_started)/configTICK_RATE_HZ);
        r57_timer_remaining=elapsed>=r57_timer_remaining?1:r57_timer_remaining-elapsed;
        r57_timer_running=false;
    }else{
        if(r57_timer_finished || r57_timer_remaining==0)
            r57_timer_remaining=r57_timer_duration;
        r57_timer_started=now;r57_timer_finished=false;
        r57_timer_running=true;
    }
}
static void r57_timer_reset(lv_event_t *ev){
    (void)ev;r57_timer_running=false;r57_timer_finished=false;
    r57_timer_remaining=r57_timer_duration;
}
#if defined(DF_R225_LOCAL_OFFLINE) && defined(DF_R185_WN9)
static void r257_local_voice_click(lv_event_t *event){
    unsigned clip=(unsigned)(uintptr_t)lv_event_get_user_data(event);
    if(!r257_local_voice_from_touch(clip)){
        lv_label_set_text(status_label,"语音忙碌或指令不可用");return;
    }
    r57_close_page();
    lv_label_set_text(status_label,"正在播放SD本地语音");
}
#endif
static bool r479_controls_busy(void){
    return capturing || speaking || h10_receiving;
}
static void r57_volume_update(lv_event_t *ev){
    // LVGL moves a slider before emitting VALUE_CHANGED. Revert its visual
    // value on a busy voice turn, rather than silently showing a false change.
    if(r479_controls_busy()){
        if(r36_volume_slider)lv_slider_set_value(r36_volume_slider,volume,LV_ANIM_OFF);
        return;
    }
    r36_volume_changed(ev);
}
static void r57_brightness_update(lv_event_t *ev){
    if(r479_controls_busy()){
        if(r36_brightness_slider)
            lv_slider_set_value(r36_brightness_slider,r33_brightness,LV_ANIM_OFF);
        return;
    }
    r36_brightness_changed(ev);
}
// A real IP/USB observation does not mean an authenticated Gateway Session.
static void r479_refresh_connections(void){
    if(r57_page!=1 && r57_page!=2)return;
    r62_wifi_state_t net={0};
    r62_wifi_snapshot(&net);
    bool usb=usb_serial_jtag_is_connected();
    bool fresh=usb && r268_usb_host_alive();
    const char *us= fresh?"USB：Mac已连接":
        usb?"USB：待确认":"USB：未连接";
    // Prewake and an authenticated full-duplex DSH turn are distinct WSS
    // phases. Never show "not connected" during a valid conversation.
    bool gateway=r486_lan_prewake_authenticated() ||
        (r268_lan_busy &&
         (r268_current_phase==R268_LAN_LISTENING ||
          r268_current_phase==R268_LAN_THINKING ||
          r268_current_phase==R268_LAN_SPEAKING));
    const char *wi=net.has_ip?(gateway?"Wi-Fi：已就绪":"Wi-Fi：仅有IP"):
        net.connecting||net.scanning?"Wi-Fi：连接中":"Wi-Fi：离线";
    const char *phase=capturing?"录音中":speaking?"播音中":
        h10_receiving?"接收中":"待机中";
    if(r57_page==1){
        if(r479_quick_usb && strcmp(lv_label_get_text(r479_quick_usb),us))
            lv_label_set_text(r479_quick_usb,us);
        if(r479_quick_wifi && strcmp(lv_label_get_text(r479_quick_wifi),wi))
            lv_label_set_text(r479_quick_wifi,wi);
        if(r479_quick_phase && strcmp(lv_label_get_text(r479_quick_phase),phase))
            lv_label_set_text(r479_quick_phase,phase);
        // Do not invalidate QSPI widgets every 250ms for unchanged status.
        const int link_inks=(fresh?1:0)|(net.has_ip?2:0)|(gateway?4:0);
        if(link_inks!=r481_last_link_inks){
            r481_last_link_inks=link_inks;
            if(r479_quick_usb)lv_obj_set_style_text_color(r479_quick_usb,
                lv_color_hex(fresh?0x3D806D:0x61788A),0);
            if(r479_quick_wifi)lv_obj_set_style_text_color(r479_quick_wifi,
                lv_color_hex(gateway?0x3D806D:0x61788A),0);
        }
        bool busy=r479_controls_busy();
        if(r36_volume_slider){
            if(busy)lv_obj_add_state(r36_volume_slider,LV_STATE_DISABLED);
            else lv_obj_remove_state(r36_volume_slider,LV_STATE_DISABLED);
        }
        if(r36_brightness_slider){
            if(busy)lv_obj_add_state(r36_brightness_slider,LV_STATE_DISABLED);
            else lv_obj_remove_state(r36_brightness_slider,LV_STATE_DISABLED);
        }
    }else if(r57_page==2){
        // Five independently labelled rows: no shrinking a wall of text.
        struct {lv_obj_t *label;const char *value;} fields[]={
            {r487_state_usb,fresh?"Mac已连接":usb?"待确认":"未连接"},
            {r487_state_wifi,net.has_ip?(gateway?"已就绪":"仅有IP"):
                 (net.connecting||net.scanning)?"连接中":"离线"},
            {r487_state_gateway,gateway?"已鉴权":"未接通"},
            {r487_state_voice,phase},
            {r487_state_last,r36_last_turn_ok?"已完成":"未确认"}
        };
        for(unsigned i=0;i<sizeof(fields)/sizeof(fields[0]);i++){
            if(fields[i].label &&
               strcmp(lv_label_get_text(fields[i].label),fields[i].value))
                lv_label_set_text(fields[i].label,fields[i].value);
        }
        if(r487_state_gateway)lv_obj_set_style_text_color(
            r487_state_gateway,lv_color_hex(gateway?0x3C816E:0x4F7183),0);
    }
}

// UTF-8-safe truncated preview: do not replace/alter Mac's real transcript.
// The board's small font subset cannot render every Unicode point. Suppress
// unsupported codepoints to a visible middle dot; never show tofu squares.
// Mac remains the full-fidelity source of the real conversation.
static bool r62_chat_render(char *out,size_t limit,const char *src,size_t max_scan){
    size_t pos=0,used=0;bool missing=false,mark=false;
    while(src && src[pos] && used+4<limit && pos<max_scan){
        const unsigned char *p=(const unsigned char*)src+pos;
        uint32_t cp=0;unsigned bytes=1;
        if(p[0]<0x80){cp=p[0];}
        else if((p[0]&0xE0)==0xC0){bytes=2;cp=p[0]&0x1F;}
        else if((p[0]&0xF0)==0xE0){bytes=3;cp=p[0]&0x0F;}
        else if((p[0]&0xF8)==0xF0){bytes=4;cp=p[0]&0x07;}
        else {missing=true;pos++;continue;}
        bool valid=true;
        for(unsigned i=1;i<bytes;i++){
            if(pos+i>=max_scan || !p[i] || (p[i]&0xC0)!=0x80){valid=false;break;}
            cp=(cp<<6)|(p[i]&0x3F);
        }
        if(!valid){missing=true;pos++;continue;}
        lv_font_glyph_dsc_t d={0};
        bool drawable=(cp=='\n'||cp==' '||cp=='\t') ||
            lv_font_get_glyph_dsc(&lv_font_r57_cn_16,&d,cp,0);
        if(drawable && used+bytes<limit-1){
            memcpy(out+used,p,bytes);used+=bytes;mark=false;
        }else if(!mark && used+3<limit-1){
            memcpy(out+used,"·",2);used+=2;mark=true;missing=true;
        }else {missing=true;}
        pos+=bytes;
    }
    if(src && src[pos])missing=true;
    out[used]=0;
    return missing;
}
static bool r60_chat_preview(char out[192],const char *src){
    return r62_chat_render(out,192,src,127);
}
static void r57_refresh(lv_timer_t *timer){
    (void)timer;
    // R61: only the primary LVGL status timer owns mic colors. Previously
    // r57_refresh (250ms) and r33_update_status (1000ms) alternated colors,
    // causing a visible flash even when the user never touched the mic.
    if(r59_mic_caption){
        const char *wanted=capturing?"发送":"录音";
        if(strcmp(lv_label_get_text(r59_mic_caption),wanted)!=0)
            lv_label_set_text(r59_mic_caption,wanted);
    }
    TickType_t now=xTaskGetTickCount();
    if(r57_timer_running){
        uint32_t elapsed=(uint32_t)(now-r57_timer_started)/configTICK_RATE_HZ;
        if(elapsed>=r57_timer_remaining){
            r57_timer_running=false;r57_timer_remaining=0;
            r57_timer_finished=true;
            if(status_label)lv_label_set_text(status_label,"计时结束");
        }
    }
    if(r57_page==5 && r57_counter){
        uint32_t value=r57_timer_remaining;
        if(r57_timer_running){
            uint32_t elapsed=(uint32_t)(now-r57_timer_started)/configTICK_RATE_HZ;
            value=elapsed>=value?0:value-elapsed;
        }
        lv_label_set_text_fmt(r57_counter,"%02lu:%02lu:%02lu",
            (unsigned long)(value/3600),(unsigned long)((value%3600)/60),
            (unsigned long)(value%60));
        if(r57_timer_note)lv_label_set_text(r57_timer_note,
            r57_timer_finished?"计时结束":r57_timer_running?"计时中":"自定义 1 秒到 24 小时");
    }
    if(r57_page==0 && r223_wifi_icon && r277_wifi_badge){
        // Three observable states; a saved marker alone is NOT connectivity.
        // The icon shape/badge changes even on a monochrome or dim display.
        static int r277_last_wifi_state=-1;
        r62_wifi_state_t wifi={0};r62_wifi_snapshot(&wifi);
        const int state=wifi.ready && wifi.has_ip ? 2:
            (wifi.connecting || wifi.scanning ||
             (wifi.ready && wifi.saved && !wifi.has_ip)) ? 1:0;
        if(state!=r277_last_wifi_state){
            const uint32_t color=state==2?0x26825A:
                state==1?0xC18A24:0x63768A;
            lv_obj_set_style_text_color(r223_wifi_icon,lv_color_hex(color),0);
            lv_obj_set_style_text_color(r277_wifi_badge,lv_color_hex(color),0);
            if(state==2)lv_obj_add_flag(r277_wifi_badge,LV_OBJ_FLAG_HIDDEN);
            else{
                lv_label_set_text(r277_wifi_badge,
                    state==1?LV_SYMBOL_REFRESH:LV_SYMBOL_CLOSE);
                lv_obj_remove_flag(r277_wifi_badge,LV_OBJ_FLAG_HIDDEN);
            }
            r277_last_wifi_state=state;
        }
    }
    if(r57_page==1 || r57_page==2)r479_refresh_connections();
    if(r57_page==10)r62_wifi_refresh();
    if(r57_page==9)r211_storage_refresh();
    if(r57_page==4 && r57_seen_revision!=r57_recent_revision){
        r57_seen_revision=r57_recent_revision;
        for(unsigned i=0;i<4;i++){
            if(r57_recent_labels[i]){
                char cleaned[192]={0};
                if(r57_recent[i][0]){
                    bool omitted=r60_chat_preview(cleaned,r57_recent[i]);
                    lv_label_set_text(r57_recent_labels[i],cleaned);
                    if(omitted)ESP_LOGW("R60_CHAT","unsupported_glyph_hidden slot=%u",i);
                }else lv_label_set_text(r57_recent_labels[i],"暂无记录");
            }
        }
    }
}
static void r57_open_page(unsigned page){
    if(r57_root)r57_close_page();
    if(page==0)return;
    if(page>17)page=1;
    r57_page=page;
    lv_obj_t *screen=lv_screen_active();
    r57_root=lv_obj_create(screen);
    lv_obj_set_size(r57_root,480,480);lv_obj_align(r57_root,LV_ALIGN_TOP_LEFT,0,0);
    lv_obj_set_style_radius(r57_root,0,0);
    lv_obj_set_style_border_width(r57_root,0,0);
    lv_obj_set_style_pad_all(r57_root,0,0);
    lv_obj_set_style_bg_opa(r57_root,LV_OPA_COVER,0);
    lv_obj_set_style_bg_color(r57_root,lv_color_hex(0xFFFFFF),0);
    lv_obj_remove_flag(r57_root,LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_event_cb(r57_root,r57_gesture,LV_EVENT_GESTURE,NULL);
    if(page==1){
        // A compact control-center with a consistent baseline grid.
        lv_obj_set_style_bg_color(r57_root,lv_color_hex(0xF4F7F9),0);
        lv_obj_t *handle=r481_plate(r57_root,217,12,46,4,0xB5C6D1,3);
        lv_obj_set_style_border_width(handle,0,0);
        r481_ink(r57_root,"大肥鱼",27,29,230,true,0x233D50);
        r487_caption(r57_root,"控制中心",29,70,175,0x8AA0AE);
        r481_plate(r57_root,352,34,100,35,0xE9F2F6,18);
        r479_quick_phase=r487_caption(r57_root,"待机中",358,40,88,0x4D778E);
        lv_obj_set_style_text_align(r479_quick_phase,LV_TEXT_ALIGN_CENTER,0);

        r481_plate(r57_root,26,104,207,67,0xFFFFFF,19);
        r481_plate(r57_root,246,104,208,67,0xFFFFFF,19);
        lv_obj_t *usb_dot=r481_plate(r57_root,43,134,8,8,0xA8BAC5,4);
        lv_obj_set_style_border_width(usb_dot,0,0);
        lv_obj_t *wifi_dot=r481_plate(r57_root,263,134,8,8,0x7FB6CF,4);
        lv_obj_set_style_border_width(wifi_dot,0,0);
        r479_quick_usb=r481_ink(r57_root,"USB：未连接",58,119,167,false,0x486575);
        r479_quick_wifi=r481_ink(r57_root,"Wi-Fi：离线",278,119,170,false,0x486575);

        r481_plate(r57_root,26,183,428,169,0xFFFFFF,22);
        r487_caption(r57_root,"声音与显示",49,198,206,0x879DAA);
        r487_icon(r57_root,"音",48,225);
        r481_ink(r57_root,"音量",99,229,137,false,0x29485D);
        r36_volume_pct=r481_ink(r57_root,"70%",361,229,72,false,0x507F9B);
        lv_obj_set_style_text_align(r36_volume_pct,LV_TEXT_ALIGN_RIGHT,0);
        r36_volume_slider=lv_slider_create(r57_root);
        lv_obj_set_size(r36_volume_slider,323,11);
        lv_obj_align(r36_volume_slider,LV_ALIGN_TOP_LEFT,104,259);
        r481_slider_skin(r36_volume_slider);
        lv_slider_set_range(r36_volume_slider,20,95);
        lv_slider_set_value(r36_volume_slider,volume,LV_ANIM_OFF);
        lv_obj_remove_flag(r36_volume_slider,LV_OBJ_FLAG_GESTURE_BUBBLE);
        lv_obj_add_event_cb(r36_volume_slider,r57_volume_update,LV_EVENT_VALUE_CHANGED,NULL);
        lv_label_set_text_fmt(r36_volume_pct,"%u%%",volume);
        r487_rule(r57_root,50,282,377);
        r487_icon(r57_root,"光",48,290);
        r481_ink(r57_root,"亮度",99,292,138,false,0x29485D);
        r36_brightness_pct=r481_ink(r57_root,"60%",361,292,72,false,0x507F9B);
        lv_obj_set_style_text_align(r36_brightness_pct,LV_TEXT_ALIGN_RIGHT,0);
        r36_brightness_slider=lv_slider_create(r57_root);
        lv_obj_set_size(r36_brightness_slider,323,11);
        lv_obj_align(r36_brightness_slider,LV_ALIGN_TOP_LEFT,104,324);
        r481_slider_skin(r36_brightness_slider);
        lv_slider_set_range(r36_brightness_slider,10,100);
        lv_slider_set_value(r36_brightness_slider,r33_brightness,LV_ANIM_OFF);
        lv_obj_remove_flag(r36_brightness_slider,LV_OBJ_FLAG_GESTURE_BUBBLE);
        lv_obj_add_event_cb(r36_brightness_slider,r57_brightness_update,
                            LV_EVENT_VALUE_CHANGED,NULL);
        lv_label_set_text_fmt(r36_brightness_pct,"%u%%",r33_brightness);

        lv_obj_t *net=r481_action(r57_root,"Wi-Fi 连接",26,365,207,58,10,true);
        r487_rounded_action(net,true);
        lv_obj_t *status=r481_action(r57_root,"设备状态",247,365,207,58,2,false);
        r487_rounded_action(status,false);
        lv_obj_t *extra=r481_action(r57_root,"更多信息",128,435,224,39,12,false);
        lv_obj_set_style_border_width(extra,0,0);
        lv_obj_set_style_bg_color(extra,lv_color_hex(0xF4F7F9),0);
        lv_obj_t *footer=lv_obj_get_child(extra,0);
        if(footer)lv_obj_set_style_text_font(footer,&lv_font_r487_cn_18,0);
        r479_refresh_connections();
        return;
    }
    if(page==12){
        lv_obj_set_style_bg_color(r57_root,lv_color_hex(0xF4F7F9),0);
        lv_obj_t *back=r481_action(r57_root,"返回",26,30,98,49,1,false);
        r487_rounded_action(back,false);
        r481_ink(r57_root,"更多信息",166,37,226,true,0x243F51);
        r487_caption(r57_root,"设备管理",29,104,216,0x89A0AE);
        lv_obj_t *storage=r481_action(r57_root,"",26,139,428,98,9,false);
        r487_rounded_action(storage,false);
        r487_icon(r57_root,"存",46,168);
        r481_ink(r57_root,"存储空间",99,160,264,false,0x253F52);
        r487_caption(r57_root,"›",415,166,30,0x93ABBC);
        lv_obj_t *about=r481_action(r57_root,"",26,254,428,98,17,false);
        r487_rounded_action(about,false);
        r487_icon(r57_root,"设",46,283);
        r481_ink(r57_root,"关于设备",99,276,261,false,0x253F52);
        r487_caption(r57_root,"›",415,283,30,0x93ABBC);
        return;
    }
    if(page==17){
        lv_obj_set_style_bg_color(r57_root,lv_color_hex(0xF4F7F9),0);
        lv_obj_t *back=r481_action(r57_root,"返回",26,30,98,49,12,false);
        r487_rounded_action(back,false);
        r481_ink(r57_root,"关于设备",166,37,226,true,0x243F51);
        const esp_app_desc_t *app=esp_app_get_description();
        const char *version=app && app->version[0]?app->version:"待确认";
        char built[105];
        snprintf(built,sizeof(built),"%s %s",
            app&&app->date[0]?app->date:"--",
            app&&app->time[0]?app->time:"--");
        r481_plate(r57_root,26,113,428,137,0xFFFFFF,23);
        r487_caption(r57_root,"当前固件",52,138,201,0x89A0AE);
        r481_ink(r57_root,version,52,168,235,true,0x244358);
        r481_plate(r57_root,344,168,77,34,0xE8F4EE,17);
        r487_caption(r57_root,"运行中",352,173,64,0x568570);

        r481_plate(r57_root,26,267,428,175,0xFFFFFF,23);
        r487_caption(r57_root,"设备型号",52,295,186,0x88A0AF);
        r481_ink(r57_root,"ESP32-S3",244,290,178,false,0x264459);
        r487_rule(r57_root,50,353,377);
        r487_caption(r57_root,"构建时间",52,375,182,0x88A0AF);
        r487_caption(r57_root,built,208,373,217,0x3F6277);
        return;
    }
    if(page==10){
        r62_wifi_build_page();
        return;
    }
    if(page==11){
        r57_button(r57_root,"返回",35,42,80,43,r57_nav,3,0xF3F6FB);
        r57_text(r57_root,"本地口头指令映射",139,51,290,true);
        r57_text(r57_root,"先说：嗨乐鑫。回应后8秒内说一句：",42,104,405,false);
        lv_obj_t *pane=lv_obj_create(r57_root);
        lv_obj_set_size(pane,398,308);
        lv_obj_align(pane,LV_ALIGN_TOP_LEFT,40,150);
        lv_obj_set_style_bg_color(pane,lv_color_hex(0xF5F9FF),0);
        lv_obj_set_style_radius(pane,14,0);
        lv_obj_set_style_border_width(pane,0,0);
        lv_obj_set_style_pad_all(pane,4,0);
        lv_obj_add_flag(pane,LV_OBJ_FLAG_SCROLLABLE);
        for(size_t k=0;k<R259_COMMAND_COUNT;k++){
            char line[180];
            int length=snprintf(line,sizeof(line),"%s → %s",
                 R259_COMMANDS[k].ask,R259_COMMANDS[k].reply);
            if(length<=0 || length>=(int)sizeof(line))continue;
            lv_obj_t *lbl=r57_text(pane,line,9,12+(int)k*70,350,false);
            lv_obj_set_height(lbl,65);
            lv_label_set_long_mode(lbl,LV_LABEL_LONG_WRAP);
        }
        return;
    }
    if(page>=13 && page<=16){
        unsigned idx=page-13;
        r57_button(r57_root,"返回",42,43,80,42,r57_nav,4,0xF3F6FB);
        r57_text(r57_root,idx%2?"大肥鱼回复":"我的提问",164,50,255,true);
        lv_obj_t *pane=lv_obj_create(r57_root);
        lv_obj_set_size(pane,395,339);
        lv_obj_align(pane,LV_ALIGN_TOP_LEFT,42,105);
        lv_obj_set_style_bg_color(pane,lv_color_hex(0xF5F9FF),0);
        lv_obj_set_style_radius(pane,16,0);
        lv_obj_set_style_border_width(pane,0,0);
        lv_obj_add_flag(pane,LV_OBJ_FLAG_SCROLLABLE);
        char full[820]={0};
        r62_chat_render(full,sizeof(full),r57_recent[idx],768);
        lv_obj_t *txt=lv_label_create(pane);
        lv_label_set_text(txt,full[0]?full:"暂无记录");
        lv_obj_set_width(txt,347);
        lv_label_set_long_mode(txt,LV_LABEL_LONG_WRAP);
        lv_obj_set_style_text_font(txt,&lv_font_r57_cn_16,0);
        lv_obj_set_style_text_color(txt,lv_color_hex(0x253D5F),0);
        return;
    }
    // Storage owns its complete page; no second "系统设置" toolbar.
    if(page==9){
        r211_storage_page();
        return;
    }
    static const char *titles[]={"","", "通信追踪","本地指令","对话记录","计时提醒",
           "音量调节","屏幕亮度","唤醒设置","系统设置"};

    if(page==2){
        // Square-screen-safe detailed status page.
        lv_obj_set_style_bg_color(r57_root,lv_color_hex(0xF3F7F9),0);
        r481_action(r57_root,"返回",27,32,82,48,1,false);
        r481_ink(r57_root,"设备状态",158,33,233,true,0x243E52);
    }else{
        r57_button(r57_root,"返回",42,43,80,42,r57_nav,1,0xF3F6FB);
        r57_text(r57_root,titles[page],175,49,256,true);
    }
    if(page==2){
        r481_plate(r57_root,26,119,428,325,0xFFFFFF,23);
        r487_caption(r57_root,"连接与语音",51,137,251,0x89A0AE);
        r487_rule(r57_root,51,173,376);
        r487_caption(r57_root,"USB",51,194,153,0x7D98A9);
        r487_state_usb=r481_ink(r57_root,"未连接",228,188,202,false,0x36556A);
        r487_rule(r57_root,51,225,376);
        r487_caption(r57_root,"Wi-Fi",51,242,153,0x7D98A9);
        r487_state_wifi=r481_ink(r57_root,"离线",228,235,200,false,0x36556A);
        r487_rule(r57_root,51,274,376);
        r487_caption(r57_root,"语音网关",51,289,157,0x7D98A9);
        r487_state_gateway=r481_ink(r57_root,"未接通",228,282,200,false,0x36556A);
        r487_rule(r57_root,51,324,376);
        r487_caption(r57_root,"当前语音",51,338,152,0x7D98A9);
        r487_state_voice=r481_ink(r57_root,"待机中",228,332,200,false,0x36556A);
        r487_rule(r57_root,51,375,376);
        r487_caption(r57_root,"上轮对话",51,389,153,0x7D98A9);
        r487_state_last=r481_ink(r57_root,"未确认",228,383,200,false,0x36556A);
        r479_refresh_connections();
    }else if(page==3){
#if defined(DF_R225_LOCAL_OFFLINE) && defined(DF_R185_WN9)
        r57_text(r57_root,"点按钮即可播放SD预置语音",52,122,390,false);
        static const char *local_labels[]={"打招呼","离线介绍","生活小贴士","状态说明","下次见"};
        static const unsigned local_clips[]={1u,2u,3u,4u,8u};
        for(unsigned k=0;k<5u;k++){
            r57_button(r57_root,local_labels[k],45+(int)(k%2u)*198,
                168+(int)(k/2u)*71,187,57,r257_local_voice_click,
                local_clips[k],k%2u?0xF4F7FF:0xE9F3FF);
        }
        r57_button(r57_root,"查看唤醒后7条口头指令",47,409,386,48,
                   r57_nav,11,0xDDEBFF);
#else
        r57_text(r57_root,"离线中文语音尚未启用",57,190,375,false);
#endif
    }else if(page==4){
        r57_text(r57_root,"最近两轮对话 · 来自 Mac",52,106,390,false);
        for(unsigned i=0;i<4;i++){
            lv_obj_t *card=lv_obj_create(r57_root);
            lv_obj_set_size(card,388,64);
            lv_obj_align(card,LV_ALIGN_TOP_LEFT,46,141+i*70);
            lv_obj_set_style_bg_color(card,lv_color_hex(i%2?0xF4F9FF:0xF7F8FA),0);
            lv_obj_set_style_border_width(card,0,0);
            lv_obj_set_style_radius(card,12,0);
            lv_obj_set_style_pad_all(card,0,0);
            lv_obj_remove_flag(card,LV_OBJ_FLAG_SCROLLABLE);
            lv_obj_add_flag(card,LV_OBJ_FLAG_CLICKABLE);
            lv_obj_add_event_cb(card,r57_nav,LV_EVENT_CLICKED,
                                (void*)(uintptr_t)(13+i));
            char cleaned[192]={0};
            if(r57_recent[i][0])r60_chat_preview(cleaned,r57_recent[i]);
            r57_recent_labels[i]=r57_text(card,
                 r57_recent[i][0]?cleaned:"暂无记录",12,9,365,false);
        }
        r57_text(r57_root,"点按卡片阅读全文 · 最多两轮",52,430,390,false);
        r57_seen_revision=r57_recent_revision;
    }else if(page==5){
        r57_counter=r57_text(r57_root,"00:01:00",136,125,250,true);
        const char *units[]={"小时","分钟","秒"};
        for(unsigned i=0;i<3;i++){
            int x=59+(int)i*130;
            r57_text(r57_root,units[i],x+21,185,110,false);
            r57_button(r57_root,"+",x,223,57,50,r57_timer_adjust,i*2,0xE8F3FF);
            r57_button(r57_root,"-",x+61,223,57,50,r57_timer_adjust,i*2+1,0xF5F7FA);
        }
        r57_button(r57_root,"开始 / 暂停",64,321,203,55,r57_timer_toggle,0,0xDDEEFF);
        r57_button(r57_root,"重置",277,321,137,55,r57_timer_reset,0,0xFFF0F1);
        r57_timer_note=r57_text(r57_root,"自定义 1 秒到 24 小时",87,401,331,false);
        r57_refresh(NULL);
    }else if(page==6 || page==7){
        bool brightness=page==7;
        r57_text(r57_root,brightness?"屏幕亮度":"喇叭音量",60,155,270,true);
        lv_obj_t *pct=r57_text(r57_root,"70%",367,153,75,true);
        lv_obj_t *slider=lv_slider_create(r57_root);
        lv_obj_set_size(slider,349,19);
        lv_obj_align(slider,LV_ALIGN_TOP_LEFT,66,223);
        lv_slider_set_range(slider,brightness?10:20,brightness?100:95);
        lv_slider_set_value(slider,brightness?r33_brightness:volume,LV_ANIM_OFF);
        if(brightness){
            r36_brightness_slider=slider;r36_brightness_pct=pct;
            lv_obj_add_event_cb(slider,r57_brightness_update,LV_EVENT_VALUE_CHANGED,NULL);
        }else{
            r36_volume_slider=slider;r36_volume_pct=pct;
            lv_obj_add_event_cb(slider,r57_volume_update,LV_EVENT_VALUE_CHANGED,NULL);
        }
        lv_label_set_text_fmt(pct,"%u%%",brightness?r33_brightness:volume);
        r57_text(r57_root,brightness?"调整当前显示亮度":"按需调整，建议保留当前适宜音量",
                 76,302,330,false);
    }else if(page==8){
        r57_text(r57_root,"本地唤醒词：嗨乐鑫",58,142,360,true);
        r57_text(r57_root,"连接Mac：唤醒后正常对话",58,207,367,false);
        r57_text(r57_root,"脱离Mac：唤醒后8秒内说口令",58,267,362,false);
        r57_button(r57_root,"查看7条预置回复映射",46,327,383,59,r57_nav,11,0xDDEBFF);
    }
}
static void r57_style_home(lv_obj_t *screen,lv_obj_t *mic,lv_obj_t *mic_label){
    lv_obj_set_style_bg_color(screen,lv_color_hex(0xFFFFFF),0);
    lv_obj_align(r33_header,LV_ALIGN_TOP_LEFT,58,36);
    lv_obj_set_style_text_font(r33_header,&lv_font_r57_cn_16,0);
    lv_obj_align(r36_mac_dot,LV_ALIGN_TOP_LEFT,43,43);
    lv_obj_align(r36_clock_label,LV_ALIGN_TOP_MID,0,33);
    lv_obj_set_style_text_font(r36_clock_label,&lv_font_r57_cn_16,0);
    lv_obj_align(r36_battery_shell,LV_ALIGN_TOP_RIGHT,-97,42);
    lv_obj_align(r33_battery,LV_ALIGN_TOP_RIGHT,-47,39);
    r223_wifi_icon=lv_label_create(screen);
    lv_label_set_text(r223_wifi_icon,LV_SYMBOL_WIFI);
    lv_obj_set_style_text_font(r223_wifi_icon,LV_FONT_DEFAULT,0);
    lv_obj_set_style_text_color(r223_wifi_icon,lv_color_hex(0x63768A),0);
    // R267: status icon shares the power/battery header row; Wi-Fi details
    // remain available on the Wi-Fi settings page, not as a second-row label.
    lv_obj_align(r223_wifi_icon,LV_ALIGN_TOP_RIGHT,-139,40);
    // Visible offline "x" / in-progress refresh badge; previously only
    // changed green vs gray while keeping identical Wi-Fi glyphs.
    r277_wifi_badge=lv_label_create(screen);
    lv_label_set_text(r277_wifi_badge,LV_SYMBOL_CLOSE);
    lv_obj_set_style_text_font(r277_wifi_badge,LV_FONT_DEFAULT,0);
    lv_obj_set_style_text_color(r277_wifi_badge,lv_color_hex(0x63768A),0);
    lv_obj_align(r277_wifi_badge,LV_ALIGN_TOP_RIGHT,-125,34);
    lv_obj_set_style_text_font(r33_battery,&lv_font_r57_cn_16,0);
    lv_obj_align(picture,LV_ALIGN_TOP_LEFT,120,96);
    lv_obj_set_size(mic,183,64);
    lv_obj_align(mic,LV_ALIGN_TOP_LEFT,47,348);
    lv_obj_set_style_bg_color(mic,lv_color_hex(0xE8F2FF),0);
    lv_obj_set_style_border_color(mic,lv_color_hex(0xBCD9FD),0);
    lv_obj_set_style_radius(mic,17,0);
    lv_obj_set_style_bg_color(mic,lv_color_hex(0xCBE4FF),LV_STATE_PRESSED);
    lv_obj_set_style_border_color(mic,lv_color_hex(0x6CAAF0),LV_STATE_PRESSED);
    // R281: the animated pressed-state outer shadow expands the LVGL
    // dirty rectangle beyond the button, exactly where the user saw
    // stale blue stripes during Wi-Fi playback. Keep a visible pressed
    // fill and border but no QSPI partial-flush shadow overlays.
    lv_obj_set_style_shadow_width(mic,0,LV_STATE_PRESSED);
    lv_obj_set_style_shadow_opa(mic,LV_OPA_TRANSP,LV_STATE_PRESSED);
    r59_mic_caption=mic_label;
    lv_label_set_text(mic_label,"录音");
    lv_obj_set_style_text_font(mic_label,&lv_font_r57_cn_16,0);
    lv_obj_set_style_text_color(mic_label,lv_color_hex(0x236CCA),0);
    lv_obj_align(mic_label,LV_ALIGN_RIGHT_MID,-19,0);
    if(r46_mic_img){
        lv_image_set_scale(r46_mic_img,171);  // 44px to approx 29px
        lv_obj_align(r46_mic_img,LV_ALIGN_LEFT_MID,21,0);
    }
    if(r33_mic_stop){
        lv_label_set_text(r33_mic_stop,"结束录音");
        lv_obj_set_style_text_font(r33_mic_stop,&lv_font_r57_cn_16,0);
    }
    r57_main_stop=r57_button(screen,"停止播音",250,348,183,64,
                              r51_stop_audio,0,0xFFE8EE);
    lv_obj_set_size(status_label,392,34);
    lv_obj_align(status_label,LV_ALIGN_TOP_MID,0,429);
    lv_obj_set_style_text_font(status_label,&lv_font_r57_cn_16,0);
    lv_obj_set_style_bg_color(status_label,lv_color_hex(0xF4F7FC),0);
    lv_label_set_text(status_label,"待机中 · 点击录音");
    lv_obj_add_event_cb(screen,r57_gesture,LV_EVENT_GESTURE,NULL);
    lv_timer_create(r57_refresh,250,NULL);
}
