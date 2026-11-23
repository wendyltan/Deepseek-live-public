#include "dfsp_blit.h"
static unsigned mix(unsigned fore, unsigned back, unsigned alpha){
    return (fore*alpha + back*(255u-alpha) + 127u)/255u;
}
int dfsp_blit_rgb565a8(const uint8_t *src, uint16_t width, uint16_t height,
    uint8_t *dst, uint16_t dst_width, uint16_t dst_height,
    int x, int y, int circle_clip){
    if (!src || !dst || !width || !height || !dst_width || !dst_height ||
        width>480 || height>480 || dst_width>480 || dst_height>480 ||
        (circle_clip!=0 && circle_clip!=1)) return -1;
    const int r=(dst_width<dst_height?dst_width:dst_height)/2;
    const int cx=dst_width/2, cy=dst_height/2;
    int changed=0;
    // R502: the real avatar is always a 240x240 full-rectangle, with no
    // circle clipping, no translation and exactly the same backing size.
    // Avoid per-pixel coordinate/bounds/index arithmetic on this hot path.
    // The alpha arithmetic is deliberately identical to the generic path:
    // pixel-exact tests must pass before any physical firmware deployment.
    if(!circle_clip && x==0 && y==0 &&
       width==dst_width && height==dst_height){
        const size_t count=(size_t)width*height;
        const uint8_t *a=src;
        uint8_t *b=dst;
        for(size_t i=0;i<count;i++,a+=3,b+=2){
            const unsigned alpha=a[2];
            if(!alpha)continue;
            unsigned fore=(unsigned)a[0]|((unsigned)a[1]<<8);
            if(alpha!=255u){
                const unsigned back=(unsigned)b[0]|((unsigned)b[1]<<8);
                const unsigned r5=mix((fore>>11)&31u,(back>>11)&31u,alpha);
                const unsigned g6=mix((fore>>5)&63u,(back>>5)&63u,alpha);
                const unsigned b5=mix(fore&31u,back&31u,alpha);
                fore=(r5<<11)|(g6<<5)|b5;
            }
            b[0]=(uint8_t)fore;b[1]=(uint8_t)(fore>>8);
            changed++;
        }
        return changed;
    }
    for(unsigned sy=0;sy<height;sy++){
        int py=y+(int)sy;
        if(py<0 || py>=dst_height)continue;
        for(unsigned sx=0;sx<width;sx++){
            int px=x+(int)sx;
            if(px<0 || px>=dst_width)continue;
            if(circle_clip){
                int dx=px-cx,dy=py-cy;
                if(dx*dx+dy*dy>r*r)continue;
            }
            size_t si=((size_t)sy*width+sx)*3u;
            const unsigned alpha=src[si+2];
            if(alpha==0)continue;
            unsigned fore=(unsigned)src[si]|((unsigned)src[si+1]<<8);
            size_t di=((size_t)py*dst_width+(unsigned)px)*2u;
            unsigned back=(unsigned)dst[di]|((unsigned)dst[di+1]<<8);
            if(alpha!=255){
                /* Blend channels in their native 5-6-5 bit precision. */
                unsigned r5=mix((fore>>11)&31u,(back>>11)&31u,alpha);
                unsigned g6=mix((fore>>5)&63u,(back>>5)&63u,alpha);
                unsigned b5=mix(fore&31u,back&31u,alpha);
                fore=(r5<<11)|(g6<<5)|b5;
            }
            dst[di]=(uint8_t)fore;dst[di+1]=(uint8_t)(fore>>8);
            changed++;
        }
    }
    return changed;
}

/* A deliberate display-only 2x scale: enlarge 160x160 classics to 320x320
 * without storing duplicated source sprites in SPIFFS. This is nearest-
 * neighbor by design; high-quality resampling is a separate visual choice.
 * All edges are bounded before pixel writes. The screen remains square.
 */
int dfsp_blit_rgb565a8_square_2x(const uint8_t *src, uint16_t width, uint16_t height,
    uint8_t *dst, uint16_t dst_width, uint16_t dst_height, int x, int y)
{
    if (!src || !dst || !width || !height || !dst_width || !dst_height ||
        width > 240 || height > 240 || dst_width > 480 || dst_height > 480)
        return -1;
    int changed=0;
    for (unsigned sy=0;sy<(unsigned)height*2u;sy++) {
        const int py=y+(int)sy;
        if (py<0 || py>=dst_height) continue;
        for (unsigned sx=0;sx<(unsigned)width*2u;sx++) {
            const int px=x+(int)sx;
            if (px<0 || px>=dst_width) continue;
            const size_t si=((size_t)(sy/2u)*width+(sx/2u))*3u;
            const unsigned alpha=src[si+2u];
            if (!alpha) continue;
            unsigned fore=(unsigned)src[si]|((unsigned)src[si+1u]<<8);
            const size_t di=((size_t)py*dst_width+(unsigned)px)*2u;
            if (alpha!=255u) {
                const unsigned back=(unsigned)dst[di]|((unsigned)dst[di+1u]<<8);
                const unsigned r5=mix((fore>>11)&31u,(back>>11)&31u,alpha);
                const unsigned g6=mix((fore>>5)&63u,(back>>5)&63u,alpha);
                const unsigned b5=mix(fore&31u,back&31u,alpha);
                fore=(r5<<11)|(g6<<5)|b5;
            }
            dst[di]=(uint8_t)fore;
            dst[di+1u]=(uint8_t)(fore>>8);
            changed++;
        }
    }
    return changed;
}
