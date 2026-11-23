# Wi-Fi 语音网关与 ESP32 配对

大肥鱼 ESP32 通过受信任的 WSS 连接 Mac。网关负责板麦音频、Whisper 转写、DSH 会话和 Qwen3-TTS 播音；客户端必须先与 Mac 配对。

[Mac Host 安装](INSTALL_MAC.md) · [Whisper](INSTALL_WHISPER_CPP.md) · [Qwen3-TTS](INSTALL_QWEN3_TTS.md) · [ESP32 固件](INSTALL_ESP32_FIRMWARE_AND_MOTIONS.md)

## 1. 安装网关运行依赖

在 Mac 项目根目录：

```bash
export DAFEIYU_GATEWAY_VENV="$HOME/Library/Application Support/Deepseek-live/gateway-venv"
python3.12 -m venv "$DAFEIYU_GATEWAY_VENV"
"$DAFEIYU_GATEWAY_VENV/bin/python" -m pip install \
  "websockets==15.0.1" "pyserial==3.5"
export DAFEIYU_PYTHON="$DAFEIYU_GATEWAY_VENV/bin/python"
```

Whisper、TTS 和 DSH 的模型及服务先按各自指南配置；网关需要继承 `DAFEIYU_WHISPER_*` 等识别环境变量。参考声线设置为：

```bash
export DAFEIYU_R503_REFERENCE_AUDIO="$PWD/release-assets/voice/r503-reference.wav"
export DAFEIYU_R503_REFERENCE_TEXT="$(cat release-assets/voice/r503-reference.txt)"
```

### 可选：本地天气和 USB 串口

公开源码不会预设作者的地区。需要使用“当前位置天气”快速回复时，可设置自己城市的名称、坐标及别名；不配置时该本地快捷能力不拦截一般天气查询：

```bash
export DAFEIYU_WEATHER_LOCATION="北京市海淀区"
export DAFEIYU_WEATHER_LATITUDE=39.97
export DAFEIYU_WEATHER_LONGITUDE=116.32
export DAFEIYU_WEATHER_TIMEZONE="Asia/Shanghai"
export DAFEIYU_WEATHER_ALIASES="海淀,海淀区"
```

使用传统 USB 语音路径时，指定真实串口（无线网关的首次配对另在第四步显式给出）：

```bash
export DAFEIYU_USB_SERIAL_PORT="/dev/cu.usbmodemYOURDEVICE"
```

上述环境变量只需传入实际启动的语音进程，不会修改其他已运行的设备。

## 2. 准备独立 DSH 连接

完成 [DSH Host 安装](INSTALL_MAC.md)后，为网关指定私有 Bridge token 文件：

```bash
export DAFEIYU_HOME="$HOME/Library/Application Support/Deepseek-live/my-companion"
export DAFEIYU_DSH_BRIDGE_TOKEN_FILE="$DAFEIYU_HOME/secrets/bridge.token"
```

该文件由 Host 初始化流程生成，网关读取其内容进行验证，不需要把 token 复制进命令行、配置示例或 Git 仓库。

## 3. 创建 Mac 与 ESP32 的配对凭证

先确认 Mac 已通过受信任的本地网络连接，并安装 OpenSSL。运行以下命令会在自己用户目录创建密钥、证书和设备 token：

```bash
brew install openssl
python3.12 scripts/r268_pairing_prepare.py
```

凭证保存在 `~/Library/Application Support/Deepseek-live/lan-pairing/`，文件权限为 0600，目录为 0700。已经存在的有效凭证会原样保留。

## 4. 通过 USB 配对 ESP32

插好数据线，在终端查看真实串口路径：

```bash
ls /dev/cu.usbmodem*
python3.12 -m scripts.pair_esp32
```

确认板端支持 `@@DFLAN2` 配对协议、Mac 处于空闲状态后，执行：

```bash
"$DAFEIYU_GATEWAY_VENV/bin/python" -m scripts.pair_esp32 \
  --port "/dev/cu.usbmodemYOURDEVICE" \
  --host-ip "192.168.1.100" \
  --apply
```

将串口和 IP 修改为自己的真实值，IP 必须与证书中签发的本地地址一致。命令仅通过指定 USB 串口完成配对，成功返回 `paired=true`；不会输出 token 或证书。已被其他 App 占用的串口应先由使用者在应用内释放。

## 5. 启动 Wi-Fi 语音网关

先确认 USB 语音控制者已经退出、DSH Session 和 TTS 正常运行，使用与证书匹配的本地 IP：

```bash
export DAFEIYU_GATEWAY_BIND="192.168.1.100"
export DAFEIYU_GATEWAY_PORT=8877
zsh scripts/start_voice_gateway.sh
```

网关的 TLS 证书与配对身份会从用户目录读取。ESP32 Wi-Fi 连接成功后，端到端流程为 **板麦 → WSS → Whisper → DSH / Pinky / CUA → Qwen3-TTS → WSS → 板载扬声器**。

## 6. 定位问题

| 现象 | 核查 |
|---|---|
| 配对脚本无法找到设备 | `/dev/cu.usbmodem*` 是否真实存在、串口是否被其他程序占用 |
| `pairing_identity_permissions_or_file_missing` | 初始化身份文件、确认属主与 0600 权限 |
| `bridge_token_permissions_invalid` | DSH 独立 Host 初始化和 Bridge token 文件权限 |
| 无法建立 WSS | 本机 IP、TLS 证书 IP SAN、端口 8877、ESP32 的配对状态 |
| Wi-Fi 正常但无法识别 | `DAFEIYU_WHISPER_*`、Whisper small/VAD、板麦 PCM 数据 |
| 已识别但没播音 | TTS 模型服务、参考 WAV、流式 PCM 处理 |
| 工具无结果 | DSH 会话绑定、Pinky/CUA MCP 真实回执 |

配对与网关启动仅在执行对应命令后生效，按以上步骤即可完成本机网关与设备端联调。
