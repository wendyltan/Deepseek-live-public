# ESP32 开发板与 microSD

大肥鱼使用 **Waveshare ESP32-S3-Touch-AMOLED-2.16**，板载触控屏、麦克风和音频接口；另配 microSD 存放动画与用户素材。

[返回 README](../README.md) · [固件与 106 动作可复现构建](INSTALL_ESP32_FIRMWARE_AND_MOTIONS.md) · [首次部署](FIRST_BOOT_ESP32.md) · [微雪官方资料](https://docs.waveshare.com/ESP32-S3-Touch-AMOLED-2.16)

## 硬件清单

| 部件 | 规格 |
|---|---|
| 主控 | ESP32-S3R8，2.4 GHz Wi-Fi |
| 屏幕 | 2.16 英寸、480×480 AMOLED，触控 |
| 固件与内存 | 16 MB Flash、8 MB PSRAM |
| 音频 | ES7210 双麦克风、ES8311 播音链路及扬声器接口 |
| SD 卡槽 | 开发板自带 TF/microSD 卡槽 |
| 外置 SD 卡 | 参考配置：**64 GB microSD，exFAT** |
| 运行主机 | Apple Silicon Mac |

选择完整型号 **ESP32-S3-Touch-AMOLED-2.16**，即可匹配项目使用的屏幕、触控、音频驱动和引脚配置。

## microSD 作用与连接

64 GB 是参考配置，可根据动画和用户素材数量调整容量。microSD 插在板载 TF 卡槽，通过 **SDMMC 1-bit** 连接：

| 信号 | GPIO |
|---|---|
| CMD | GPIO1 |
| CLK | GPIO2 |
| D0 | GPIO3 |

microSD 用于保存 DFSP 动画帧与用户资源。Whisper、DSH 和 Qwen3-TTS 在 Mac 上运行，ESP32 管理动画、输入和音频回放。

## 文件系统和目录

使用 exFAT 格式，并将资源放在约定目录：

```text
/DAFEIYU/
├── MOTIONS/
│   ├── M000.DFS
│   ├── M001.DFS
│   └── ...
└── USER/
    └── MNNN.DFS
```

`MNNN` 表示三位动作编号，如 `M000.DFS`。实际可用编号与动作由固件资源映射决定。

固件对应的读取实现位于 `firmware/esp32/exfat_ro_animation.c`，SDMMC 初始化与读取逻辑位于 `firmware/esp32/unified-wifi-wake/main/h12_sd_motion.c`。

## 首次装卡

1. 将 microSD 接入 Mac 读卡器，准备 exFAT 文件系统。
2. 建立 `/DAFEIYU/MOTIONS/` 等资源目录，并放入具有使用权限的 DFSP 文件。
3. 安全弹出，断电后插入开发板 TF 卡槽。
4. 启动固件，检查 SDMMC 初始化、exFAT 挂载和动画读取日志。
5. 验证显示、帧播放与重新上电后的资源读取。

动画资源来源和各项许可见 [动画权属台账](ANIMATION_RIGHTS_REGISTER.md)。

## 固件构建

```bash
python3.12 -m scripts.install_host device-plan
```

工程位于 `firmware/esp32/unified-wifi-wake/`，按 `sdkconfig.defaults`、`dependencies.reference.lock`（或本机生成的 `dependencies.lock`）、`partitions.csv` 确定构建配置。公开源码已通过 `main/idf_component.yml` 声明固定版本的 ESP-IDF 组件依赖。

[继续 ESP32 编译、烧录与配对](FIRST_BOOT_ESP32.md)
