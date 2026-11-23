# DSH Host 与多模块部署

大肥鱼在 Mac 上运行独立 DSH Agent，并连接 Whisper、本地 TTS、Pinky、Computer Use 和 ESP32 语音网关。

[返回 README](../README.md) · [完整 Mac 安装](INSTALL_MAC.md) · [系统架构](ARCHITECTURE.md)

## Host 组件

| 组件 | 配置 |
|---|---|
| DSH CLI / Web | `0.2.1-rc.2` |
| Computer Use / macOS CUA | 与 DSH CLI 匹配的 `0.2.1-rc.2` |
| Live Bridge | 仓库中的 `plugins/dsh-live-bridge/` |
| Python | 3.12 |
| pnpm | 10 |

安装脚本使用 `config/locks/` 下的依赖锁文件，生成独立的 DSH Profile 和本地数据目录。

## 安装命令

```bash
mkdir -p "$HOME/Library/Application Support/Deepseek-live"
export DAFEIYU_HOME="$HOME/Library/Application Support/Deepseek-live/my-companion"

python3.12 -m scripts.install_host plan --dsh-home "$DAFEIYU_HOME"
python3.12 -m scripts.install_host prepare \
  --dsh-home "$DAFEIYU_HOME" \
  --python "$(command -v python3.12)" --initialize-secrets
python3.12 -m scripts.install_host deps \
  --dsh-home "$DAFEIYU_HOME" --network --confirm-network
python3.12 -m scripts.install_host doctor --dsh-home "$DAFEIYU_HOME"
```

`plan` 用于环境检查，`prepare` 创建配置，`deps` 安装版本锁定依赖，`doctor` 检查安装状态。详细的 Provider 登录、Web 启动和 Mac App 构建见 [Mac 安装指南](INSTALL_MAC.md)。

## 接入语音与工具

| 模块 | 指引 |
|---|---|
| 语音识别 | [whisper.cpp + Silero VAD](INSTALL_WHISPER_CPP.md) |
| 语音合成 | [Qwen3-TTS + MLX Audio](INSTALL_QWEN3_TTS.md) |
| 手机操作 | [Pinky MCP](INSTALL_PINKY_CUA.md) |
| Mac 操作 | [Computer Use / CUA](INSTALL_PINKY_CUA.md) |
| 设备 | [ESP32 固件、microSD 与配对](FIRST_BOOT_ESP32.md) |

```bash
python3.12 -m scripts.check_dependencies --stage all
```

## 工具与插件管理

在 Mac 管理 App 的 **插件与扩展** 页面查看安装状态，通过 **管理插件** 进入官方 DSH 插件管理器。

[插件说明](PLUGINS.md) · [故障排查](TROUBLESHOOTING.md) · [交给 Agent 部署](AGENT_INSTALL_PROMPT.md)
