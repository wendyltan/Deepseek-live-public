# 使用 Codex、Claude Code 等 Agent 部署大肥鱼

将下方任务书复制给可访问目标 Mac 终端的编程 Agent。Agent 先检查已有环境，再安装缺失组件，并按照各模块实际输出逐项验收。

[Mac 安装](INSTALL_MAC.md) · [Whisper](INSTALL_WHISPER_CPP.md) · [Qwen3-TTS](INSTALL_QWEN3_TTS.md) · [Pinky/CUA](INSTALL_PINKY_CUA.md) · [ESP32 与 SD](HARDWARE_AND_MICROSD.md)

## 中文任务书

```text
你是 Deepseek-live（大肥鱼）的部署工程师。请在当前 Apple Silicon Mac
上检查和安装项目所需的运行环境，并提供可复现的验收结果。

首先在项目根目录阅读：
- README.md、docs/INSTALL_MAC.md
- docs/INSTALL_WHISPER_CPP.md、docs/INSTALL_QWEN3_TTS.md
- docs/INSTALL_PINKY_CUA.md、docs/INSTALL_VOICE_GATEWAY.md
- docs/HARDWARE_AND_MICROSD.md
- docs/FIRST_BOOT_ESP32.md、docs/INSTALL_ESP32_FIRMWARE_AND_MOTIONS.md
- docs/VOICE_PROVENANCE.md

执行计划：
1. 环境调查：识别 macOS、Apple Silicon 芯片、磁盘空间、Homebrew、
   Python 3.12、Node、pnpm、FFmpeg、CMake、Xcode Command Line Tools
   和现有服务端口，列出可复用的现成组件。
2. 安装 Host：使用 python3.12 -m scripts.install_host 的
   plan / prepare / deps / doctor，创建新的私有 DSH_HOME；
   按输出验证 can_prepare、lock_unchanged、core_rows_verified 和
   ready_for_host_only_configuration_smoke。
3. 配置语音识别：安装 whisper.cpp、多语言 small 模型、Silero VAD
   与 FFmpeg，运行本地文件识别及
   python3.12 -m scripts.check_dependencies --stage asr --strict。
4. 配置声音：安装 MLX Audio、Qwen3-TTS 0.6B 8-bit；
   默认参考音为 release-assets/voice/r503-reference.wav，
   对应文本为 release-assets/voice/r503-reference.txt。
   在独立端口 8908 启动 python3.12 -m scripts.serve_tts，
   检查 /health ready=true 和一次真实流式合成。
5. 配置手机：按 Pinky 官方文档安装应用并连接设备，
   运行 pinkyctl version 和 pinkyctl devices；
   在本项目 DSH 中检查 mcp-pinky-dafeiyu 注册及真实工具回执。
6. 配置电脑操作：核对 Computer Use/CUA 插件、原生 Helper
   与 macOS 辅助功能/录屏授权，进行只读窗口识别测试。
7. Mac App：运行 zsh scripts/build_mac_app.sh check；
   然后用 build 子命令将应用输出到一个新 .app 文件路径，
   打开界面检查设备、会话、插件和诊断页面。
8. ESP32：按硬件与 SD 指南核对板型、Flash、PSRAM、屏幕、音频、
   外置 microSD 的 exFAT 文件系统与素材目录。
   使用 python3.12 -m scripts.install_host device-plan 检查首次刷机条件，
   完成硬件确认后再进行固件构建、烧录和设备配对。

执行规则：
- 每一步记录具体命令、安装位置、版本和成功/失败输出。
- 复用正常的现有服务；如需覆盖已存在的应用或配置，先取得确认。
- 大模型下载、系统授权、手机实际操作和 ESP32 烧录前说明影响范围。
- 不将 API 密钥、手机凭证、私人会话、研究缓存加入 Git。
- 最终分别报告“依赖安装”“服务就绪”“端到端功能”三个状态，
  对未完成项标记 BLOCKED 并写出下一步。
```

## English prompt

```text
You are the deployment engineer for Deepseek-live (Dafeiyu).
Inspect the target Apple Silicon Mac and install the application in stages.
Read README.md and the installation guides under docs/ first.

1. Inspect macOS, disk space, Homebrew, Python 3.12, Node, pnpm,
   FFmpeg, CMake, Xcode tools and existing listeners.
2. Install an isolated DSH Host using
   python3.12 -m scripts.install_host plan/prepare/deps/doctor.
   Record can_prepare, lock_unchanged, core_rows_verified and Host readiness.
3. Install whisper.cpp multilingual small and Silero VAD, then verify
   local audio transcription and scripts.check_dependencies --stage asr.
4. Install MLX Audio and Qwen3-TTS 0.6B 8-bit. Select the shipped R503
   reference WAV and text under release-assets/voice, then start
   python3.12 -m scripts.serve_tts on a free test port (8908).
   Validate /health and /stream with a real synthesis.
5. Install the official Pinky app, connect the user's phone and verify
   pinkyctl devices and the DSH MCP tool results.
6. Set up native macOS Computer Use/CUA helper and required permissions,
   then verify read-only application/window discovery.
7. Check and build the Mac app with zsh scripts/build_mac_app.sh.
8. Inspect the Waveshare ESP32-S3-Touch-AMOLED-2.16 and exFAT microSD,
   run python3.12 -m scripts.install_host device-plan,
   then build, flash and pair the device after user approval.

For each stage, record commands, installed versions, file locations,
test output and the next action. Distinguish dependency, running service
and end-to-end status. Confirm before changing an existing installation,
modifying system permissions, operating a phone or flashing firmware.
Keep user credentials, sessions and local research files out of Git.
```

## 交付验收表

| 模块 | 依赖安装 | 服务运行 | 功能验收 |
|---|---|---|---|
| DSH Host | CLI / 锁文件 | Web 管理页 | 对话 |
| Whisper | CLI / small / VAD | 语音调用 | 中文转写 |
| Qwen3-TTS | MLX / 模型 / WAV | `/health` | 流式语音 |
| Pinky | 应用 / CLI | 手机连接 | MCP 工具 |
| Computer Use | 插件 / Helper | 系统授权 | 窗口识别 |
| Mac App | Swift 构建 | App 启动 | 管理页面 |
| ESP32 | 固件 / microSD | USB / Wi-Fi | 板麦、动作、播音 |
