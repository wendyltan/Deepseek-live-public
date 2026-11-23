# 第三方依赖与可分发素材清单

这份清单面向未来 GitHub Release。**源代码可见，不意味着其中所有二进制、角色素材、模型和录音都可以二次公开分发。**

| 资产类别 | 来源 / 当前边界 | 对外发行状态 |
|---|---|---|
| ESP-IDF、芯片 SDK | Espressif 官方，按具体版本许可证与依赖锁使用 | 可引用官方来源；不附带私人SDK镜像 |
| DeepSeek Harness DSH | 官方上游、锁定到参考版本 | 使用者自行安装与授权；留意 RC 兼容 |
| 大肥鱼 Live Bridge | 本仓库 `plugins/dsh-live-bridge`，包内声明 MIT | 自有部分可审计；不覆盖第三方资产 |
| Pinky App / MCP | 使用者独立安装与连接、上游许可另核 | 不打包 App、电话资料、令牌 |
| macOS CUA helper | 官方 DSH native helper，可能需要 Mac 权限和签名 | 先确认签名/再分发权，不将本机helper视为公开资产 |
| Whisper / Qwen3-TTS | 模型与推理环境按官方模型卡/许可证 | 只给下载/校验指引，权重本阶段不公开 |
| R503 参考音色 | 作者声明：基于“冬冰”的视频声线二次合成；详细出处待补 | **已授权（项目作者确认）**；作者同意将衍生 R503 正式参考 WAV 用于拟公开部署，已单独选定文件与逐字稿并附 [来源和 SHA-256](VOICE_PROVENANCE.md)；实际许可条件不由代码 MIT 代替 |
| 大肥鱼角色动画/贴图/声音特效 | 经典社区角色与衍生制作可能涉及独立版权 | **来源和再分发权未确认之前不打包** |
| 参考机 ESP32固件镜像、NVS、身份、发布签名 | 绑定实际设备的私有回执 | 绝不作为别人首刷资源 |
| macOS 应用签名/Developer ID | 绑定开发者账户与钥匙串 | 开发者重新签名，不能复制作者本机身份 |

## 发布门槛

1. 逐文件确定创作者、出处、原始许可证、修改情况、保留署名义务、是否允许商业使用/再分发。
2. 分出公开自有代码、需用户单独下载的上游软件、完全禁止上传的私人资料；不要将全部内容统一标为 MIT。
3. 检查 Git index 和 Release 文件清单中是否有 token、设备身份、邮箱、个人对话、语音样本、未获授权的动画帧。
4. 项目权利人已选择根目录 **MIT License**，但依 [授权范围](../LICENSE_SCOPE.md) 仅覆盖有权许可的原创代码/文档部分。不能对外宣称所有素材与第三方代码均为 MIT；公开发行仍受素材权利和隐私清理门禁阻止。
5. 另一个使用者的 Mac 和 ESP32 必须生成各自身份与发布证明。

若有无法核对来源的资源，把它当作非发行素材处理，并以可替换的授权资源占位，直到许可证核实。

## 媒体与二进制资源的发行边界

公开源码包已排除开发阶段包含个人对话或第三方角色帧的历史截图（如早期 `mac-native-*.png`、`r483-*.png`、`r487-*.png`）以及现役第三方角色编译包 `ANIM.DFS` 与历史备份 `ANIM.DFS.*`，仅保留经核验的公开文档插图与确定性生成的原创固件占位资源：

