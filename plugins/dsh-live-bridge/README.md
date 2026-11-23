# dsh-live-bridge — Deepseek-live 自有 Harness 适配插件（0.4.6）

`dsh-live-bridge` 是大肥鱼（`Deepseek-live`）项目的核心 Cordis / DeepSeek Harness 适配插件，负责在本地回环（`127.0.0.1:3080`）为 Mac 语音网关与原生管理 App 提供受鉴权的会话绑定、人设与动态上下文注入、手动记忆与人格成长审核、只读任务状态快照（`companion-facts`）及手机/电脑工具回执核验。

- 安装与宿主配置指南：[Mac Host 安装指南](../../docs/INSTALL_MAC.md) · [插件管理说明](../../docs/PLUGINS.md) · [系统架构](../../docs/ARCHITECTURE.md)

## Companion Facts（隔离可选）

插件提供 **`POST /dsh-live-bridge/companion-facts`**，从**同一个官方 DSH Session 内已有任务的受验证状态**生成供可信 Mac 视觉/设备网关使用的安全快照。该接口不会创建 Agent、发送提示、请求模型、审批工具或启动播放；保留原先 `/result` 的最终回答和任务回执语义。

默认关闭。只有 Harness 启动环境显式配置 `DSH_LIVE_ENABLE_COMPANION_FACTS=1`、已有独立 Bridge Token 与回环服务限制时才可用。请求使用同其他敏感接口一致的 Bearer：

```json
{
  "protocolVersion": 1,
  "task_id": "<已有任务 ID>",
  "session_id": "<任务所属原生 DSH Session ID>"
}
```

HTTP 200 只返回 `turn_id`、`session_id`、递增的 `revision`、`task_phase`、`tool_active_count`、`tool_failed`、`approval_pending`、`outcome` 和 `assistant_ready_for_tts` 等字段；**不含 prompt、回复正文、工具入参/正文或令牌**。来源未验证的V4工具回执不会使工具完成；不同Session的同名callId分别处理。接口不是ESP32公网/LAN端点，设备只能通过未来单独鉴权的 Mac 设备网关访问映射后的最少状态。

- `revision` 从同一任务的原生工具、审批、回答、结轮及Agent状态事实递增（首快照为0），受信Mac消费者须拒绝重复或乱序结果；失败／取消结轮后不再显示旧审批等待。
- Mac 端提供 `app/companion_facts_client.py` 的固定回环受权读取器和 `app/companion_trusted_adapter.py` 的确定性状态投影。读取消费者不会自动部署到 P1 页面，也不向 ESP32 传播 Bridge Token；播放器启动、结束、实际音量须由Mac可信本地播放器回调，不能让远程浏览器伪造。
- `task_phase` 是 **DSH任务事实**（thinking、working、approval_pending、cancel_requested、settling、settled），**不等于** `app/companion_events.py` 中的物理设备状态；设备状态与播放确认由 Mac 可信 Adapter 再做校验。
- `assistant_ready_for_tts=true` 只出现在 Bridge 最终 `answered/completed` 后，**不意味着 D10 已生成/音箱已播放**，因此不可直接据此张嘴。
- 未授权401、非回环403、关闭503、任务不存在404、Session不匹配409；已结束的任务记录随 `/end` 从内存映射清除，再查询返回404；接口也不会回读已结束的持久会话历史。当前仅有模拟宿主合同测试；正式 Profile 虽已加载插件，本接口尚未在该 Profile 运行验收。

专项测试与架构边界见 [系统架构说明](../../docs/ARCHITECTURE.md) 与 `test/companion-facts.test.mjs`。

## 会话绑定、人设与手动记忆接口

新增后端独立受信本机 `app/dsh_p1_adapter.py`：P1 在 `P1_DSH_BRIDGE_ENABLED=1` 时使用 `P1_DSH_BRIDGE_URL=http://127.0.0.1:<项目隔离端口>` 和 `P1_DSH_BRIDGE_TOKEN`（服务端私有，不能暴露页面/ESP32），绕过 P1 direct REST / `ModelSessions` 这两套模型真相。Bridge 新增受限 `POST /models`（只列出隔离 Host 用 `DSH_LIVE_P1_VISIBLE_MODELS` 配置且原生路由验证的模型）、`POST /bind`（不花钱创建/恢复原生 Agent）、`POST /end`（只允许 idle 关闭）。P1页面沿用 STT/D10，`/end` 退出后清空老前端 Session ID，不声称清理 Session.v4/派生索引/备份。人设文件 `app/companion_persona.txt`；只有显式 `DSH_LIVE_ENABLE_P1_PERSONA=1` 才注入本项目 Agent scoped `systemPrompt.section`。保持原有模型/工具 Guard 与真正原生 requestHeader 的模型确认，不调用全局 selectModel。

