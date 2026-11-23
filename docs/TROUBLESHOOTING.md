# 故障排查

先按模块检查，再结合真实运行日志定位问题。

[Mac 安装](INSTALL_MAC.md) · [Whisper](INSTALL_WHISPER_CPP.md) · [Qwen3-TTS](INSTALL_QWEN3_TTS.md) · [Pinky / CUA](INSTALL_PINKY_CUA.md) · [ESP32](FIRST_BOOT_ESP32.md)

## 快速检查

```bash
python3.12 -m scripts.check_dependencies --stage all
python3.12 -m scripts.install_host doctor --dsh-home "$DAFEIYU_HOME"
python3.12 -m scripts.install_host device-plan
```

`DAFEIYU_HOME` 为安装 DSH 时设置的目录；重新打开终端后可按 [Mac 安装指南](INSTALL_MAC.md)再次设置。

## 常见问题

| 现象 | 优先检查 |
|---|---|
| `plan` 返回 `can_prepare=false` | Mac 架构、Python 3.12、目标目录是否已存在 |
| `deps` 返回 `pnpm_install_failed` | Node/pnpm 版本、网络、上游包仓库和锁文件 |
| `doctor` 返回未就绪 | 输出 `checks` 中的具体缺项；手机与 CUA 按模块分别安装 |
| Web 管理页无法连接 | DSH 进程、端口 3080 的监听状态 |
| Web 能打开但无法对话 | Provider 登录、模型配置、Session 和网络 |
| Mac App 无法读取设备 | 本地 Host、语音网关、USB/Wi-Fi 连接及权限 |
| 手机无法操作 | `pinkyctl devices`、MCP 连接、原生工具执行日志 |
| Mac 窗口无法识别 | CUA Helper、macOS 辅助功能和屏幕录制权限 |
| Whisper 无识别结果 | 录音格式、FFmpeg、small 模型、Silero VAD |
| TTS 音量异常或吞字 | 模型预热、流式事件、参考音与 PCM 播放链 |
| USB 接入后 Wi-Fi 网关停止监听 | 当前单通道传输状态与 USB 连接 |
| ESP32 动画缺失 | SDMMC 挂载、exFAT、资源路径、文件完整性 |
| ESP32 断连 | Wi-Fi/TLS 配对、USB 所有者切换、供电与网关日志 |

## 验收顺序

| 层级 | 证据 |
|---|---|
| 安装与配置 | 脚本、依赖锁文件、CLI、模型文件、配置检查 |
| 服务运行 | DSH Web、TTS `/health`、Pinky 设备列表、Mac App 启动 |
| 功能联调 | Whisper 中文转写、TTS 流式播音、工具实际返回 |
| 实体设备 | ESP32 板麦、显示、扬声器、microSD、USB/Wi-Fi 切换 |

[完整部署任务书](AGENT_INSTALL_PROMPT.md)提供逐阶段安装与验收报告格式。
