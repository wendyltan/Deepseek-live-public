#pragma once
#include <stdbool.h>
#include <stdint.h>
typedef struct {
    bool ready,scanning,connecting,connected,has_ip,saved,needs_setup;
    int count,signal[8],error;
    uint8_t diagnostic_stage; int diagnostic_esp_error;
    uint8_t persistence_stage; // 0 none, 1 joining, 2 DHCP save pending, 3 NVS committed, 4 failed
    bool station_config_loaded; // driver-reported station config present after cold boot
    uint32_t persistence_generation; // non-sensitive monotonic NVS receipt
    uint32_t diagnostic_dma_largest,diagnostic_internal_largest;
    uint32_t diagnostic_dma_min,diagnostic_internal_min;
    uint8_t diagnostic_min_stage;
    char ssid[8][33],current[33],ip[20];
} r62_wifi_state_t;
void r62_wifi_begin(void);
bool r62_wifi_scan(void);
bool r62_wifi_connect(const char *ssid,const char *password);
bool r62_wifi_forget(void);
void r62_wifi_snapshot(r62_wifi_state_t *state);
