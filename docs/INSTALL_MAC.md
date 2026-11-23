# Mac 安装指南

在 Apple Silicon Mac 上安装 DSH Host、构建大肥鱼管理 App，并按需要接入本地语音和手机工具。

## 1. 系统环境

| 组件 | 要求 |
|---|---|
| macOS | Apple Silicon，macOS 14 或更高 |
| Python | 3.12 |
| Node.js / pnpm | Node.js、pnpm 10 |
| 开发工具 | Git、Xcode Command Line Tools、Homebrew |

安装基础工具：

```bash
brew install git python@3.12 node pnpm
xcode-select -p
python3.12 --version
node --version
pnpm --version
```

如果 `xcode-select -p` 提示未安装，执行 `xcode-select --install` 完成 macOS 开发工具安装。

## 2. 安装 DSH Host

进入项目源码根目录，创建独立的应用数据目录：

```bash
mkdir -p "$HOME/Library/Application Support/Deepseek-live"
export DAFEIYU_HOME="$HOME/Library/Application Support/Deepseek-live/my-companion"

python3.12 -m scripts.install_host plan --dsh-home "$DAFEIYU_HOME"
```

`can_prepare=true` 表示目录及安装条件符合要求。随后初始化 Host：

```bash
python3.12 -m scripts.install_host prepare \
  --dsh-home "$DAFEIYU_HOME" \
  --python "$(command -v python3.12)" \
  --initialize-secrets
```

安装与项目锁文件匹配的 DSH、Live Bridge 及相关插件：

```bash
python3.12 -m scripts.install_host deps \
  --dsh-home "$DAFEIYU_HOME" --network --confirm-network
```

依赖安装成功时，输出包括 `ready_for_configuration_smoke=true`、`lock_unchanged=true` 和 `core_rows_verified=true`。离线缓存已经准备好的环境也可以省略 `--network --confirm-network`。

检查配置：

```bash
python3.12 -m scripts.install_host doctor --dsh-home "$DAFEIYU_HOME"

DSH_HOME="$DAFEIYU_HOME" node \
  "$DAFEIYU_HOME/profiles/web/node_modules/@deepseek-ai/dsh/lib/bin.js" \
  --profile web --dump-config > "$DAFEIYU_HOME/effective-config.yml"
```

`ready_for_host_only_configuration_smoke=true` 代表 Host 基础组件已经齐备。手机工具和 Mac 电脑控制的依赖分别在各自的安装阶段检查。

### 启动 DSH

```bash
DSH_HOME="$DAFEIYU_HOME" node \
  "$DAFEIYU_HOME/profiles/web/node_modules/@deepseek-ai/dsh/lib/bin.js" \
  --profile web --no-open --host 127.0.0.1 --port 3080
```

浏览器打开 **http://127.0.0.1:3080**，按 DSH 页面完成模型 Provider 配置、登录及对话测试。保持该终端运行。

## 3. 构建 Mac 管理 App

在项目源码根目录运行：

```bash
zsh scripts/build_mac_app.sh check
zsh scripts/build_mac_app.sh build "$HOME/Downloads/大肥鱼-源码构建.app"
open "$HOME/Downloads/大肥鱼-源码构建.app"
```

`check` 检查 Swift 代码；`build` 将 Swift 源码编译为 macOS App，写入图标与动作目录，并进行本地代码签名。输出为 `MAC_APP_BUILD_PASS`。App 的会话、插件及设备页面通过本机 Host 和网关访问实际状态。

**构建路径由你指定**：当已有同名 App 时，更换输出文件名即可保留旧版本。管理 App 的功能页包括设备状态、会话、长期记忆、动作库、插件和诊断。

### 完整动作缩略图与桌宠动态 GIF

Mac 管理 App 包含两种角色动画视图：
1. **桌面四方悬浮窗（`496×496` 桌宠）与管理中心概览页动态预览**：从 `~/Library/Application Support/Deepseek-live/companion-native/motions-light-r32/` 读取 `M000.gif` 至 `M105.gif`（`240×240`、8 FPS）。
2. **动作库分类网格**：使用打包在 App 内部的 106 张 `m000.jpg` 至 `m105.jpg` 缩略图。

在按 [ESP32 固件与 106 动画指南](INSTALL_ESP32_FIRMWARE_AND_MOTIONS.md) 转换出 106 个 `M000.DFS`..`M105.DFS` 后，可一键导出这两套 Mac 本地预览素材并打包进 App：

```bash
"$HOME/Development/dafeiyu-motion-venv/bin/python" \
  -m scripts.build_motion_library --mode mac-assets \
  --source-dir "$PWD/app/runtime/portable-esp32-candidate/sd-motion-library/DAFEIYU/MOTIONS" \
  --previews-dir "$HOME/Library/Application Support/Deepseek-live/motion-previews-jpg" \
  --gifs-dir "$HOME/Library/Application Support/Deepseek-live/companion-native/motions-light-r32"

zsh scripts/build_mac_app.sh build "$HOME/Downloads/大肥鱼-含动作预览.app" \
  --motion-previews "$HOME/Library/Application Support/Deepseek-live/motion-previews-jpg"
```

完整资源打包完成会输出 `MAC_APP_RESOURCES_COMPLETE motion_previews=106`。不指定该目录时仍能构建基础管理 App。素材的来源及许可证见 [动画权属台账](ANIMATION_RIGHTS_REGISTER.md)。

## 4. 配置语音、手机与 ESP32

| 组件 | 安装与测试 |
|---|---|
| Whisper 语音识别 | [whisper.cpp、small 模型、Silero VAD 和 FFmpeg](INSTALL_WHISPER_CPP.md) |
| Qwen3-TTS | [MLX Audio、模型权重及参考声音](INSTALL_QWEN3_TTS.md) |
| Wi-Fi 语音网关 | [WSS 配对与启动](INSTALL_VOICE_GATEWAY.md) |
| Pinky / Computer Use | [手机连接、MCP、macOS CUA Helper 和系统权限](INSTALL_PINKY_CUA.md) |
| ESP32 | [硬件与 microSD](HARDWARE_AND_MICROSD.md) · [首次部署](FIRST_BOOT_ESP32.md) |

统一查看本地软件依赖：

```bash
python3.12 -m scripts.check_dependencies --stage all
```

每项也可单独检查：`--stage asr`、`--stage tts`、`--stage pinky`、`--stage cua`；加上 `--strict` 可让缺失依赖时返回非零退出码。

## 5. 常见问题

| 现象 | 处理方式 |
|---|---|
| `can_prepare=false` | 检查 Python 版本、macOS 架构、目标目录是否已存在 |
| `pnpm_install_failed` | 检查网络、pnpm、Node.js 和上游包仓库访问 |
| `lock_unchanged=false` | 对照仓库锁文件及安装日志检查依赖版本 |
| DSH 已启动但无法对话 | 在 Web UI 查看 Provider 登录、模型选择和网络连接 |
| Mac App 无法读取设备状态 | 检查 DSH 及设备网关是否运行、对应端口是否可访问 |
| ESP32 能开机但不说话 | 分别检查板载拾音、Mac Whisper、Qwen3-TTS 与音频回传 |

[完整架构](ARCHITECTURE.md) · [更详细的故障定位](TROUBLESHOOTING.md) · [交给 Codex / Claude 协助部署](AGENT_INSTALL_PROMPT.md)
