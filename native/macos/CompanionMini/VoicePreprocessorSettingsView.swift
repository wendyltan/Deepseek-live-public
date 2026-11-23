import Foundation
import SwiftUI

// R212: local-only setting for the separate spoken-summary pipeline.
// This file is independent of Taylor's screen/navigation redesign.
struct VoicePreprocessorSettingsView: View {
    @State private var enabled = false
    @State private var supported = false
    @State private var loaded = false
    @State private var notice = ""
    private let statusURL = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/Deepseek-live/companion-native/status.json")
    private let configURL = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/Deepseek-live/companion-native/voice-preprocessor-r218.json")

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Toggle("长回复自动精简后再朗读", isOn: $enabled)
                .disabled(!supported)
                .onChange(of: enabled) { _, newValue in
                    guard loaded && supported else { return }
                    save(newValue)
                }
            Text(supported ? "优先独立 DeepSeek Flash 精简长回复；原文留在近期对话。" : "独立 Flash 会话暂不可用；若已开启精简，失败时使用本地原文摘录，保留完整正文。")
                .font(.system(size: 11)).foregroundStyle(.secondary)
            if let data=try? Data(contentsOf:statusURL),data.count<32768,
               let obj=try? JSONSerialization.jsonObject(with:data) as? [String:Any],
               let result=obj["voice_preprocessor_last"] as? String {
                Text(result=="applied" ? "上一条长回复：Flash 精简已成功" :
                     result=="local_digest" ? "上一条长回复：Flash 未成功，采用本地重点摘录" :
                     result=="fallback" ? "上一条长回复：Flash 未成功，保留原文" :
                     "上一条回复未触发 Flash")
                    .font(.system(size:11,weight:.medium))
                    .foregroundStyle(result=="applied" ? .green : .secondary)
            }
            Text("仅在开启时请求一次独立 Flash，可能额外消耗额度。不可用则本地提取原文前段并提示到 Mac 查看表格；不伪造 Flash 成功，也不修改原始答案。")
                .font(.system(size: 11)).foregroundStyle(.secondary)
            if !notice.isEmpty {
                Text(notice).font(.system(size: 11)).foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .onAppear { load() }
        .onReceive(Timer.publish(every: 3, on: .main, in: .common).autoconnect()) { _ in
            verifyCapability()
        }
    }

    private func verifyCapability() {
        guard let data=try? Data(contentsOf:statusURL),
              data.count<=32768,
              let obj=try? JSONSerialization.jsonObject(with:data) as? [String:Any],
              obj["session_verified"] as? Bool == true,
              obj["voice_preprocessor_supported"] as? Bool == true,
              let changed=obj["updated_at_unix"] as? Double,
              Date().timeIntervalSince1970-changed < 15,
              changed<=Date().timeIntervalSince1970+5 else {
            supported=false
            return
        }
        supported=true
    }

    private func load() {
        defer { loaded = true }
        verifyCapability()
        guard let bytes = try? Data(contentsOf: configURL),
              let data = try? JSONSerialization.jsonObject(with: bytes) as? [String: Any],
              data["schema"] as? Int == 1,
              let choice = data["enabled"] as? Bool else {
            enabled = false // Explicit opt-in: never auto-charge on first install.
            return
        }
        enabled = choice // Keep the real saved opt-in visible even if Flash capability is down.
    }

    private func save(_ choice: Bool) {
        guard supported else { enabled=false; return }
        do {
            let directory = configURL.deletingLastPathComponent()
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                                                    attributes: [.posixPermissions: 0o700])
            let raw = try JSONSerialization.data(withJSONObject:
                ["schema": 1, "enabled": choice, "model": "deepseek-flash"], options: [])
            try raw.write(to: configURL, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600],
                                                  ofItemAtPath: configURL.path)
            notice = choice ? "已允许长回复调用一次独立 Flash 生成朗读稿；可能额外消耗模型额度" :
                              "已关闭，将朗读原始回答"
        } catch {
            enabled = !choice
            notice = "无法安全保存设置，未更改语音服务"
        }
    }
}
