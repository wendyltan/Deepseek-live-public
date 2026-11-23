# R503 发行参考声源

项目作者确认：**“冬冰”原视频声线使用已授权**，并同意将自己基于该声线二次合成的 **R503 正式参考音**作为大肥鱼项目公开运行素材。

- `r503-reference.wav`：现役 R503 的同一 8.20 秒、24 kHz、单声道参考 WAV，393,644 字节，SHA-256 `33bce3a2c5078f1ae71c117783412b16de7886ed11f580e8d4ac9edaf93556fc`。
- `r503-reference.txt`：与现役服务 `REF_TEXT` 完全一致的参考音逐字稿。
- 原声来源及授权证据类型：见 [`docs/VOICE_PROVENANCE.md`](../../docs/VOICE_PROVENANCE.md)。作者已确认原视频获授权，但具体授权文件未入库，**不虚构许可证编号，也不默认按代码 MIT 许可声源**。

新用户在项目根目录可直接设置：

```bash
export DAFEIYU_R503_REFERENCE_AUDIO="$PWD/release-assets/voice/r503-reference.wav"
export DAFEIYU_R503_REFERENCE_TEXT="$(cat release-assets/voice/r503-reference.txt)"
```

其他视频原片、私人录音、试听版本、模型权重、设备密钥和用户会话均不在此目录（那些私人录制文件从未 Git Push 或随 Release 分发），不因这一个参考样本获准分享而自动公开。

ESP32 固件构建所需的 `VOICE.WAV`、`R185_GREETING.WAV` 在公开源码包中已替换为由 `scripts/generate_firmware_assets.py` 生成的原创合成提示音，不包含任何私人录音。
