# Pinky 手机操作与 macOS Computer Use

Pinky 提供手机操作能力，Computer Use / CUA 负责 Mac 桌面操作。两者通过大肥鱼的 DSH Agent 调用，分别完成安装、授权和功能验证。

[Mac 安装](INSTALL_MAC.md) · [Pinky 官方仓库](https://github.com/DIYgod/pinky) · [DSH Computer Use](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/computer-use.zh.md)

## 一、安装 Pinky

### 1. 安装 Mac App 和 CLI

```bash
brew install --cask diygod/tap/pinky
open -a Pinky
pinkyctl version
```

也可从 [Pinky 官方 Releases](https://github.com/DIYgod/pinky/releases) 获取 Mac ARM64 安装包。

### 2. 连接手机

打开 Pinky，选择 **Add phone（添加手机）**，按系统版本完成配对：

| 手机 | 接入方式 |
|---|---|
| iPhone（iOS 27 及以上） | 按 Pinky 向导连接与授权 |
| iPhone（iOS 17.4–26） | Xcode、Apple ID 签名及按向导安装辅助组件 |
| Android 10–17 | USB 调试、数据线及手机端辅助组件 |

连接状态：

```bash
pinkyctl devices
```

需要安装 iPhone 辅助程序时，按 Pinky 提示执行：

```bash
pinkyctl helper install
```

### 3. 接入大肥鱼 DSH

完成 [Mac Host 安装](INSTALL_MAC.md) 后，私有 Profile 内已有 `mcp-pinky-dafeiyu` 的 MCP 配置。Pinky 默认通过 `pinkyctl mcp` 提供 stdio MCP 服务；项目代理脚本 `scripts/pinky_mcp_named_proxy.py` 负责识别客户端名称并转发工具通信。

当 `pinkyctl` 不在默认路径，可设置：

```bash
export DAFEIYU_PINKYCTL="$(command -v pinkyctl)"
python3.12 -m scripts.check_dependencies --stage pinky --strict
```

成功时 `pinkyctl_executable=true`、`pinky_app_installed=true`。在 DSH 界面确认 MCP 已连接，再执行一次读取设备信息或当前前台应用的测试。

## 二、配置 Mac Computer Use / CUA

### 1. 检查 DSH 插件

安装 Host 时，锁文件包含兼容的 `@deepseek-ai/dsh-computer-use` 和 `@deepseek-ai/dsh-experimental-cua-macos`。

```bash
export DAFEIYU_HOME="$HOME/Library/Application Support/Deepseek-live/my-companion"

test -f "$DAFEIYU_HOME/profiles/web/node_modules/@deepseek-ai/dsh-computer-use/package.json"
test -f "$DAFEIYU_HOME/profiles/web/node_modules/@deepseek-ai/dsh-experimental-cua-macos/package.json"
python3.12 -m scripts.install_host doctor --dsh-home "$DAFEIYU_HOME"
```

### 2. 准备原生 Helper

根据 [macOS CUA 官方说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/experimental/cua-macos/README.zh.md) 和 [native Helper 文档](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/experimental/cua-macos/native/README.md)，使用与已安装插件版本匹配的 Helper。

首次创建 DSH Profile 时，可指定 Helper 的本机绝对路径：

```bash
python3.12 -m scripts.install_host prepare \
  --dsh-home "$DAFEIYU_HOME" \
  --python "$(command -v python3.12)" \
  --computer-helper "/path/to/dsh-cua-native" \
  --initialize-secrets
```

这段 `prepare` 用于新目录；已经初始化的 Host 可按 DSH 官方方式更新 Helper 路径。

### 3. 授予 macOS 权限

在 **系统设置 → 隐私与安全性** 中为实际执行操作的 Helper 开启：

- 辅助功能（Accessibility）
- 屏幕与系统录制（Screen Recording）

检查 Helper：

```bash
export DAFEIYU_CUA_HELPER="/path/to/dsh-cua-native"
python3.12 -m scripts.check_dependencies --stage cua --strict
```

随后在 DSH 中查询前台应用、窗口信息，核对 Helper 返回的实际结果。

## 三、完成验收

| 能力 | 验收方式 |
|---|---|
| Pinky 安装 | `pinkyctl version` |
| 手机连接 | `pinkyctl devices` 与 Pinky 界面 |
| 手机 MCP | DSH 中的 `mcp-pinky-dafeiyu` 与实际工具回执 |
| Computer Use | 原生 Helper、辅助功能、录屏权限 |
| 电脑操作 | 真实窗口识别和实际任务执行结果 |

手机和电脑的操作权限由对应系统与工具界面管理。

[返回 README](../README.md) · [故障排查](TROUBLESHOOTING.md)
