# Deepseek-live · ESP32-S3 Unified Wi-Fi & Wake-Word Firmware

This directory contains the canonical ESP-IDF application source for the **Waveshare ESP32-S3-Touch-AMOLED-2.16** desktop companion (`大肥鱼`), including:

- **Audio & Wake-Word**: Dual-microphone capture (ES7210), ESP-SR wake-word detection (`ni hao da fei yu`), speaker playback (ES8311) with 16-level mouth opening envelope, and listening waveform display.
- **Display & Touch**: 480 × 480 AMOLED LVGL UI, capacitive touch interactions, and software LVGL screenshot diagnostics (`@@DFSCREEN2`).
- **Storage & Motions**: SDMMC 1-bit exFAT reader (`main/h12_sd_motion.c`) for 106 DFSP animations under `/DAFEIYU/MOTIONS/`, plus embedded emergency fallback animation (`main/assets/ANIM.DFS`) and chimes (`main/assets/VOICE.WAV`, `main/assets/R185_GREETING.WAV`).
- **Connectivity**: Paired TLS/WSS Wi-Fi voice streaming (`@@DFLAN2`) and USB Serial/JTAG PCM protocol (`@@DFPCM1`).

## Build & Deployment Guides

- [ESP32 Hardware & microSD Layout](../../../docs/HARDWARE_AND_MICROSD.md)
- [ESP32 Firmware & 106 Motions Build Guide](../../../docs/INSTALL_ESP32_FIRMWARE_AND_MOTIONS.md)
- [ESP32 First-Time Setup & Flashing](../../../docs/FIRST_BOOT_ESP32.md)
- [Wi-Fi Voice Gateway & Device Pairing](../../../docs/INSTALL_VOICE_GATEWAY.md)
