# 参与 Deepseek-live 贡献

欢迎为 **Deepseek-live（大肥鱼）** 提交 Issue、文档改进或 Pull Request！本项目自有源码采用 **MIT License** 开源（详见 [LICENSE](LICENSE) 与 [许可范围](LICENSE_SCOPE.md)）；第三方角色动画、字体字形与上游模型权重沿用各自原许可证。

## 提交 Issue 前

建议先查阅 [README](README.md)、[系统架构](docs/ARCHITECTURE.md)、[Mac 安装指南](docs/INSTALL_MAC.md) 与 [故障排查](docs/TROUBLESHOOTING.md)。

提交问题时请尽量附上：开发板型号、macOS 与工具链版本、连接方式（USB 或 Wi-Fi）、复现步骤及错误日志。请注意脱敏，**不要在公开 Issue 中贴出 API Key、设备证书、Token、个人对话记录或隐私截图**。

## 贡献流程

1. 从最新主分支拉取自己的功能分支，保持每个 PR 聚焦一个明确目标。
2. 优先复用官方 DSH、ESP-IDF 与 Pinky 的标准接口；若引入新插件或依赖，请在说明中标明版本、许可证与所需系统权限。
3. 自动化单测默认使用离线模拟桩（Mock/Fake），避免在 CI 中触发真实模型调用、手机操作或硬件烧录；如需在真机验证，请在 PR 中说明实测步骤与设备环境。
4. 构建或测试 Mac App 时请输出到独立的 `.app` 路径，避免覆盖正在运行的应用实例。
5. 若修改网关或固件连接逻辑，请保持同一时刻仅由 USB 或 Wi-Fi 单一通道管理实体设备会话。
6. 提交前请确保文档链接检查、隐私扫描与相关单元测试全部通过。

## 本地离线检查

```bash
python3.12 -m scripts.install_host device-plan
python3.12 -m scripts.r658_docs_check --strict
python3.12 -m unittest -q tests.test_r658_portable_installer tests.test_r659_plugin_manager
node --check plugins/dsh-live-bridge/lib/index.js
```

涉及 Apple Silicon 的检查在其他平台上会自动跳过；提交 PR 无需附带个人音频、设备证书或真机录像，如某项真机条件未覆盖，请在 PR 中如实说明测试范围即可。

## 代码与文档风格

保持实现简洁清晰：优先保障实体设备与桌面交互体验、支持失败安全回退、遵循数据最小化原则，避免在默认路径触发非预期的模型计费调用。
