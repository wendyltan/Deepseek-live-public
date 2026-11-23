#include "dfsp_stage.h"
static unsigned mix_channel(unsigned back,unsigned dark,unsigned weight){
    return (back*(255u-weight)+dark*weight+127u)/255u;
}
void dfsp_stage_background(uint8_t *rgb565, uint16_t width,uint16_t height){
    if(!rgb565||!width||!height||width>480||height>480)return;
    const uint16_t bg=DAFEIYU_STAGE_BG_RGB565;
    for(size_t i=0;i<(size_t)width*height;i++){
        rgb565[2*i]=(uint8_t)bg;rgb565[2*i+1]=(uint8_t)(bg>>8);
    }
}
int dfsp_stage_soft_shadow(uint8_t *dst,uint16_t width,uint16_t height,
                          int cx,int cy,int rx,int ry){
    if(!dst||!width||!height||width>480||height>480||
       rx<4||ry<3||rx>240||ry>240)return -1;
    int affected=0;
    for(int y=cy-ry;y<=cy+ry;y++){
        if(y<0||y>=(int)height)continue;
        for(int x=cx-rx;x<=cx+rx;x++){
            if(x<0||x>=(int)width)continue;
            long dx=(long)(x-cx)*(x-cx)*1024/(rx*rx);
            long dy=(long)(y-cy)*(y-cy)*1024/(ry*ry);
            long r=dx+dy;
            if(r>=1024)continue;
            // Smooth falloff: feathered edge, dark center maximum ~13% shade.
            unsigned q=(unsigned)(1024-r);
            unsigned a=34u*q*q/(1024u*1024u);
            if(!a)continue;
            size_t i=2u*((size_t)y*width+(size_t)x);
            unsigned src=(unsigned)dst[i]|((unsigned)dst[i+1]<<8);
            unsigned sr=(src>>11)&31u,sg=(src>>5)&63u,sb=src&31u;
            unsigned red=mix_channel(sr,9u,a);
            unsigned green=mix_channel(sg,23u,a);
            unsigned blue=mix_channel(sb,22u,a);
            unsigned out=(red<<11)|(green<<5)|blue;
            dst[i]=(uint8_t)out;dst[i+1]=(uint8_t)(out>>8);
            affected++;
        }
    }
    return affected;
}
