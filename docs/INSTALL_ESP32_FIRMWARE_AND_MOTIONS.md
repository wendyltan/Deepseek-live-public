# ESP32 固件与 106 段动画：从源码部署

适用硬件：Waveshare ESP32-S3-Touch-AMOLED-2.16，16 MB Flash、8 MB PSRAM、480×480 AMOLED，外插 exFAT microSD。此文档把固件源码、第三方 ESP-IDF 组件、内嵌提示音、106 段动作与刷机流程分开说明。

[返回 README](../README.md) · [硬件与 microSD](HARDWARE_AND_MICROSD.md) · [动画来源](ANIMATION_RIGHTS_REGISTER.md)

## 一、安装 ESP-IDF 工具链

固件开发参考版本为 **ESP-IDF 5.5.5**。在 Mac 创建独立的开发工具目录：

```bash
brew install git cmake ninja ffmpeg python@3.12
mkdir -p "$HOME/Development"
git clone --depth 1 --branch v5.5.5 \
  https://github.com/espressif/esp-idf.git \
  "$HOME/Development/esp-idf"
cd "$HOME/Development/esp-idf"
git submodule update --init --recursive
./install.sh esp32s3
. ./export.sh
idf.py --version
```

每次新开终端需要重新执行 `. "$HOME/Development/esp-idf/export.sh"`。

官方工具链：[ESP-IDF ESP32-S3 安装说明](https://docs.espressif.com/projects/esp-idf/en/v5.5.5/esp32s3/get-started/index.html)，[Component Manager](https://docs.espressif.com/projects/esp-idf/en/v5.5.5/esp32s3/api-guides/tools/idf-component-manager.html)。

## 二、公开固件源码构建

公开源码包包含 `firmware/esp32/unified-wifi-wake/`，已去除作者电脑绝对符号链接，改用 `main/idf_component.yml` 的固定组件版本。固件包含三个**原创默认构建资源**：`ANIM.DFS` 几何提示动画、`VOICE.WAV` 与 `R185_GREETING.WAV` 合成提示音；它们不包含作者现役私有声音或第三方角色动画。

```bash
. "$HOME/Development/esp-idf/export.sh"
cd firmware/esp32/unified-wifi-wake
idf.py set-target esp32s3
idf.py reconfigure
idf.py build
```

Component Manager 解析 ESP-SR、微雪 BSP、LVGL 等并生成当前安装的 `dependencies.lock`。如需从头生成三个默认资源，可在项目根目录输出到一个新目录：

```bash
python3.12 -m scripts.generate_firmware_assets   --destination "$HOME/Development/dafeiyu-default-assets"
```

使用个人合法的自定义声音与第三方动画时，按各素材许可替换相应文件。Qwen3-TTS 的已授权 R503 参考声音另见 [语音来源](VOICE_PROVENANCE.md)。尚无新设备的独立编译或刷机验证记录。

## 五、取得并转换 106 段动画

上游来源：<https://github.com/PC2005-cloud/dsh-pet>，锁定提交 `c696095c5786e0eeb25fec0f37a9cdcf30059151`。

角色与动画采用 **CC BY-NC-SA 4.0**（署名、非商业、相同方式共享），与本项目自有代码 MIT 分开。原作者与角色设计署名、改编声明见 [动画权属台账](ANIMATION_RIGHTS_REGISTER.md)。

先按上游仓库的素材获取说明取得 106 段 WebM，放入一个目录。文件可使用上游原名（如 `待机呼吸休闲.webm`）或 `m000.webm` 至 `m105.webm`。

安装处理工具：

```bash
brew install ffmpeg
python3.12 -m venv "$HOME/Development/dafeiyu-motion-venv"
"$HOME/Development/dafeiyu-motion-venv/bin/python" -m pip install \
  "Pillow==11.3.0"
```

在本项目源码根目录进行所有上游 WebM 的 **Git blob SHA-1** 校验：

```bash
"$HOME/Development/dafeiyu-motion-venv/bin/python" \
  -m scripts.build_motion_library \
  --source-dir "/path/to/authorized-upstream-webms"
```

显示 `all106_verified=true` 后才进入转换：

```bash
"$HOME/Development/dafeiyu-motion-venv/bin/python" \
  -m scripts.build_motion_library --mode stage \
  --source-dir "/path/to/authorized-upstream-webms" \
  --destination "$PWD/app/runtime/portable-esp32-candidate/sd-motion-library" \
  --compare-reference
```

转换会生成 `DAFEIYU/MOTIONS/M000.DFS` 至 `M105.DFS`，格式 **240×240、8 FPS、RGB565+Alpha、zlib key/delta**。它逐项验证编码后的文件、校验帧数并与 [106 段正式 SHA-256 清单](../release-assets/animation/dfsp-hashes.json)比较。完整数据约 **285 MiB**。

如需同时为 **Mac 桌面悬浮窗（`496×496` 动态角色播放）** 和 **Mac 管理中心动作库（106 张缩略图）** 导出本机预览资产，可从已校验的 `DAFEIYU/MOTIONS` 目录一键生成：

```bash
"$HOME/Development/dafeiyu-motion-venv/bin/python" \
  -m scripts.build_motion_library --mode mac-assets \
  --source-dir "$PWD/app/runtime/portable-esp32-candidate/sd-motion-library/DAFEIYU/MOTIONS" \
  --previews-dir "$HOME/Library/Application Support/Deepseek-live/motion-previews-jpg" \
  --gifs-dir "$HOME/Library/Application Support/Deepseek-live/companion-native/motions-light-r32"
```

导出的 `M000.gif`..`M105.gif` 会被 Mac 桌宠悬浮窗与管理中心概览页直接加载播放；`m000.jpg`..`m105.jpg` 可在运行 `zsh scripts/build_mac_app.sh build ... --motion-previews "$HOME/Library/Application Support/Deepseek-live/motion-previews-jpg"` 时打包进 `.app`。

## 六、安装外置 microSD 并验收

将 exFAT microSD 插入读卡器，准备以下目录：

```text
/DAFEIYU/
├── MOTIONS/
│   ├── M000.DFS
│   ├── M001.DFS
│   └── ... M105.DFS
└── USER/
    └── (可扩展自制动作)
```

拷贝转换目录的 `DAFEIYU/MOTIONS/` 到 SD 卡，读回比较 `MOTION_CHECKSUMS.json` 中的 SHA-256。项目提供无需写卡权限的只读验收器：

```bash
python3.12 -m scripts.verify_motion_library \
  --motions-dir "/Volumes/YOUR_SD/DAFEIYU/MOTIONS" \
  --strict
```

`verified=106`、`complete=true` 表示所有内容与项目权威哈希一致。脚本只读取目录，校验失败返回 2；之后安全弹出、装卡冷启动，再进行 SDMMC/exFAT 挂载、动画播放、显示方向与任务状态联动的实机测试。

**提示：** DFSP 转换、固件编译、串口烧录与 SD 卡写入是四个独立步骤，按顺序执行即可完成全套硬件端部署与 106 段动画联调。
