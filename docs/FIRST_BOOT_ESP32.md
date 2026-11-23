# ESP32 首次部署

适用开发板：**Waveshare ESP32-S3-Touch-AMOLED-2.16**，480 × 480 触控 AMOLED，16 MB Flash、8 MB PSRAM。动画和用户素材可放在另外插入的 exFAT microSD 卡上。

[硬件与 microSD](HARDWARE_AND_MICROSD.md) · [固件与 106 动作可复现构建](INSTALL_ESP32_FIRMWARE_AND_MOTIONS.md) · [Mac 安装](INSTALL_MAC.md) · [架构说明](ARCHITECTURE.md)

## 1. 检查硬件

确认板型、屏幕、音频接口、Flash/PSRAM 容量及 USB 数据线。首次使用外置 microSD 时，按 [SD 卡指南](HARDWARE_AND_MICROSD.md)准备文件系统和素材目录。

在源码根目录查看固件工程：

```bash
python3.12 -m scripts.install_host device-plan
```

固件工程位于 `firmware/esp32/unified-wifi-wake/`，包含 `sdkconfig.defaults`、`dependencies.reference.lock`（或本机 ESP-IDF 生成的 `dependencies.lock`）、`partitions.csv` 和各模块源文件。

## 2. 准备 ESP-IDF 构建环境

按照 [Espressif ESP-IDF 安装文档](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/get-started/index.html)安装工具链，并核对项目组件及锁文件版本。

```bash
idf.py --version
cd firmware/esp32/unified-wifi-wake
idf.py set-target esp32s3
idf.py build
# 编译完成后连接 USB 串口烧录并查看日志（将 <port> 替换为实际设备端口，如 /dev/cu.usbmodem*）
idf.py -p <port> flash monitor
```

构建时，ESP-IDF Component Manager 会自动根据 `idf_component.yml` 与 `dependencies.lock` 拉取所需的微雪板级驱动、ESP-SR 与 LVGL 组件。

检查编译成功后的分区大小、Flash/PSRAM 配置及镜像大小。

## 3. 备份、烧录与配对

1. 将开发板接入 Mac，确认串口设备和芯片信息。
2. 对已有用户数据的设备，备份 NVS、用户分区及原固件镜像。
3. 确认串口和写入分区后，通过 ESP-IDF 工具烧录本次构建的镜像。
4. 读回并校验写入结果，再连接 DSH Host。
5. 依次验证 USB 语音、Wi-Fi 配对、板麦录音、扬声器、屏幕、触控和 microSD 动画。

## 4. 验收清单

| 模块 | 验收内容 |
|---|---|
| 设备硬件 | 板型、Flash/PSRAM、显示和触控 |
| 本地存储 | exFAT 挂载、目录、资源读取、冷启动 |
| 语音 | 板麦转写、短句/长句播音、打断 |
| 联网 | Wi-Fi 连接、TLS、断线重连、USB/Wi-Fi 切换 |
| 动画 | 资源路径、动作播放和任务状态联动 |
| 设备更新 | 固件读回校验及用户数据保留 |

完整硬件选型和 SDMMC 连接信息见 [硬件说明](HARDWARE_AND_MICROSD.md)。
