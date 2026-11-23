# 大肥鱼 106 动画：来源与再分发权台账

> **结论：上游来源已追溯，公开再分发尚未获独立核准。** 本表从本项目实际 `app/motion-review/catalog.json` 生成，不能替代原作者许可、逐帧鉴定或对当前 `ANIM.DFS` 的内容鉴定。

## 106 段动画的来源

**106/106** 个清单动作均指向 `PC2005-cloud/dsh-pet@c696095c5786e0eeb25fec0f37a9cdcf30059151`，每个保存上游 WebM 文件名、Git blob ID、文件大小。动作分布：idle 13，other 45，reaction 8，seasonal 22，special 6，work 12。


## 许可来源与边界

- 上游 [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet) README 将程序代码 MIT 与动画、源视频和角色形象许可分开；公开的改编/展示需注明该上游仓库。
- 角色原型作者 **上善无形**、女仆鲸鱼娘设计 **ZipZipPipe**，上游列出角色许可 [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/deed.zh-hans)（署名、非商业、相同方式共享）。如采用另一个 Live2D 作者 **氵六青** 的模型，须额外遵守该具体素材的授权。
- 其他社区实例 [dsh-game 的动画 LICENSE](https://github.com/luckui/dsh-game/blob/main/packages/dsh-game/assets/dafeiyu/LICENSE.md) 同样区分代码 MIT 与衍生动画 CC BY-NC-SA，但它不是本 106 个动作的授权替代品。
- **不能把动画协议代码的 MIT 许可证扩展到 `ANIM.DFS`、WebM、转码后的 GIF/帧或角色美术。** 非商业许可不能替代商业使用授权；如要商业化或更改许可，须逐项取得具有相应权利者的许可。

## 处理决定

| 资源 | 本机现役继续使用 | 当前公开发行决定 |
|---|---|---|
| 自有动画协议、调度、DFSP/DFS 解码代码 | 保留 | 仅对自身拥有权利的代码适用 MIT |
| `firmware/esp32/unified-wifi-wake/main/assets/ANIM.DFS` | 保留 | 暂时排除，不能直接按 MIT 公开 |
| `firmware/esp32/unified-wifi-wake/main/assets/ANIM.DFS.before-r74-wifi-only` | 本地保留历史备份 | **已从当前开发 Git 索引停止跟踪**，本地原文件未删除；旧 Git 历史仍有该 blob，公开时须使用净化的新历史 |
| 106 个源 WebM 与拆帧/转码的图像 | 保留 | 暂时排除，需原作者许可和必要署名 |
| 带有经典角色画面的 UI 截图或文档插图 | 本地可用 | 发布前逐张核实，优先采用无角色、无私人数据的纯 UI 截图 |
| 用户自行绘制的原创图标 | 保留 | 原创绘图部分可以单独处理；如果直接采用上游角色特征或第三方商标仍受原权利限制 |
| 用户克隆的声音 | 保留 | 原声录音、被模仿声音、模型权重分别核实，不因“自己克隆”就自动拥有源声版权 |

**目前只隔离未来对外发布的资源范围，不删除现役 `ANIM.DFS`、动画源帧、截图和设备上的资源。** 如果未来公开 Git，需要处理历史提交中的受限 blob；只从当前工作树移除并不足够。

## 可重复转换与二进制校验

按照 [ESP32 固件与 106 动画转换指南](INSTALL_ESP32_FIRMWARE_AND_MOTIONS.md)，使用固定上游提交和 `app/motion-review/catalog.json` 的 Git blob SHA-1 校验原 WebM。`scripts/build_motion_library.py` 与 `scripts/motion_dfsp_codec.py` 提供转换器，可将取得使用权的 WebM 转为设备 DFSP，并对照 [106 段 SHA-256 清单](../release-assets/animation/dfsp-hashes.json)验证成品。

本地已确认 **106/106 上游 WebM 来源身份**；抽样重新编码的 `m000`、`m001` 与现役原始文件 **SHA-256 完全一致**。全部 106 段重编码、新 SD 和新板的整条验收仍需继续。

动画与角色按上游 CC BY-NC-SA 4.0 的范围署名、标明改动并保持非商用及相同方式共享，独立于本项目自有代码 MIT 许可。

## 本地复现与公众使用的区别

- 本地使用者可阅读 [上游 dsh-pet](https://github.com/PC2005-cloud/dsh-pet) 的原始许可，按其使用场景自行合法获取视频并转换到自己的板子。
- 当前仓库尚未有可向陌生使用者承诺的“通用自动获取 106 动画并打包”流程。README 不会宣称自动内置合法可分发素材。
- `app/animation_catalog.json` 另保存“吃白饭、写代码、打瞌睡被惊醒”三段人工认可动作，其现有 `rights` 字段已经标注非商用与公开再分发待核；真人审美认可不是版权许可。
- 本登记表记录的是 **106 个审片素材索引**，还没有完整的 WebM → 帧 → `ANIM.DFS` 的逐帧 SHA256 证据，所以不能据此断言现役二进制包内部恰好包含全部 106 段。

## 逐项来源登记

| ID | 动作名 | 类型 | 上游 WebM | 上游 Git blob（12位） | 公开分发状态 |
|---|---|---|---|---|---|
| m000 | 待机呼吸休闲 | idle | `待机呼吸休闲.webm` | `fd64a428a2be` | 待授权 |
| m001 | 原地小憩沉眠 | idle | `原地小憩沉眠.webm` | `9b258545a841` | 待授权 |
| m002 | 东张西望 | idle | `东张西望.webm` | `3ba4edb2cc64` | 待授权 |
| m003 | 哈欠连天 | idle | `哈欠连天.webm` | `63da356fa373` | 待授权 |
| m004 | 超大伸懒腰 | idle | `超大伸懒腰.webm` | `689e04f120f9` | 待授权 |
| m005 | 悠闲哼歌 | idle | `悠闲哼歌.webm` | `01bd5c202583` | 待授权 |
| m006 | 原地专心玩魔方 | idle | `原地专心玩魔方.webm` | `d2730f4c17e8` | 待授权 |
| m007 | 撸猫 | idle | `撸猫.webm` | `466044675ea2` | 待授权 |
| m008 | 原地蹲下玩玩具汽车 | idle | `原地蹲下玩玩具汽车.webm` | `9a4ba01b33e6` | 待授权 |
| m009 | 照镜子 | idle | `照镜子.webm` | `f9ead4a5e1ab` | 待授权 |
| m010 | 轻快记录 | idle | `轻快记录.webm` | `d0c1bc670b74` | 待授权 |
| m011 | 三球抛接 | idle | `三球抛接.webm` | `a76228cb5f42` | 待授权 |
| m012 | 点击回应-傲娇生气 | reaction | `点击回应-傲娇生气.webm` | `77c6461a1f8c` | 待授权 |
| m013 | 点击回应-元气挥手 | reaction | `点击回应-元气挥手.webm` | `f60556f06c38` | 待授权 |
| m014 | 点击回应-害羞惊讶 | reaction | `点击回应-害羞惊讶.webm` | `499b73c42844` | 待授权 |
| m015 | 点击回应-开心跃动 | reaction | `点击回应-开心跃动.webm` | `fb614abf8d19` | 待授权 |
| m016 | 点击回应-挠痒咯咯笑 | reaction | `点击回应-挠痒咯咯笑.webm` | `d896eb9a91ca` | 待授权 |
| m017 | 被吓一跳 | reaction | `被吓一跳.webm` | `a7afe71ed729` | 待授权 |
| m018 | 被鼠标拖拽悬空反馈 | reaction | `被鼠标拖拽悬空反馈.webm` | `728f04b2997a` | 待授权 |
| m019 | 原地重力下蹲压缩 | reaction | `原地重力下蹲压缩.webm` | `67acb52f7e7c` | 待授权 |
| m020 | 写代码 | work | `写代码.webm` | `47902f235c11` | 待授权 |
| m021 | 原地敲击桌面互动 | work | `原地敲击桌面互动.webm` | `c7e55e6f83c1` | 待授权 |
| m022 | 工作状态-原地踱步张望 | work | `工作状态-原地踱步张望.webm` | `7b9459a1efdf` | 待授权 |
| m023 | 工作状态-垂头叹气冒汗 | work | `工作状态-垂头叹气冒汗.webm` | `653ef82b71d5` | 待授权 |
| m024 | 工作状态-忙碌点按 | work | `工作状态-忙碌点按.webm` | `32bc6dbf65a7` | 待授权 |
| m025 | 工作状态-思考冒泡 | work | `工作状态-思考冒泡.webm` | `51bc3bb2fb89` | 待授权 |
| m026 | 工作状态-清点归档 | work | `工作状态-清点归档.webm` | `af694fb0013c` | 待授权 |
| m027 | 工作状态-雀跃庆祝 | work | `工作状态-雀跃庆祝.webm` | `edd6645a8ee9` | 待授权 |
| m028 | 深度思考碎碎念 | work | `深度思考碎碎念.webm` | `5a40d5bfdfa8` | 待授权 |
| m029 | 碎碎念-发呆碎碎念 | work | `碎碎念-发呆碎碎念.webm` | `4afcaf7459e3` | 待授权 |
| m030 | 碎碎念-对屏碎碎念 | work | `碎碎念-对屏碎碎念.webm` | `8b7b357f01a9` | 待授权 |
| m031 | 碎碎念-擦桌碎碎念 | work | `碎碎念-擦桌碎碎念.webm` | `343513cf0d55` | 待授权 |
| m032 | 余额-分文不剩 | special | `余额-分文不剩.webm` | `013b69906a5c` | 待授权 |
| m033 | 余额-数金皱眉 | special | `余额-数金皱眉.webm` | `6c1dac8e3edd` | 待授权 |
| m034 | 余额-袋空如洗 | special | `余额-袋空如洗.webm` | `a85eb2206596` | 待授权 |
| m035 | 余额-金袋叮当 | special | `余额-金袋叮当.webm` | `1bbe074a0bef` | 待授权 |
| m036 | 余额-钱袋如常 | special | `余额-钱袋如常.webm` | `a52b686a7a3d` | 待授权 |
| m037 | 余额-钱袋满溢 | special | `余额-钱袋满溢.webm` | `34212594a3b9` | 待授权 |
| m038 | 中秋赏月吃月饼 | seasonal | `中秋赏月吃月饼.webm` | `48beff57ddc5` | 待授权 |
| m039 | 写福字 | seasonal | `写福字.webm` | `b7aa9ce458b6` | 待授权 |
| m040 | 吃冰淇淋融化 | seasonal | `吃冰淇淋融化.webm` | `c696cf2f6136` | 待授权 |
| m041 | 吃年糕 | seasonal | `吃年糕.webm` | `7b4473435dfa` | 待授权 |
| m042 | 吃汤圆 | seasonal | `吃汤圆.webm` | `eac65950006c` | 待授权 |
| m043 | 吃粽子 | seasonal | `吃粽子.webm` | `6ad057c473cb` | 待授权 |
| m044 | 吃糖葫芦 | seasonal | `吃糖葫芦.webm` | `def3fa70022f` | 待授权 |
| m045 | 吃西瓜 | seasonal | `吃西瓜.webm` | `ffa2c36e86e9` | 待授权 |
| m046 | 吃重阳糕 | seasonal | `吃重阳糕.webm` | `cc54c1f82bb5` | 待授权 |
| m047 | 吃长寿面 | seasonal | `吃长寿面.webm` | `ac71008a0768` | 待授权 |
| m048 | 吃青团 | seasonal | `吃青团.webm` | `00031236d476` | 待授权 |
| m049 | 堆雪人 | seasonal | `堆雪人.webm` | `ce8e8be3b7e5` | 待授权 |
| m050 | 插茱萸赏菊 | seasonal | `插茱萸赏菊.webm` | `7e2976e00317` | 待授权 |
| m051 | 放孔明灯 | seasonal | `放孔明灯.webm` | `ca554c0df5fb` | 待授权 |
| m052 | 放河灯 | seasonal | `放河灯.webm` | `2827fd308393` | 待授权 |
| m053 | 放烟花 | seasonal | `放烟花.webm` | `3a1bcd38b00b` | 待授权 |
| m054 | 放风筝 | seasonal | `放风筝.webm` | `000eba2f49a1` | 待授权 |
| m055 | 穿针乞巧 | seasonal | `穿针乞巧.webm` | `f78881f4e996` | 待授权 |
| m056 | 舞狮头 | seasonal | `舞狮头.webm` | `b16d549ec257` | 待授权 |
| m057 | 装点圣诞树 | seasonal | `装点圣诞树.webm` | `1217c9625c3a` | 待授权 |
| m058 | 讨糖南瓜灯 | seasonal | `讨糖南瓜灯.webm` | `3a17ac14fba4` | 待授权 |
| m059 | 踢毽子 | seasonal | `踢毽子.webm` | `1a0586564e58` | 待授权 |
| m060 | 下五子棋 | other | `下五子棋.webm` | `63295b32e6a0` | 待授权 |
| m061 | 优雅女仆舞 | other | `优雅女仆舞.webm` | `390c504dfb0b` | 待授权 |
| m062 | 偷吃零食被抓住 | other | `偷吃零食被抓住.webm` | `9f50ed6c3ba1` | 待授权 |
| m063 | 凭空生花 | other | `凭空生花.webm` | `085fe6d74ddf` | 待授权 |
| m064 | 动物环绕 | other | `动物环绕.webm` | `44722e0afb7e` | 待授权 |
| m065 | 原地左转奔跑 | other | `原地左转奔跑.webm` | `d9b6611b3206` | 待授权 |
| m066 | 原地漂浮踏步 | other | `原地漂浮踏步.webm` | `d700e4fdd38e` | 待授权 |
| m067 | 原地跳跃抓碎头顶物品 | other | `原地跳跃抓碎头顶物品.webm` | `b45cdcb57340` | 待授权 |
| m068 | 变鸽子 | other | `变鸽子.webm` | `150abd9011b3` | 待授权 |
| m069 | 可爱宅舞 | other | `可爱宅舞.webm` | `0b96ac0de6fa` | 待授权 |
| m070 | 吃Token | other | `吃Token.webm` | `619722b50ea7` | 待授权 |
| m071 | 吃午餐 | other | `吃午餐.webm` | `83618038d3d4` | 待授权 |
| m072 | 吃大闸蟹 | other | `吃大闸蟹.webm` | `f8e0774d6b4b` | 待授权 |
| m073 | 吃早餐 | other | `吃早餐.webm` | `6691dc43900e` | 待授权 |
| m074 | 吃晚餐 | other | `吃晚餐.webm` | `14f9eee2a361` | 待授权 |
| m075 | 吃白饭 | idle | `吃白饭.webm` | `0f400023c2f0` | 待授权 |
| m076 | 吃腊八粥 | other | `吃腊八粥.webm` | `c20156c0de08` | 待授权 |
| m077 | 吃饺子 | other | `吃饺子.webm` | `2dee24954bae` | 待授权 |
| m078 | 吹气球 | other | `吹气球.webm` | `3a632cd91c40` | 待授权 |
| m079 | 吹笛子 | other | `吹笛子.webm` | `fd57f820116b` | 待授权 |
| m080 | 大口吃零食 | other | `大口吃零食.webm` | `ab57e48e28d0` | 待授权 |
| m081 | 女仆屈膝礼仪 | other | `女仆屈膝礼仪.webm` | `0bcac6ada85e` | 待授权 |
| m082 | 小幅度原地360度旋转展示 | other | `小幅度原地360度旋转展示.webm` | `915feb453f11` | 待授权 |
| m083 | 小提琴演奏 | other | `小提琴演奏.webm` | `2de1533cd0f2` | 待授权 |
| m084 | 扑克魔术 | other | `扑克魔术.webm` | `2e33efead726` | 待授权 |
| m085 | 打瞌睡被惊醒 | other | `打瞌睡被惊醒.webm` | `e5c575989527` | 待授权 |
| m086 | 抽陀螺 | other | `抽陀螺.webm` | `1a0cd6a9447c` | 待授权 |
| m087 | 拆礼物 | other | `拆礼物.webm` | `01445f708db3` | 待授权 |
| m088 | 摇扇纳凉 | other | `摇扇纳凉.webm` | `bbb9b8344e6c` | 待授权 |
| m089 | 收红包 | other | `收红包.webm` | `ca07f8792572` | 待授权 |
| m090 | 整体换装试色 | other | `整体换装试色.webm` | `abd198a8d1e4` | 待授权 |
| m091 | 是啊，吃什么 | other | `是啊，吃什么.webm` | `e347b7574b4d` | 待授权 |
| m092 | 晨间刷牙 | other | `晨间刷牙.webm` | `66581dbd88c7` | 待授权 |
| m093 | 涮火锅 | other | `涮火锅.webm` | `d3e99cf6d869` | 待授权 |
| m094 | 玩水枪 | other | `玩水枪.webm` | `70cabac39a03` | 待授权 |
| m095 | 玩游戏气急败坏 | other | `玩游戏气急败坏.webm` | `a3375c298063` | 待授权 |
| m096 | 用鲸鱼尾巴拍打地面 | other | `用鲸鱼尾巴拍打地面.webm` | `822a7c41f795` | 待授权 |
| m097 | 荡秋千 | other | `荡秋千.webm` | `41c614294051` | 待授权 |
| m098 | 萌化小幽灵 | other | `萌化小幽灵.webm` | `cae5ebbca863` | 待授权 |
| m099 | 蓝鲸现世 | other | `蓝鲸现世.webm` | `eb62a155d056` | 待授权 |
| m100 | 蝴蝶蜜蜂环绕头顶开花 | other | `蝴蝶蜜蜂环绕头顶开花.webm` | `6f39bb90fd83` | 待授权 |
| m101 | 螃蟹走路 | other | `螃蟹走路.webm` | `6ff801362957` | 待授权 |
| m102 | 被落叶淹没 | other | `被落叶淹没.webm` | `1e35fff171fb` | 待授权 |
| m103 | 轻快摇摆舞 | other | `轻快摇摆舞.webm` | `596558b14cac` | 待授权 |
| m104 | 骑木马 | other | `骑木马.webm` | `b578f4c951a1` | 待授权 |
| m105 | 鲸鱼吐泡泡特效 | other | `鲸鱼吐泡泡特效.webm` | `4848e28f2c4f` | 待授权 |

## 公开之前尚须补充

1. 将上游版本的 LICENSE / README / NOTICE 与该 commit 固定留证；逐项确认署名、非商业和衍生共享条件。
2. 如计划商业应用，向角色设计及相关动画版权所有人取得覆盖具体商业用途的许可；单一仓库作者的口头允许不当然覆盖原角色权利。
3. 核对本机转换流水线各阶段的源文件 Hash、帧数和 `ANIM.DFS` 清单；不在权属不明时自动重新打包公开。
4. 若不随仓库公开动画，需提供可复现的“自行准备已获授权资源”的技术说明或独立原创的替代演示动画，并在 README 说明当前安装器不会自动配置角色动画。
