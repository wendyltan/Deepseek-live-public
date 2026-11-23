# 参考声源来源与授权说明

> **授权状态：已授权（项目作者确认，2026-11-22）。** 项目作者确认“冬冰”原声线素材已获授权使用，并将其二次合成的 **R503 参考声源**作为大肥鱼项目的默认参考音随仓库提供。

## 声源署名说明

> **R503 参考声源：** 由项目作者参考“冬冰”声线通过 Qwen3-TTS 0.6B Base（MLX-Audio）二次合成，原素材已获授权（项目作者确认）。

## 随仓库提供的参考声源

| 项目 | 内容 |
|---|---|
| 原声线来源 | “冬冰”声线；**已授权（项目作者确认）** |
| 制作方式 | 基于原声线二次合成并调试生成 R503 参考音 |
| 发行范围 | 随仓库提供单一参考 WAV 与对应逐字稿（其余个人音频与模型权重需按指南自行准备或下载） |
| 参考音频文件 | `release-assets/voice/r503-reference.wav` |
| 对应逐字稿 | `release-assets/voice/r503-reference.txt` |
| WAV 参数 | 单声道、24 kHz、16-bit PCM、8.20 秒，393,644 字节 |
| WAV SHA-256 | `33bce3a2c5078f1ae71c117783412b16de7886ed11f580e8d4ac9edaf93556fc` |

该参考音频与逐字稿已和 `app/r644_r503_production_server.py` 中的 `REF_TEXT` 保持一致。

## 如何使用项目内置参考音

在项目根目录导出以下环境变量即可直接使用随库提供的参考音与逐字稿：

```bash
export DAFEIYU_R503_REFERENCE_AUDIO="$PWD/release-assets/voice/r503-reference.wav"
export DAFEIYU_R503_REFERENCE_TEXT="$(cat release-assets/voice/r503-reference.txt)"
```

随后按 [Qwen3-TTS 安装指南](INSTALL_QWEN3_TTS.md) 配置模型目录、独立 Python 环境并启动服务。你也可以随时将上述两个变量替换为自己录制的 WAV 音频与对应逐字稿。

## 许可说明

- **参考音频用途**：随仓库提供的单一参考 WAV 仅用于大肥鱼本地 TTS 部署示例，不自动涵盖原视频或未纳入仓库的其他音频素材。
- **代码与素材分层**：项目源码采用 MIT 协议；参考音色素材的授权仅限于当前随附文件本身，源代码的 MIT 协议不自动对第三方人物声线或原素材做二次通用许可。如需商业衍生或重新分发声源，请自行确认相关授权条件。
