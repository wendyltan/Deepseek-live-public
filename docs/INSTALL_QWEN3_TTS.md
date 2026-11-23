# 安装 Qwen3-TTS 本地语音合成

> **目标：** 在 Apple Silicon Mac 的独立 Python 环境中安装 **Qwen3-TTS 0.6B Base 8-bit（MLX）**，配置参考录音与逐字稿，并在独立 **8908** 端口验证本地语音合成与流式接口（不影响 8907 端口的常规服务）。

[返回 README](../README.md) · [全流程导航](INSTALL_MAC.md) · [MLX Audio 上游](https://github.com/Neywa-Labs/mlx-audio) · [Qwen3-TTS 模型卡](https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit)

## 你需要准备什么？

- Apple Silicon Mac、Python 3.12、FFmpeg、稳定网络与足够的磁盘空间。
- [`mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit`](https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit)（模型权重约 **1.99 GB**，并预留适量运行时缓存空间）。
- 一份 **WAV 参考录音**和对应的**逐字稿**。Base 模型采用参考音频克隆路线；项目提供已获授权的参考音频（由作者基于“冬冰”声线二次合成）及逐字稿，详见 [声音来源与校验说明](VOICE_PROVENANCE.md)，你也可以随时替换为自己的录音。
- 推荐实测依赖版本：`mlx-audio 0.4.5`、`mlx 0.32.0`、`huggingface-hub 1.23.0`（建议使用独立虚拟环境以保持版本一致）。

## 第一步：建立专用环境

在 `Deepseek-live` 项目根目录：

```bash
export DAFEIYU_DEPS_ROOT="$HOME/Library/Application Support/Deepseek-live/dependencies"
export DAFEIYU_TTS_VENV="$DAFEIYU_DEPS_ROOT/qwen3-tts/.venv"
mkdir -p "$DAFEIYU_DEPS_ROOT/qwen3-tts"

python3.12 -m venv "$DAFEIYU_TTS_VENV"
"$DAFEIYU_TTS_VENV/bin/python" -m pip install --upgrade pip
"$DAFEIYU_TTS_VENV/bin/python" -m pip install \
  "mlx-audio==0.4.5" "mlx==0.32.0" "huggingface-hub==1.23.0"

"$DAFEIYU_TTS_VENV/bin/python" -c \
  "from importlib.metadata import version; print('mlx-audio', version('mlx-audio')); print('mlx', version('mlx'))"
```

**成功标志：** Python 能导入所需分发包版本。建议在独立的虚拟环境中安装，避免与系统 Python 或其他项目的依赖产生冲突。

## 第二步：下载权重到自己的模型目录

```bash
export DAFEIYU_R503_MODEL_DIR="$DAFEIYU_DEPS_ROOT/qwen3-tts/model"

"$DAFEIYU_TTS_VENV/bin/hf" download \
  mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit \
  --local-dir "$DAFEIYU_R503_MODEL_DIR"

ls -lh "$DAFEIYU_R503_MODEL_DIR/model.safetensors"
ls -lh "$DAFEIYU_R503_MODEL_DIR/speech_tokenizer/model.safetensors"
```

**成功标志：** 根模型与 `speech_tokenizer` 权重文件均已完整下载且非空。若下载中断，请检查网络或磁盘空间后重新拉取。

## 第三步：准备自己的声音

选择**本人录制或已取得使用许可**的干净录音，准备准确的参考文本，参考音频应尽量避免多人说话、重背景音乐和明显截断。

```bash
mkdir -p "$DAFEIYU_DEPS_ROOT/qwen3-tts/private"

ffmpeg -i "/path/to/my-voice-source.m4a" \
  -ar 24000 -ac 1 -c:a pcm_s16le \
  "$DAFEIYU_DEPS_ROOT/qwen3-tts/private/reference.wav"

export DAFEIYU_R503_REFERENCE_AUDIO="$DAFEIYU_DEPS_ROOT/qwen3-tts/private/reference.wav"
export DAFEIYU_R503_REFERENCE_TEXT="这里填写刚才参考录音实际说出的完整文字"
export DAFEIYU_TTS_PYTHON="$DAFEIYU_TTS_VENV/bin/python"
```

将输入文件和 `DAFEIYU_R503_REFERENCE_TEXT` 改成自己有权使用的录音和对应真实文字。**如想复现项目作者的正式 R503 音色，可直接选用仓库已核对的参考音：**

```bash
export DAFEIYU_R503_REFERENCE_AUDIO="$PWD/release-assets/voice/r503-reference.wav"
export DAFEIYU_R503_REFERENCE_TEXT="$(cat release-assets/voice/r503-reference.txt)"
```

参考 WAV 为 24 kHz 单声道、8.20 秒，与现役 R503 的 SHA-256 一致；不需要复制作者机器的私人目录。

**成功标志：** WAV 可以播放，文本与其语音内容一致。录音、转写稿和其他私人语音样本不入 Git；重跑前确认不要无意覆盖已有参考文件。

## 第四步：运行本项目的只读依赖体检

```bash
python3.12 -m scripts.check_dependencies --stage tts --strict
```

**成功标志：** `ready=true`；包括 `tts_python_executable`、`model_weights`、`speech_tokenizer_weights`、`private_reference_wav`、`reference_transcript_set`、`mlx_audio_installed` 全部 `true`。

这一步仅检查本地文件与 Python 环境，不会加载 GPU 权重或播放声音。临时导出的环境变量仅在当前终端及子进程内有效。

## 第五步：验证本地语音合成

先确认 8908 未被使用：

```bash
lsof -nP -iTCP:8908 -sTCP:LISTEN
```

端口空闲时，在项目根目录启动语音合成服务，启动过程会预热模型：

```bash
export DAFEIYU_R503_PORT=8908
"$DAFEIYU_TTS_PYTHON" -m scripts.serve_tts
```

保持这一个终端运行，在**第二个终端**中检查：

```bash
curl --fail --silent http://127.0.0.1:8908/health
```

**成功标志：** `"ready":true`、`"error":null`。刚启动时 `ready=false` 表示模型仍在预热，稍等数秒再查询即可；若 `error` 不为空，请查看终端日志排查报错。

如需验证真实短句生成，确认 GPU 试运行后执行：

```bash
curl --fail --no-buffer --max-time 120 \
  -H 'Content-Type: application/json' \
  -d '{"text":"你好，今天过得怎么样？"}' \
  http://127.0.0.1:8908/stream |
python3.12 -c 'import sys,json
for line in sys.stdin:
    x=json.loads(line)
    print(x.get("type"), x.get("rate",""), x.get("frames",""),
          x.get("error",""))
'
```

**成功标志：** 收到 `start`、一到多个 `audio`，最后 `end` 且无 `error`。该脚本**只打印事件元数据**；如需确认实际音色效果，可导出 WAV 后直接试听。

第二个终端也要使用与前面相同的环境变量才能复现；由于 HTTP 命令只需端口，该示例不需要重复导出模型路径。

## 第六步：接入大肥鱼网关

`scripts.serve_tts` 已支持：

| 环境变量 | 作用 |
|---|---|
| `DAFEIYU_R503_MODEL_DIR` | 新 Mac 的模型权重目录 |
| `DAFEIYU_R503_REFERENCE_AUDIO` | 私有 WAV 声源 |
| `DAFEIYU_R503_REFERENCE_TEXT` | 对应准确转写稿 |
| `DAFEIYU_R503_PORT` | 隔离测试 `8908`、正式参考端口 `8907` |
| `DAFEIYU_TTS_PYTHON` | 外部体检与启动时选用的 Python |
| `DAFEIYU_R503_LAB_ROOT` | 可选的本地实验页面/示例资源目录，不影响 `/health` 和 `/stream` |

测试完成后，可根据 Mac 网关配置选择正式 TTS 端口。启动与常驻服务的设置见 [Mac 安装指南](INSTALL_MAC.md)。

### 常见失败

| 现象 | 处理 |
|---|---|
| 模型根文件存在但缺 `speech_tokenizer` | 模型仓库未完整下载 |
| `mlx_audio_installed=false` | `DAFEIYU_TTS_PYTHON` 指向了系统 Python 而不是新建 venv |
| `private_reference_wav=false` | 路径有误、文件不是可解码的 WAV 或录音为空 |
| `reference_transcript_set=false` | `DAFEIYU_R503_REFERENCE_TEXT` 未设置 |
| `/health` 长期 `ready=false` | 检查 GPU、MLX/Metal、模型初始化和 Python stderr |
| 合成音色不一致 | 核对参考录音路径与对应的逐字稿文本是否匹配 |
| 网关找不到 TTS 服务 | 检查服务绑定端口（`8907` / `8908`）与网关配置端口是否一致 |

**验收建议：** 按“本地依赖就绪 → `8908` 接口流式合成正常 → 试听音色与音量满意 → 接入语音网关与 ESP32 播放”四步逐级确认。
