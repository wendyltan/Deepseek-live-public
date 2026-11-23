#pragma once
// R67 isolated on-device Wi-Fi UI. No auto-radio or background scan.
// Included after r57 UI primitives. R211 persists the verified network
// using regular unencrypted NVS; never reveal stored passwords on screen.
#include "r62_wifi.h"
#include <string.h>
#include <stdio.h>

static lv_obj_t *r62_wifi_rows[5]={0};
static lv_obj_t *r62_wifi_status=NULL;
static lv_obj_t *r62_wifi_modal=NULL;
static lv_obj_t *r62_wifi_field=NULL;
static lv_obj_t *r62_wifi_keyboard=NULL;
static lv_obj_t *r62_wifi_reveal_btn=NULL;
static bool r62_wifi_password_visible=false;
static lv_obj_t *r211_forget_dialog=NULL;
static char r62_wifi_selected_ssid[33]={0};
// Mixed Wi-Fi names need CJK *and* complete Latin glyph coverage.
// This is a copy of our local 16px font descriptor, not an external font.
static lv_font_t r269_wifi_mixed_font;
static bool r269_wifi_mixed_font_ready=false;
static const lv_font_t *r269_wifi_font(void){
    if(!r269_wifi_mixed_font_ready){
        r269_wifi_mixed_font=lv_font_r57_cn_16;
        r269_wifi_mixed_font.fallback=&lv_font_montserrat_16;
        r269_wifi_mixed_font_ready=true;
    }
    return &r269_wifi_mixed_font;
}
// Decode a bounded UTF-8 SSID for DISPLAY ONLY. Never change its original
// 32-byte Wi-Fi driver value used for connecting. Reject invalid, control,
// zero-width/bidi or unsupported glyphs; never show replacement-glyph boxes.
static bool r269_safe_ssid_text(const char *ssid,size_t n){
    if(n==0||n>32)return false;
    const lv_font_t *font=r269_wifi_font();
    for(size_t i=0;i<n;){
        unsigned char a=(unsigned char)ssid[i++];
        uint32_t cp=a;
        unsigned extra=0;
        if(a<0x20||a==0x7f)return false;
        if(a>=0x80){
            if(a>=0xc2&&a<=0xdf){cp=a&0x1f;extra=1;}
            else if(a>=0xe0&&a<=0xef){cp=a&0x0f;extra=2;}
            else if(a>=0xf0&&a<=0xf4){cp=a&0x07;extra=3;}
            else return false;
            if(i+extra>n)return false;
            for(unsigned j=0;j<extra;j++){
                unsigned char b=(unsigned char)ssid[i++];
                if((b&0xc0)!=0x80)return false;
                cp=(cp<<6)|(b&0x3f);
            }
            if((extra==1&&cp<0x80)||(extra==2&&cp<0x800)||
               (extra==3&&cp<0x10000)||cp>0x10ffff||
               (cp>=0xd800&&cp<=0xdfff))return false;
        }
        if((cp>=0x200b&&cp<=0x200f)||(cp>=0x202a&&cp<=0x202e)||
           (cp>=0x2060&&cp<=0x206f))return false;
        lv_font_glyph_dsc_t desc={0};
        if(!lv_font_get_glyph_dsc(font,&desc,cp,0)||desc.is_placeholder)
            return false;
    }
    return true;
}
static void r223_safe_ssid(char *out,size_t size,const char *ssid,unsigned row){
    size_t n=strnlen(ssid,33);
    if(r269_safe_ssid_text(ssid,n))
        snprintf(out,size,"%.*s",(int)n,ssid);
    else
        snprintf(out,size,"网络 %u · 名称暂不显示",row+1);
}

