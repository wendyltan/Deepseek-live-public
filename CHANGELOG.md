# 更新日志

记录大肥鱼面向使用者的主要功能变化。源码版本和发布标签以 Git 仓库为准。

## 当前开发版本 · 2026 年 11 月

### 语音与交互
- 使用 whisper.cpp 多语言 small 模型进行本地中文语音识别。
- Qwen3-TTS 配合 MLX Audio 实现流式中文合成，附带已获授权的参考音与逐字稿。
- ESP32 支持 USB / Wi-Fi 语音连接、AMOLED 动画、触控与音频播放。

### Mac 管理 App
- 提供设备状态、会话记录、长期记忆、动画管理、插件及诊断页面。
- 插件列表显示真实安装和启用状态，由官方 DSH 插件管理器处理安装、启停与卸载。
- 增加统一的 Swift 源码构建脚本 `scripts/build_mac_app.sh`。

### 安装与开发
- 增加 `scripts/install_host.py`，用于配置独立 DSH Host 和版本锁定依赖。
- 增加 `scripts/check_dependencies.py`，检查 Whisper、TTS、Pinky 和 Computer Use 环境。
- 完善开发板、外置 microSD、Mac Host、TTS、Pinky 和 ESP32 安装指南。
- 提供可交给 Codex、Claude Code 等编程 Agent 的分阶段部署任务书。

### 源码与素材
- 项目自有源码采用 MIT 许可。
- 整理经典角色动画的来源及独立授权说明。
- 登记默认参考音色的原视频来源、许可确认与文件哈希。
- 增加 Git 私有素材过滤、构建检查和公开文档回归测试。

[项目主页](README.md) · [安装指南](docs/INSTALL_MAC.md) · [许可证](LICENSE)