| 路径 | 类型 | 公开源码包处理方式 |
|---|---|---|
| `docs/assets/deepseek-live-icon.png` | 项目文档图标 | 仅用于仓库文档展示，不随 MIT 授予商标或原作角色版权 |
| `docs/assets/mac-floating-pet.png` | Mac 桌宠悬浮窗实机截图 | 496×496 桌面四方悬浮窗与 496×74 折叠条模式截图（含 CC BY-NC-SA 4.0 上游鲸鱼娘动作预览帧） |
| `docs/assets/mac-center-overview.png` | Mac 管理中心概览页 | 管理中心概览、106 段动作库预览舞台与 Core/Style 人设卡片截图（含上游鲸鱼娘动作预览帧） |
| `docs/assets/mac-center-conversations.png` | Mac 对话与上下文页 | 上下文压力进度条、Pinky/CUA 原生工具回执与语音记忆逐条审批示例 |
| `docs/assets/mac-app-public.png` | Mac 插件管理页 | 脱敏的 Mac 管理端插件与扩展页面示例，不包含私人会话 |
| `docs/assets/esp32-ui-overview.png` | ESP32 界面概览 | 480×480 板端 LVGL 主屏（含上游鲸鱼娘预览帧）与控制中心/状态/存储四页概览图 |
| `docs/assets/dafeiyu-promo-preview.gif` | 16:9 项目宣传短片预览动图 | 由项目脚本与 Remotion 合成的 16:9 宣传片预览图（包含部分上游鲸鱼娘预览帧） |
| `release-assets/voice/r503-reference.wav` | R503 参考音色 | 项目作者基于已获授权的“冬冰”视频声线二次合成并确认公开，详见 [声源来源](VOICE_PROVENANCE.md) |
| `firmware/esp32/unified-wifi-wake/main/assets/ANIM.DFS` | 固件默认动画占位 | 由 `scripts/generate_firmware_assets.py` 生成的 8 帧原创几何动画，不含第三方角色帧 |
| `firmware/esp32/unified-wifi-wake/main/assets/VOICE.WAV` | 固件默认提示音 | 由 `scripts/generate_firmware_assets.py` 生成的原创合成双音提示音 |
| `firmware/esp32/unified-wifi-wake/main/assets/R185_GREETING.WAV` | 固件默认问候提示音 | 由 `scripts/generate_firmware_assets.py` 生成的原创合成三音和弦提示音 |

自有 Bridge 包 `package.json` 声明 MIT，并配套 `plugins/dsh-live-bridge/LICENSE`；根目录 `LICENSE` 为标准 MIT 正文。两者**均只覆盖有权许可的原创部分**，不能自动覆盖上述媒体、字形数据、模型、第三方 SDK 或上游代码。

## 扩展边界：字体字形、SVG 与第三方代码

以下文本、字形或配置引用遵循各自原有的许可证或权利边界，不由根目录 MIT 覆盖：

| 路径/范围 | 来源线索 | 许可及公开处理 |
|---|---|---|
| `app/assets/third_party/deepseek-icon.svg` | 第三方品牌图标 | 不纳入原创 MIT 许可，不随公开源码包分发 |
| `firmware/esp32/r57-fonts/OFL-1.1.txt` | SIL Open Font License 1.1 | 保留独立 OFL-1.1 许可，不用 MIT 覆盖 |
| `firmware/esp32/**/lv_font_*.c` | LVGL 字库生成输出（基于 SIL OFL 1.1 字体） | 字形与字体衍生部分由原字体许可（SIL OFL 1.1）约束 |
| `app/motion-review/catalog.json` | 记录第三方动画源文件名称与上游 Git blob | 自有目录索引与校验表，不是上游动画视频本身的再分发授权 |
| `research/**` 和历史 `firmware/esp32/patches/**` | 开发阶段实验记录与历史补丁 | 已从公开源码包中整体排除 |
| ESP-IDF、LVGL、DSH、Pinky/CUA、依赖安装锁 | 由独立上游许可证管理 | 不随本仓库 MIT 被重新授权；遵守原许可和 NOTICE 义务 |

完整约束见根目录 [LICENSE_SCOPE.md](../LICENSE_SCOPE.md)。**Git 提交者归属是提交证据，不等于逐文件的独立版权鉴定。**

## 106 段角色动画溯源与本地重建

详见 [动画素材权属台账](ANIMATION_RIGHTS_REGISTER.md) 与 [`release-assets/animation/README.md`](../release-assets/animation/README.md)：106 个动作均记录上游来源（CC BY-NC-SA 4.0）、WebM 文件名、Git blob 与转换后的 DFSP SHA-256 清单。公开仓库不直接打包第三方角色动画二进制；使用者可按 [固件与 106 动画构建指南](INSTALL_ESP32_FIRMWARE_AND_MOTIONS.md) 从上游仓库拉取并通过 `scripts.build_motion_library` 在本地转换与校验。