## 手动记忆 API 与人格成长审核（`memory-manage`）

**默认全部关闭**。可选 `DSH_LIVE_ENABLE_MANUAL_MEMORY=1`、`DSH_LIVE_MANUAL_MEMORY_DIR=<项目内绝对0700目录>` 和 `DSH_LIVE_MEMORY_ADMIN_TOKEN=<另一独立32–256字符密钥>`，才开放 `POST /dsh-live-bridge/memory-manage`。需旧 Bridge Bearer、额外请求头 `x-dsh-live-memory-token` 和回环访问。JSON `{protocolVersion:1,action:"list"|"read"|"export"|"consent"|"put"|"remove"}`；`consent` 带 `allow` 布尔和 `confirm:"MANUAL_MEMORY_CONSENT"`，`put` 带 `text`、可选 `id`、`expectedRevision`（创建默认为null），`remove` 带 `id,expectedRevision,confirm:"DELETE_THIS_FACT"`。存储为跨重启私有 Markdown，权限与 hash 完整性校验；不允许自动提炼，**不与 ReMe 索引互通**，只能由受信人类管理界面调用，不能把 Admin Token 发给模型或 ESP32。

`lib/privacy-maintenance.js` 提供隔离研究专用 `planFixtureRetention` 与 `executeFixtureRetention`；故意要求项目忽略的 `tmp/c2-s3-e1b-isolated/<真实专用测试夹具>` 与显式 marker/revision/测试确认，只能清理虚构测试文件，**不是对真实 DSH_HOME 的清理接口**。

## 受限 ReMe 检索 + 可选跨重启恢复

**当前所有新特性默认关闭，按需在独立 DSH Profile 中启用。** 官方 ReMe DSH 插件仍负责提供记忆指引；本插件在自身 Agent scope **Shadow** 同名 `reme_search`，不暴露该 ReMe 全局工具。真正模型 `request/header` 中仅允许 scoped `reme_search` 和 `dsh_live_read_volume`。为了让本项目 Agent 永远只看到固定权能，仍为 `tools.restrict({allow:[]})` + 单调 `guard`，不为了检索放开继承工具。

需显式 `DSH_LIVE_ENABLE_MAC_READONLY_TOOL=1`、`DSH_LIVE_ENABLE_REME_SEARCH=1`、`DSH_LIVE_REME_URL=http://127.0.0.1:<独立端口>`；ReMe 服务**必须自己占有项目私有工作区**且仅本机监听，无外部 Bearer 鉴权不能用于共享环境。检索为只读、限定输入/结果大小、5秒超时；错误返回不可用，不能把外部历史当作工具授权。

需显式 `DSH_LIVE_ENABLE_SESSION_RECOVERY=1`、`DSH_LIVE_STATE_DIR=<项目工作区内绝对私有路径>` 才启用有锁私有绑定账本（`bindings-v1.json`，不进 Git）。保持原生 DSH Session 作为历史唯一权威；恢复旧 `conversation_id` 时调用 `ctx.agents.resume`，使用当前 Session 模型事件/保存路由而非全局默认；保存 turn 的 SHA-256 摘要+最终回执，不另存用户原始 prompt。重启后旧 `turn_id` 幂等、旧 `task_id` 最终结果可查，未证实结果返回 `turn_outcome_unknown`，`/session` 初次查询标注 `pending_resume`。默认恢复窗口 30 天，0 表示下次进程不恢复、改建 Session。

## 会话绑定与局部模型选择

`POST /submit` 支持可选 `conversation_id`（8–64 字母数字/下划线/连字符）；相同 conversation 顺序多轮共用真正 Agent/Session；无此字段仍采用旧 v0.3 独立任务行为。新增需原有 loopback+独立 Bearer Token 的：

- `POST /dsh-live-bridge/session`：`{protocolVersion:1,conversation_id:"whale_session_001"}`，返回当前本 Session scoped `selected`（下轮模型）、真实 `requestHeader` 对应 `last_request`、`pending_next_request` 和 busy。
- `POST /dsh-live-bridge/model`：`{protocolVersion:1,conversation_id:"whale_session_001",model:"deepseek-pro"}`；只能变更本绑定 Session 的同 Provider 模型。Harness `llm.resolveCallConfig` 验证后才将 `model/selection` 写该 Session 并更新官方 `installModelSelection` scoped route；未发新请求时显示下轮生效，失败 422 不改模型，忙时 409 不切换。**不调用会异步改全局默认值的原生 `sessionController.selectModel`**。Token 不得放到前端/ESP32。任务/工具仍按 `task_id` 原生事件核对，不自动批准工具。

