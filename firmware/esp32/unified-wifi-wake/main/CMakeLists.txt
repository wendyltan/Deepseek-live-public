idf_component_register(SRCS "r268_lan_pcm_wire.c" "r268_lan_transport.c" "r224_media_owner.c" "r226_sd_wake_cache.c" "r225_voice_upload.c" "r185_wakenet9.c" "r259_offline_multinet.c" "r224_offline_voice.c" "r224_sd_voice_player.c" "r150_rules.c" "r133_features.c" "main.c" "r62_wifi.c" "r83_user_sd.c" "lv_font_r57_cn_16.c" "lv_font_r57_cn_20.c" "lv_font_r487_cn_18.c" "lv_font_r487_cn_23.c" "lv_font_r487_cn_30.c" "dfsp_decoder.c" "dfsp_blit.c" "dfsp_stage.c"
    "exfat_ro_animation.c" "h12_sd_motion.c" "h13_sd_usb.c"
  INCLUDE_DIRS "."
  REQUIRES esp_app_format esp-sr esp_timer esp_wifi esp_netif esp_event nvs_flash spi_flash fatfs esp_driver_i2s esp_driver_sdmmc sdmmc esp_driver_usb_serial_jtag mbedtls esp_rom tcp_transport json espressif__esp_lvgl_adapter
  EMBED_FILES "assets/ANIM.DFS" "assets/VOICE.WAV" "assets/R185_GREETING.WAV")
target_compile_definitions(${COMPONENT_LIB} PRIVATE
 DF_H11_PREVIEW_STATES=1 DF_H12_SD_ANIM=1 DF_H12_HASH_VERIFY=1 DF_H13_SD_UPLOAD=1 DF_H28_HOLD_MIC=1 DF_R30_TOGGLE_MIC=1 DF_R33_BOARD_UI=1 DF_R46_PCM2_ONLY=1 DF_R47_PCM2_DIAGNOSTIC=1 DF_R103_USER_SD=1 DF_R150_ALL106=1 DF_R185_WN9=1 DF_R225_LOCAL_OFFLINE=1 DF_R327_MN5_DIRECT=1 DF_UNIFIED_MN5_ONLY=1 DF_R434_MAC_PREWAKE_ONLY=1 DF_R340_AFE_MN5=1 DF_R341_AFE_DUALCORE=1 DF_R344_AFE_PROFILE=1 DF_R387_AFE_FETCH_PROFILE=1)

# Native target-frame proof for the two stack-heavy exFAT functions.
set_source_files_properties(r226_sd_wake_cache.c r224_sd_voice_player.c r224_media_owner.c r185_wakenet9.c main.c PROPERTIES COMPILE_OPTIONS "-fstack-usage")
