// SPDX-License-Identifier: MIT
#include "usb_control.h"
#include <stdio.h>
#include "driver/usb_serial_jtag.h"
#include "freertos/FreeRTOS.h"
#include "mbedtls/base64.h"

// The driver sends each complete base64 line as one atomic ring-buffer
// operation; ordinary ESP_LOGs (also routed via USB-JTAG VFS driver) can
// appear between frames but never truncate a PCM payload mid-line.
// Return false on a real backpressure/connection failure, rather than
// pretending that 150 audio chunks were sent successfully.
#define H9_USB_TX_MAX 1100
bool h9_send_line(const char *line, size_t n){
    if(n==0 || n>H9_USB_TX_MAX || !usb_serial_jtag_is_driver_installed())
        return false;
    return usb_serial_jtag_write_bytes(line,n,pdMS_TO_TICKS(2200))==(int)n;
}
bool h9_send_audio_frame(unsigned i, const int16_t *samples, bool diagnostic,size_t sample_count){
    unsigned char b64[1024]={0};
    size_t n64=0;
    if(mbedtls_base64_encode(b64,sizeof(b64),&n64,
          (const unsigned char *)samples,sample_count*2u)!=0)
        return false;
    char line[H9_USB_TX_MAX+1];
    int n=snprintf(line,sizeof(line),"@@DFVOICE1 %s %u %s\n",
                   diagnostic?"TESTPCM":"PCM",i,b64);
    return n>0 && n<=H9_USB_TX_MAX && h9_send_line(line,(size_t)n);
}
#ifdef DF_H28_HOLD_MIC
bool h28_send_mic_frame(unsigned i,const int16_t *samples,size_t sample_count){
    unsigned char encoded[1024]={0};size_t length=0;
    if(mbedtls_base64_encode(encoded,sizeof(encoded),&length,
            (const unsigned char*)samples,sample_count*2u)!=0)return false;
    char line[H9_USB_TX_MAX+1];
    int n=snprintf(line,sizeof(line),"@@DFVOICE3 PCM %u %s\n",i,encoded);
    return n>0&&n<=H9_USB_TX_MAX&&h9_send_line(line,(size_t)n);
}
#endif
