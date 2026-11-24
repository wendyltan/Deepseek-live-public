// SPDX-License-Identifier: MIT
import AppKit
import Combine
import SwiftUI

// Native Preferences uses the same live store and existing preference keys.
// It does not open the microphone, mutate NVS, or fake unavailable wake models.
struct CompanionPreferencesView:View {
    @ObservedObject var store:CompanionStore
    @AppStorage("dafeiyu.r32.idleSeconds") private var idleSeconds=90
    @State private var showWake=false
    @State private var showMemory=false
    var embedded:Bool = false
    var openDiagnostics:(() -> Void)? = nil
    var openMemory:(() -> Void)? = nil
    var body:some View {
        Form {
            Section("会话") {
                LabeledContent("当前模型",value:store.modelLabel)
                HStack(spacing:9) {
                    Button("Flash"){store.requestModel("deepseek-flash")}
                    Button("Pro"){store.requestModel("deepseek-v4-pro")}
                    Spacer()
                    Text("仅在DSH确认后生效")
                        .foregroundStyle(.secondary)
                        .font(.system(size:11))
                }
                .disabled(!store.bothVerified || store.snapshot?.phase != "idle")
                if !store.modelChangeNotice.isEmpty {
                    Text(store.modelChangeNotice)
                        .font(.system(size:11)).foregroundStyle(.secondary)
                }
                HStack {
                    LabeledContent("联网搜索",value:store.activeSearch)
                    Button(store.snapshot?.search_enabled == true ? "关闭搜索" : "开启搜索") {
                        store.toggleSearch()
                    }
                    .disabled(!store.bothVerified ||
                              store.snapshot?.search_supported != true)
                }
                if !store.searchChangeNotice.isEmpty {
                    Text(store.searchChangeNotice)
                        .font(.system(size:11)).foregroundStyle(.secondary)
                }
            }
            Section("电脑操作权限") {
                R676ComputerPreconsentSettings()
            }
            Section("记忆") {
                Text("日常对话生成审核建议、手动添加以及已保存记忆，在同一页面管理。")
                    .font(.callout).foregroundStyle(.secondary)
                Button("管理记忆建议与手动添加") {
                    if let openMemory {openMemory()}
                    else {showMemory=true}
                }
            }
            Section("桌宠") {
                Picker("本地待机动作间隔",selection:$idleSeconds) {
                    Text("关闭").tag(0)
                    Text("60秒").tag(60)
                    Text("90秒").tag(90)
                    Text("120秒").tag(120)
                }
            }
            Section("设备与语音") {
                LabeledContent("拾音来源",value:"ESP32板载麦克风")
                Button("连接、持续唤醒与后台服务") { openDiagnostics?() }
                    .disabled(openDiagnostics == nil)
                VoicePreprocessorSettingsView()
                Button("查看板载唤醒能力"){showWake=true}
                Text("唤醒设置由当前设备配对与网关回执确认；真实声学效果仍需人工验收。")
                    .font(.system(size:11)).foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .padding(14)
        .frame(minWidth:embedded ? nil : 500,minHeight:embedded ? nil : 540)
        .sheet(isPresented:$showWake) {
            ESPWakeSettingsSheet(isPresented:$showWake,
                 hardwareReady:store.snapshot?.wake_capability_verified == true)
        }
        .sheet(isPresented:$showMemory) {
            MemoryOverviewSheet(isPresented:$showMemory)
        }
    }
}

struct CompanionVoiceGuideView:View {
    @ObservedObject var store:CompanionStore
    @Environment(\.dismiss) private var dismiss
    var body:some View {
        VStack(alignment:.leading,spacing:14) {
            HStack {
                Text("实体语音说明").font(.title2.weight(.semibold))
                Spacer()
                Button("关闭"){dismiss()}
            }
            LabeledContent("连接状态",value:VerifiedWiFiGateway.read()?.connected == true ?
                           "ESP32无线已鉴权" :
                           store.bothVerified ? "ESP32与DSH已验证" : "尚未验证")
            LabeledContent("语音通道",value:VerifiedWiFiGateway.read()?.connected == true ?
                           "Wi-Fi / WSS（以网关回执为准）" :
                           store.snapshot?.voice_streaming_enabled == true ?
                           "设备PCM2流式" : "尚未确认")
            Divider()
            Text("触摸模式下由ESP32开始或结束拾音；无线唤醒需通过真人验收。Mac不使用内建麦克风，也不会因打开这个页面自动录音。")
            Text("当前可用：询问时间、基础帮助、经过DSH验证的问答和经确认的会话模型选择。")
            Text("无线自定义唤醒与连续对话请以当前实机验收结果为准；Mac不会使用自身麦克风。")
                .foregroundStyle(.secondary)
            Spacer()
        }
        .padding(24)
        .frame(width:530,height:355)
    }
}