位置为 Deepseek-live 项目内 `plugins/dsh-live-bridge/`；仅调用 Harness `webServer`、`agents`、`agentDefaultModel`、`llm`、原生 Agent 模型选择/Session 事件/取消；不依赖 dsh-desktop-bridge、DSH Desktop 私有 API、桌面 Token、另起自制 Harness。

## 仅作用于本项目 Agent 的 Mac 只读工具

只有显式配置 `DSH_LIVE_ENABLE_MAC_READONLY_TOOL=1` 才启用 `lib/mac-readonly.js`。新建 Agent 时通过官方 `agentCtx.tools.register` **作用域注册** `dsh_live_read_volume`，仅允许读取固定项目根目录所在卷的总容量/可用容量；参数对象必须为空，不接受任意路径、Shell、用户文件内容或写操作。同步使用官方 `tools.restrict({allow:[]})` 隐藏全部继承工具、`tools.guard` 单调拒绝其余工具调用，单次回复上限 512 tokens。若缺少任何 Agent 作用域工具限制能力，则**创建失败而非扩大权限**。不开启此环境标志时保留此前 Bridge 的协议行为，仍不得把普通 Agent 当成可信受限工具执行器。

复用现有凭据仅通过隔离 Harness 的 **官方 `credentials-local` Provider**读取，不由本插件读取/存储 Key。当前插件可按 `conversation_id` 绑定 Session 并切换会话模型；未提供 conversation_id 的 `/submit` 继续逐 turn 新建。

## 原生工具继承与联网搜索

`DSH_LIVE_TOOL_MODE=native` 明确选择正常产品 Agent 的**原生工具继承**：不添加自己的全局工具白名单、搜索次数限制或额外审批引擎，沿用 Host/Agent 已有的 Harness 权限和原生审批。只有这个模式的 Agent 支持 `/search` 对官方 `web_search` 与可用的 `web_fetch` 按 Session 关闭/开启：关闭通过 `agentCtx.tools.restrict({deny:...})`，打开撤销当前 Agent 掩码，开关前必须空闲且同会话拥有者已验证；没有搜索工具时不假装成功。网页和本地 STT 指令共享该 Session 真相。若已启用会话持久化账本，仅存储布尔偏好，无密钥或提示词。

该模式与 `DSH_LIVE_ENABLE_MAC_READONLY_TOOL=1` **互斥**；后者保留早期有限只读测试策略与最多两次搜索的历史兼容逻辑，不能误认为正式产品默认能力。切换开关不会触发调用，上游搜索仍可能收费，敏感工具仍需 Harness 批准。

## 主 DSH Profile 直接接入

插件支持通过 DSH 官方插件管理器安装本地包，并在选定的 Cordis Profile 为该插件设置 `workspaceRoot`、`bridgeTokenFile`、`toolMode: native`、`visibleModels`（逗号分隔模型名）、`companionFacts` 和 `companionPersona`。也兼容旧版环境变量模式。

- `bridgeTokenFile` 指向管理员单独准备的 Bearer Token 文件，必须为拥有者私有的普通文件（权限 0600），不应使用 DSH 模型 API Key 或项目 Git 跟踪文件；`workspaceRoot` 必须是实际项目绝对目录。
- `bridgeTokenFile` 只读取专为 Bridge 创建的用户私有文件，不读取或复制 DSH 的 DeepSeek API 凭据。真实 Agent 请求使用该 Profile 当前的 provider/model 路由；`POST /models` 只调用 `ctx.llm.resolveCallConfig` 验证候选路由，不发起模型请求。
- Profile 修改和加载应通过 [`scripts.install_host`](../../docs/INSTALL_MAC.md) 或 DSH 官方管理器，并遵循该 Host 的进程/会话保护政策。健康接口未注册时 `/dsh-live-bridge/health` 返回 404；不要擅自重启繁忙 Host。

## 安全与 HTTP 契约

宿主进程需配置独立 Bridge Token（32–256字符）与工作区根目录。可用 `bridgeTokenFile` 让插件从 owner-only 文件读取专用 Token，也兼容 `DSH_LIVE_BRIDGE_TOKEN` 和 `DSH_LIVE_WORKSPACE_ROOT`；插件不会生成 Token、读取或复制 DSH 的模型 API Key，也没有缺省启用 Token。只允许来自 loopback 的 HTTP；敏感 POST 端点需 Bearer 鉴权，不向前端/ESP32 暴露 Token。

