# 大肥鱼动作资源：许可、来源与校验

本目录保存 **106 段 DFSP 动作的校验元数据**，不保存 WebM 视频、已转换动画帧或设备身份数据。

## 上游与署名

- 上游：[PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet)
- 固定来源提交：`c696095c5786e0eeb25fec0f37a9cdcf30059151`
- 角色原型作者：**上善无形**
- 女仆鲸鱼娘形象设计：**ZipZipPipe**
- 上游角色形象声明：**Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International（CC BY-NC-SA 4.0）**
- 本项目对 WebM 的处理：取帧、中心裁切与缩放到 240×240，转换为 RGB565+A8、8FPS、zlib key/delta DFSP 格式，以适配 ESP32 动画播放。

动画与角色作品的许可与本项目自有源码的 MIT 是不同的。再分发动画应保留上游及形象作者署名、标明转换/修改、限定非商业使用并遵守相同方式共享；如果素材还包含第三方权利，则以具体素材可核实的许可为准。

## 公开校验文件

`dfsp-hashes.json`：包含 106 个动作编号、帧数、字节数及 SHA-256；不包含音视频二进制。总大小 299,266,402 字节（约 285 MiB）。

根据 [固件和 106 段动画部署指南](../../docs/INSTALL_ESP32_FIRMWARE_AND_MOTIONS.md) 取得上游授权素材、转换、校验与制作 microSD。转换器 `scripts/build_motion_library.py` 会验证原 WebM 的 Git blob 身份，并按本清单核对重建的 DFSP 文件。

仓库内的 **106/106 DFSP 动画成品均已通过只读哈希校验**（`python3.12 -m scripts.verify_motion_library`），`m000`、`m001` 抽样重编码与原始 WebM 的 SHA-256 一致。如需从原 WebM 批量重建或扩展动作库，可运行上述转换脚本并在真机上预览播放效果。

此目录本身不授予上游角色或二次动画新的 MIT 许可。