static void r62_wifi_refresh(void){
    if(r57_page!=10 || !r57_root || !r62_wifi_status)return;
    r62_wifi_state_t status={0};
    r62_wifi_snapshot(&status);
    char line[128];
    if(status.has_ip)snprintf(line,sizeof(line),"IP: %s · %s",status.ip,
                                 status.persistence_stage==4?"保存失败":
        (status.persistence_stage==3&&status.saved?
          (status.persistence_generation>0?"已记住":"保存待确认"):"正在保存"));
    else if(status.connecting)snprintf(line,sizeof(line),"Wi-Fi connecting...");
    else if(status.scanning)snprintf(line,sizeof(line),"Wi-Fi scanning...");
    else if(status.needs_setup)snprintf(line,sizeof(line),"原网络配置无效 · 请扫描 2.4G 重新连接");
    else if(status.error)snprintf(line,sizeof(line),
        "Wi-Fi error %d (stage %u, rc %d)",status.error,
        (unsigned)status.diagnostic_stage,status.diagnostic_esp_error);
    else if(status.saved)snprintf(line,sizeof(line),"已记住网络 · 等待重连");
    else snprintf(line,sizeof(line),"Wi-Fi: not connected");
    if(strcmp(lv_label_get_text(r62_wifi_status),line))
        lv_label_set_text(r62_wifi_status,line);
    for(unsigned i=0;i<5;i++){
        if(!r62_wifi_rows[i])continue;
        if(i<(unsigned)status.count){
            char readable[75]={0};
            r223_safe_ssid(readable,sizeof(readable),status.ssid[i],i);
            snprintf(line,sizeof(line),"%u. %s (%d dBm)",i+1,
                readable,status.signal[i]);
            if(strcmp(lv_label_get_text(r62_wifi_rows[i]),line))
                lv_label_set_text(r62_wifi_rows[i],line);
        }else{
            lv_label_set_text(r62_wifi_rows[i],"-");
        }
    }
}
static void r62_wifi_scan_click(lv_event_t *ev){
    (void)ev;
    if(capturing||speaking||h10_receiving)return;
    r62_wifi_scan(); // explicit gesture only; never boot-time scan
    r62_wifi_refresh();
}
static void r62_wifi_password_toggle(lv_event_t *ev){
    (void)ev;
    if(!r62_wifi_field||!r62_wifi_reveal_btn)return;
    r62_wifi_password_visible=!r62_wifi_password_visible;
    lv_textarea_set_password_mode(r62_wifi_field,!r62_wifi_password_visible);
    lv_obj_t *caption=lv_obj_get_child(r62_wifi_reveal_btn,0);
    if(caption)lv_label_set_text(caption,r62_wifi_password_visible?"隐藏":"显示");
}
static void r62_wifi_close_modal(void){
    if(r62_wifi_field)lv_textarea_set_text(r62_wifi_field,"");
    if(r62_wifi_modal)lv_obj_delete_async(r62_wifi_modal);
    r62_wifi_modal=NULL;r62_wifi_field=NULL;r62_wifi_keyboard=NULL;
    r62_wifi_reveal_btn=NULL;r62_wifi_password_visible=false;
    memset(r62_wifi_selected_ssid,0,sizeof(r62_wifi_selected_ssid));
}
static void r62_wifi_modal_event(lv_event_t *ev){
    lv_event_code_t code=lv_event_get_code(ev);
    if(code==LV_EVENT_CANCEL){
        r62_wifi_close_modal();return;
    }
    if(code!=LV_EVENT_READY || !r62_wifi_field)return;
    // No password in logs or USB. After confirmed IP it is saved into
    // regular (unencrypted) ESP-IDF NVS by the Wi-Fi worker.
    char secret[65]={0};
    const char *input=lv_textarea_get_text(r62_wifi_field);
    if(input){
        size_t n=strnlen(input,sizeof(secret));
        if(n<sizeof(secret))memcpy(secret,input,n);
    }
    bool accepted=r62_wifi_connect(r62_wifi_selected_ssid,secret);
    memset(secret,0,sizeof(secret));
    if(!accepted){
        lv_textarea_set_text(r62_wifi_field,"");
        return;
    }
    r62_wifi_close_modal();
    r62_wifi_refresh();
}
static void r62_wifi_choose(lv_event_t *ev){
    if(capturing||speaking||h10_receiving || r62_wifi_modal)return;
    unsigned selected=(unsigned)(uintptr_t)lv_event_get_user_data(ev);
    if(!selected || selected>5)return;
    r62_wifi_state_t info={0};
    r62_wifi_snapshot(&info);
    if(selected>(unsigned)info.count || !info.ssid[selected-1][0])return;
    memcpy(r62_wifi_selected_ssid,info.ssid[selected-1],33);
    r62_wifi_modal=lv_obj_create(r57_root);
    lv_obj_set_size(r62_wifi_modal,460,450);
    lv_obj_center(r62_wifi_modal);
    lv_obj_set_style_bg_color(r62_wifi_modal,lv_color_hex(0xFFFFFF),0);
    lv_obj_set_style_border_width(r62_wifi_modal,1,0);
    lv_obj_set_style_radius(r62_wifi_modal,16,0);
    lv_obj_remove_flag(r62_wifi_modal,LV_OBJ_FLAG_SCROLLABLE);
    r57_text(r62_wifi_modal,"Wi-Fi password",20,14,365,true);
    r62_wifi_field=lv_textarea_create(r62_wifi_modal);
    lv_obj_set_size(r62_wifi_field,332,56);
    lv_obj_set_style_text_font(r62_wifi_field,&lv_font_montserrat_20,0);
    lv_obj_align(r62_wifi_field,LV_ALIGN_TOP_LEFT,14,57);
    lv_textarea_set_one_line(r62_wifi_field,true);
    lv_textarea_set_max_length(r62_wifi_field,63);
    lv_textarea_set_password_mode(r62_wifi_field,true);
    lv_textarea_set_password_show_time(r62_wifi_field,0);
    r62_wifi_password_visible=false;
    r62_wifi_reveal_btn=r57_button(r62_wifi_modal,"显示",354,57,91,56,
                                     r62_wifi_password_toggle,0,0xE8F3FF);
    // Prevent keyboard/credential swipes from reaching the menu gesture.
    lv_obj_remove_flag(r62_wifi_modal,LV_OBJ_FLAG_GESTURE_BUBBLE);
    lv_obj_remove_flag(r62_wifi_field,LV_OBJ_FLAG_GESTURE_BUBBLE);
    r62_wifi_keyboard=lv_keyboard_create(r62_wifi_modal);
    lv_obj_remove_flag(r62_wifi_keyboard,LV_OBJ_FLAG_GESTURE_BUBBLE);
    lv_obj_set_size(r62_wifi_keyboard,440,312);
    lv_obj_align(r62_wifi_keyboard,LV_ALIGN_TOP_LEFT,9,125);
    // All Latin letters, punctuation and LVGL keyboard action symbols need
    // the complete built-in Montserrat glyph map. The CJK subset is incomplete.
    lv_obj_set_style_text_font(r62_wifi_keyboard,&lv_font_montserrat_20,LV_PART_ITEMS);
    lv_keyboard_set_textarea(r62_wifi_keyboard,r62_wifi_field);
    lv_obj_add_event_cb(r62_wifi_keyboard,r62_wifi_modal_event,
                        LV_EVENT_READY,NULL);
    lv_obj_add_event_cb(r62_wifi_keyboard,r62_wifi_modal_event,
                        LV_EVENT_CANCEL,NULL);
}
static void r211_forget_cancel(lv_event_t *ev){
    (void)ev;
    if(r211_forget_dialog)lv_obj_delete_async(r211_forget_dialog);
    r211_forget_dialog=NULL;
}
static void r211_forget_confirm(lv_event_t *ev){
    (void)ev;
    (void)r62_wifi_forget();
    r211_forget_cancel(ev);
}
static void r211_forget_click(lv_event_t *ev){
    (void)ev;
    if(r211_forget_dialog||capturing||speaking||h10_receiving)return;
    r211_forget_dialog=lv_obj_create(r57_root);
    lv_obj_set_size(r211_forget_dialog,420,220);
    lv_obj_center(r211_forget_dialog);
    lv_obj_set_style_bg_color(r211_forget_dialog,lv_color_hex(0xFFFFFF),0);
    lv_obj_remove_flag(r211_forget_dialog,LV_OBJ_FLAG_SCROLLABLE);
    r57_text(r211_forget_dialog,"忘记已保存的 Wi-Fi？",25,35,365,true);
    r57_button(r211_forget_dialog,"取消",25,130,175,55,r211_forget_cancel,0,0xF3F6FB);
    r57_button(r211_forget_dialog,"确认忘记",215,130,175,55,r211_forget_confirm,0,0xFFF1ED);
}
static void r62_wifi_back_click(lv_event_t *ev){
    (void)ev;r57_open_page(1);
}
static void r62_wifi_build_page(void){
    r57_button(r57_root,"返回",30,35,92,50,r62_wifi_back_click,0,0xF3F6FB);
    r57_text(r57_root,"Wi-Fi",175,40,125,true);
    r57_button(r57_root,"忘记网络",328,35,126,49,r211_forget_click,0,0xFFF1ED);
    r62_wifi_status=r57_text(r57_root,"Wi-Fi: not connected",39,105,405,false);
    r57_button(r57_root,"扫描 2.4G",38,139,402,52,
               r62_wifi_scan_click,0,0xE8F3FF);
    for(unsigned i=0;i<5;i++){
        lv_obj_t *button=r57_button(r57_root,"",38,202+(int)i*48,
                                     402,43,r62_wifi_choose,i+1,0xF4F8FF);
        // Reuse the button's centered native LVGL label.
        r62_wifi_rows[i]=lv_obj_get_child(button,0);
        lv_obj_set_style_text_font(r62_wifi_rows[i],r269_wifi_font(),0);
    }
    r62_wifi_refresh();
}
