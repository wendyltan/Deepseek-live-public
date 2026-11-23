# 安装 Whisper 语音识别（Apple Silicon Mac）

> **目标：** 安装与大肥鱼当前代码一致的 `whisper.cpp` 多语言 `small` 模型及 Silero VAD，让 `app/stt_local.py` 能识别 ESP32 板载麦克风传来的中文声音。此环节**不启动 DSH、不操作板子，也不会调用云端模型**。

[返回 README](../README.md) · [全流程导航](INSTALL_MAC.md) · [Whisper 上游官方指南](https://github.com/ggml-org/whisper.cpp)

## 你需要准备

- Apple Silicon Mac、Git、CMake、FFmpeg；推荐 Python 3.12。
- 下载并编译 [ggml-org/whisper.cpp](https://github.com/ggml-org/whisper.cpp)；使用 **多语言 `small`**，不是 `small.en`。
- 如果需要板端自动唤醒后的语音过滤，再下载 `silero-v6.2.0` VAD。
- 下载体积与网络消耗：`small` 模型约 **465 MB**，VAD 模型约 **0.9 MB**；下载由用户或 Agent 在获得允许后进行。

## 第一步：安装编译工具

已安装 [Homebrew](https://brew.sh/) 的 Mac 终端：

```bash
brew install cmake ffmpeg git python@3.12
cmake --version
ffmpeg -version | head -n 1
python3.12 --version
```

**成功标志：** 三条命令均可正常输出版本号，即可进入下一步。

## 第二步：下载并编译 whisper.cpp

下面使用使用者自己的目录；在项目 `Deepseek-live` 仓库根目录运行这些命令：

```bash
export DAFEIYU_DEPS_ROOT="$HOME/Library/Application Support/Deepseek-live/dependencies"
mkdir -p "$DAFEIYU_DEPS_ROOT"

git clone https://github.com/ggml-org/whisper.cpp.git \
  "$DAFEIYU_DEPS_ROOT/whisper.cpp"

# 与参考机器的 whisper.cpp 实际检出提交一致
git -C "$DAFEIYU_DEPS_ROOT/whisper.cpp" checkout --detach \
  0c7be696371069e0baa2515ed7aa08d5a5473aa6

cmake -S "$DAFEIYU_DEPS_ROOT/whisper.cpp" \
  -B "$DAFEIYU_DEPS_ROOT/whisper.cpp/build" \
  -DCMAKE_BUILD_TYPE=Release
cmake --build "$DAFEIYU_DEPS_ROOT/whisper.cpp/build" -j 4
```

**成功标志：** 生成 `$DAFEIYU_DEPS_ROOT/whisper.cpp/build/bin/whisper-cli`。如果该目录已经存在，直接进入目录 `git fetch` 并切换到上述 commit 即可，无需重复克隆。

## 第三步：下载中文语音模型与 VAD

```bash
cd "$DAFEIYU_DEPS_ROOT/whisper.cpp"

bash models/download-ggml-model.sh small
bash models/download-vad-model.sh silero-v6.2.0

ls -lh models/ggml-small.bin models/ggml-silero-v6.2.0.bin
```

**成功标志：** 两个模型文件存在且大小完整。`ggml-small.bin` 为包含中文的多语言模型，VAD 脚本输出 `ggml-silero-v6.2.0.bin`。若下载中断，请检查网络或代理设置后重新下载。

## 第四步：配置大肥鱼自己的路径

回到 `Deepseek-live` 项目根目录：

```bash
export DAFEIYU_WHISPER_CLI="$DAFEIYU_DEPS_ROOT/whisper.cpp/build/bin/whisper-cli"
export DAFEIYU_WHISPER_MODELS="$DAFEIYU_DEPS_ROOT/whisper.cpp/models"
export DAFEIYU_WHISPER_VAD_MODEL="$DAFEIYU_WHISPER_MODELS/ggml-silero-v6.2.0.bin"
export DAFEIYU_FFMPEG="$(command -v ffmpeg)"
export DAFEIYU_ASR_MODEL="small"

python3.12 -m scripts.check_dependencies --stage asr --strict
```

**成功标志：** 四项（`whisper_cli_executable`、`multilingual_small_model`、`silero_vad_model`、`ffmpeg_executable`）均 `true`，`ready=true`。

`app/stt_local.py` 会优先读取上述环境变量（未设置时回退到默认依赖路径）。**注意：启动语音网关的终端或服务进程也需继承这些环境变量**，建议将其写入启动脚本或 `.env`。

## 第五步：本地只读试运行

先用上游自带样本验证 CLI，不需要连接 ESP32：

```bash
"$DAFEIYU_WHISPER_CLI" \
  -m "$DAFEIYU_WHISPER_MODELS/ggml-small.bin" \
  -f "$DAFEIYU_DEPS_ROOT/whisper.cpp/samples/jfk.wav"
```

可看到非空识别文本即可，样本为英文只是为了检查推理引擎是否启动；之后用自己有权使用的中文录音进行 16kHz 单声道转换并验证：

```bash
ffmpeg -i "/path/to/your-recording.m4a" -t 20 -ar 16000 -ac 1 \
  -c:a pcm_s16le "$DAFEIYU_DEPS_ROOT/chinese-test.wav"

"$DAFEIYU_WHISPER_CLI" \
  -m "$DAFEIYU_WHISPER_MODELS/ggml-small.bin" \
  -f "$DAFEIYU_DEPS_ROOT/chinese-test.wav" -l zh
```

把 `/path/to/your-recording.m4a` 换成你的测试录音路径。本地文件转写通过后，接入 ESP32 即可进行板载麦克风的端到端语音识别。

## 第六步：接入大肥鱼语音链

1. 启动网关时，确保其进程继承了第四步设置的环境变量。
2. `app/stt_local.py` 会将板载麦克风录音经 FFmpeg 转为 16kHz 单声道 WAV 后送入 `whisper-cli`；在持续唤醒场景下会结合 Silero VAD 过滤静音与背景噪声。
3. 若文本对话正常但语音无响应，可按 **设备拾音 → USB/WSS → FFmpeg 解码 → Whisper 模型 → DSH 会话** 逐段排查。

### 故障定位

| 现象 | 排查建议 |
|---|---|
| `command not found: cmake` / `ffmpeg` | 确认 Homebrew 已安装且 `/opt/homebrew/bin` 在 `PATH` 中 |
| 模型被误下成 `small.en` | 重新运行 `download-ggml-model.sh small` 获取多语言模型 |
| `multilingual_small_model=false` | 检查 `models/ggml-small.bin` 文件大小是否完整 |
| `silero_vad_model=false` | 确认 `DAFEIYU_WHISPER_VAD_MODEL` 指向 `ggml-silero-v6.2.0.bin` |
| 终端测试正常但网关报错 | 环境变量未传入网关启动进程，请检查启动脚本 |
| 手动按键可用但唤醒无反应 | 检查 `DAFEIYU_WHISPER_VAD_MODEL` 与板端唤醒词设置 |