| 端点 | 结果 |
| --- | --- |
| `GET /dsh-live-bridge/health` | 无敏感信息的版本和 configured 标志 |
| `POST /dsh-live-bridge/submit` | `{protocolVersion:1,turn_id,prompt,conversation_id?}`；202 仅受理、绝非成功 |
| `POST /dsh-live-bridge/session` | `{protocolVersion:1,conversation_id}`；返回 Session 原生下轮选型与最近真实请求模型 |
| `POST /dsh-live-bridge/model` | `{protocolVersion:1,conversation_id,model}`；只切本 Session 同 Provider 模型，校验成功后下轮生效 |
| `POST /dsh-live-bridge/search` | `{protocolVersion:1,conversation_id,enabled?}`；无 enabled 则查询本 Agent 搜索能力，有 boolean 则空闲时变更当前 Session 搜索掩码；不调用 LLM |
| `POST /dsh-live-bridge/result` | `{protocolVersion:1,task_id}`；获取当前记录 |
| `POST /dsh-live-bridge/cancel` | 同 result 参数；仅向本轮原生 Agent 发出 `cancel({kind:'user'})`；202 为 **cancel_requested**，不是已取消；真正 `cancelled` 需 `turn/end.reason.kind=aborted` 和 idle。若 Host 无 `cancel()`，501 不冒充成功。 |

POST 都要求 token 与回环地址。提交仅接收 8–64 位 `turn_id`、最多 4000 字符文本，报文 16KB；拒绝指定 cwd/provider/model/shell/审批决议。当前单进程 16 active、256 total；`turn_id` 的幂等映射**不跨重启持久化**，重启/断线后禁止客户端盲目重投递。

## 完成判定（隔离真 Harness 的项目 Mac 只读工具已验证）

- `agent/status=idle`、同 Session 的 `assistant/message` 与 `turn/end.reason.kind=completed` **必须同时出现**；只得到文字→`answered`、`execution_verified=false`，不能称电脑任务成功。
- 出现 `tool/call` 时：每个 `data.callId` 必须配对 `tool/result.data.message.toolCallId`（原生 V4 顶层 `role=tool,source={kind:tool,callId},isError=false`），旧版嵌套 `content[0].toolCallId` 另有保守兼容分支；此后还须有最终 assistant 文字。缺失、来源身份不匹配、未配对或等待中的回执保持 `awaiting_result`，绝不自动当成功。
- 原生 tool 回执全部成功且正常结轮→`completed`、`result.execution_verified=true`、`source=harness_tool_events`；只反映 Harness **工具调用边界报告成功**，**不替代外部系统的业务成功确认**。只返回工具名称和成功/失败标志，不外泄工具调用参数、原始结果正文或密钥。
- 任一工具失败或 `turn/end` 为 blocked/error/max-tokens→`failed`；aborted→`cancelled`；未收到结轮及 idle 不落最终成功。原 `approval/request` 审批由 Harness 负责，插件不注册代答接口，也不自动审批。
- `cancel_requested` 后不释放执行归属，等原生结轮；如果收到 completed 而非 aborted，仍按实际执行记录结算，不伪称取消生效。

**仍未解决**：正式 Harness Desktop 0.5.0 的兼容性；长时间无事件的超时/撤销确认；跨重启 Session 绑定、任务恢复与幂等；真实审批；大肥鱼正式 P1 语音/UI、OmniVoice/Live2D/ESP32 联动。**真实 DeepSeek 与 Mac 项目卷只读工具在隔离 CLI 已验证**，但尚不能冒称最终用户界面已集成或任意电脑操作均可成功。

## 不收费的离线测试

```bash
cd path/to/Deepseek-live/plugins/dsh-live-bridge
npm run check
```

`npm run check` 仅运行静态语法、Fake Host 和只读工具单测，现有自动测试覆盖协议、Session、记忆、V4 工具、Companion Facts 与安全边界；请以当前 `npm run check` 实际输出为准；调用该命令**不会触发付费 API**。另经用户授权，已经在隔离官方 Harness 中真实执行**一次** `deepseek-official/deepseek-flash` 付费模型任务与本机项目卷只读统计，并拿回原生成功回执。正式 Desktop 0.5.0、原生权限审批及跨重启会话恢复仍未验证；长寿命会话与会话级模型切换已在隔离 CLI 的确定性双模型下通过。

原生事件依据（对应当前上游公开文档）：[Session 事件](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/session.md)、[Agent cancel](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/core.md)。


### Official Web-only agent preset

For a DSH Profile that has installed and enabled this bundle, opt in with
`webPresetId: deepseek-live-web` in its **own** Bridge configuration alongside
`toolMode: native`. The bundle declares one scoped official Agent preset
containing only `@deepseek-ai/dsh-tool-web` (`web_search`/`web_fetch`).
The Bridge mounts that preset via the official `agentPresets.mount()` contract
*before* querying `tools.schemas(agent)` and installing its per-session
default-deny search toggle. No standard/coding preset tools, separate web
credential, host-wide tool toggle or automatic search request are added.
The same DSH credentials service supplies the `DEEPSEEK_API_KEY` reference
to the conversation and official search provider; searches may bill an
additional model request.
