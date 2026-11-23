# MIT 许可范围 / Licensing scope

本仓库根目录 `LICENSE` 使用标准 MIT License，Copyright (c) 2026 **Wendyltanpcy**（Git 历史中的项目提交账号）。该选择仅授权权利人拥有授权权利的**项目原创代码及相应原创文档部分**，不代表对仓库中所有文件或引用的第三方内容取得了版权。提交历史归属和既有 `SPDX-License-Identifier: MIT` 是项目来源线索，**不能单独证明每个文件均为本人原创或有权二次授权**。

## 适用的自有部分

权利人确认具有授权权利、且没有单独许可证或来源限制的项目原创代码，包括：

- `app/` 中自行开发的 Python 服务与协议（不包括 `app/assets/third_party/` 等第三方资产及嵌入的外部代码）；
- `plugins/dsh-live-bridge/` 的原创 Node.js Bridge 代码（随私有安装副本附独立 `LICENSE`）；
- `native/macos/CompanionMini/` 的原创 Swift 代码；
- `scripts/`、`tests/`、`config/` 中的原创项目逻辑和配置；
- `firmware/esp32/` 中的原创固件逻辑，**不包括第三方组件、字体/字形数据、图像、动画、专有固件或有独立授权的内容**；
- 本人原创的使用说明及技术文档文字（第三方引用/原文、用户私人记录除外）。

任何文件内如包含第三方代码、模板或作品，原权利人的许可及保留声明继续有效；MIT **仅授予本项目权利人实际有权许可的原创部分**。这不是对第三方作品的再次许可。

## 不包含在本 MIT 授权的内容

1. **角色与视觉媒体**：`docs/assets/` 下所有 PNG/JPG 等截图、Logo；`firmware/esp32/unified-wifi-wake/main/assets/` 中 `ANIM.DFS` 及 `ANIM.DFS.before-*` 历史备份 及任何动画、图片和派生资产；`app/assets/third_party/` 中第三方品牌图标（例如 `deepseek-icon.svg`）；`app/motion-review/catalog.json` 记录的上游 WEBM 原动画本身。是否可以公开，需要逐件来源与权属证据。
2. **字体**：`firmware/esp32/r57-fonts/OFL-1.1.txt` 及 `firmware/esp32/**/lv_font_*.c` 等从 Adobe Source Han Sans 等字体生成的字形数据；适用其原字体许可证及保留声明（例如 SIL OFL 1.1），**不能由根 MIT 覆盖或改授**。其他生成的非原创字体/字形数据同样如此。
3. **声音与模型**：作者有权授权的自制运行音频可以按对应素材许可随项目提供，但**不自动由代码 MIT 授权**。R503 参考音色由作者依据“冬冰”的视频声线二次合成，原视频已获授权（项目作者确认），作者同意公开其二次合成的正式 R503 WAV；详细文件、哈希与独立素材许可边界见 [声源来源](docs/VOICE_PROVENANCE.md)。其他私人录音、TTS/ASR 权重及上游模型仍保留各自的授权。
4. **第三方 SDK 和工具**：ESP-IDF、LVGL、DeepSeek Harness、Pinky、Computer Use/CUA、Open-Meteo、第三方 Node/Python 库及复制进工程的上游代码、补丁片段与许可证正文，各自沿用原版权和许可证；锁文件和依赖说明不产生对上游的再次授权。
5. **私有或运行时资料**：Session、Token、密钥、聊天和记忆、手机/电脑截图、设备身份证明、签名与本机生成缓存；这些资料不作为公共软件许可或公开发行内容。
6. **权利尚未厘清的材料**：`research/` 中包含的第三方研究截录、原始素材或权属未核实的复制内容，以及尚未完成溯源的字体、历史固件补丁或派生图片；不能只凭文件在 Git 中就视为 MIT。
7. **名称与标识**：MIT 授权代码不表示授予 DeepSeek 或任何第三方的商标、服务标识、原角色形象或品牌背书权。

完整已跟踪媒体清单、许可证疑点与不可分发项目见 [第三方资源说明](docs/THIRD_PARTY_NOTICES.md)。自有代码与第三方元素混合的文件必须逐部分处理；如果不能可靠分离，则**不纳入公开包**，直到完成进一步审计。

## 公开源码范围与发布边界

**本公开发行仅发布经过净化的开源源码，不发布原始私有开发 Git 历史、未经确认再分发权的第三方角色动画二进制、模型权重或私人运行时数据。** 开发阶段的历史工作树与 `research/` 实验记录不随公开仓库分发；公开版固件中内嵌的 `ANIM.DFS`、`VOICE.WAV` 和 `R185_GREETING.WAV` 均已替换为由 `scripts/generate_firmware_assets.py` 确定性生成的原创合成占位资源。根许可证存在或发布审计报告中的 `root_license_confirmed=true` **都不等于将第三方素材或外部依赖重新授权为 MIT**。

---

**English summary.** The root MIT License applies **only to original code and documentation portions for which the listed copyright holder has licensing rights**. Media, generated font glyphs under OFL or other source licenses, character designs, sound samples, model weights, third-party SDKs, personal data, and unverified third-party excerpts are not relicensed under MIT. Git authorship alone does not prove copyright ownership. Third-party assets and character animations retain their respective upstream licenses and are not redistributed as MIT-licensed binaries.
