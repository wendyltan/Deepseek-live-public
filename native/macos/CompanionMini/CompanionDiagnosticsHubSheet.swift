// SPDX-License-Identifier: MIT
// R123 read-only diagnostics hub. No USB takeover, microphone start,
// firmware writes, DSH submission or private transcript/log exposure.
import AppKit
import SwiftUI

struct CompanionDiagnosticsHubSheet: View {
    @ObservedObject var store: CompanionStore
    var embedded:Bool = false
    @Environment(\.dismiss) private var dismiss
    let openPixels: () -> Void
    let openMotions: () -> Void
    let openVoice: () -> Void

    @State private var wifiStatus:VerifiedWiFiGateway? = nil
    @State private var copied = false
    @State private var showServiceRepair = false
    @State private var showAudioDetails = false

    private var sessionFresh: Bool {
        guard let s = store.snapshot, s.session_verified == true else { return false }
        let age = Date().timeIntervalSince1970 - s.updated_at_unix
        return age >= -5 && age < 30
    }

    private var usbPortDetected: Bool {
        ESPUSBSerialPresence.detected
    }

    private func statusRow(_ label:String,_ ok:Bool,_ validText:String,_ badText:String) -> some View {
        HStack(spacing:12) {
            Image(systemName:ok ? "checkmark.circle.fill":"exclamationmark.circle")
                .foregroundStyle(ok ? Color.green:Color.orange)
                .font(.system(size:15))
            VStack(alignment:.leading,spacing:3) {
                Text(label).font(.system(size:13,weight:.medium))
                Text(ok ? validText:badText)
                    .font(.system(size:11)).foregroundStyle(.secondary)
                    .fixedSize(horizontal:false,vertical:true)
            }
            Spacer()
        }
        .padding(.vertical,6)
    }

    private var diagnosticSummary: String {
        // Never copy session IDs, SSIDs, API keys, conversation history, audio,
        // or raw logs. Only locally verified capability flags.
        let lines=[
            "大肥鱼 Mac 诊断摘要（不含会话内容）",
            "USB端口：" + (usbPortDetected ? "已检测到":"未检测到"),
            "ESP32协议握手：" + (sessionFresh && store.espVerified ? "已验证":"未验证"),
            "官方DSH同会话：" + (sessionFresh && store.bothVerified ? "已验证":"未验证"),
            "本地Qwen：" + (store.localTTSReady ? "就绪":"未就绪/检测中"),
            "流式PCM2：" + (sessionFresh && store.snapshot?.voice_streaming_enabled == true ? "已开启":"未确认"),
            "SD动作播放能力：" + (store.motionPackageVerified ? "已握手":"未验证"),
            "Wi-Fi自定义唤醒：见无线与唤醒设置的真实授权/运行回执",
            "板载离线WakeNet：" + (sessionFresh && store.snapshot?.wake_capability_verified == true
                                   ? "USB固件能力握手通过":"未核验；不代表Wi-Fi唤醒失败"),
            "设备软件截图：仅在专用窗口按需采集，默认不周期读取",
            "人眼屏幕/人耳音质：未通过此面板验证"
        ]
        return lines.joined(separator:"\n")
    }

    private var channelVerified:Bool {
        wifiStatus?.connected == true || (sessionFresh && store.bothVerified)
    }
    private var connectionSymbol:String {
        if wifiStatus?.connected == true {return "wifi"}
        if sessionFresh && store.bothVerified {return "cable.connector"}
        return "wifi.slash"
    }
    // A single factual headline answers "can I use the fish right now?"
    // Do not infer audio quality or wireless DSH success from a socket.
    private var channelTitle:String {
        if wifiStatus?.connected == true {return "ESP32 无线已连接"}
        if sessionFresh && store.bothVerified {return "ESP32 USB 已连接"}
        if usbPortDetected {return "USB 已检测到，等待握手"}
        return "等待设备连接"
    }
    private var channelDescription:String {
        if let wifiStatus,wifiStatus.connected {return wifiStatus.phaseDescription}
        if sessionFresh && store.bothVerified {
            return "板端与 Mac 的会话已经验证"
        }
        return "当前没有新鲜的可信语音连接回执"
    }

    private func quickStatus(_ symbol:String,_ title:String,_ value:String,
                             verified:Bool?=nil) -> some View {
        HStack(alignment:.center,spacing:9) {
            Image(systemName:symbol)
                .font(.system(size:14,weight:.medium))
                .foregroundStyle(verified == false ? Color.orange : Color.secondary)
                .frame(width:18)
            VStack(alignment:.leading,spacing:3) {
                Text(title)
                    .font(.system(size:11,weight:.medium))
                    .foregroundStyle(.secondary)
                Text(value)
                    .font(.system(size:13,weight:.medium))
                    .lineLimit(2)
                    .fixedSize(horizontal:false,vertical:true)
            }
            Spacer(minLength:0)
        }
        .accessibilityElement(children:.combine)
    }

    private var connectionOverview:some View {
        VStack(alignment:.leading,spacing:17) {
            HStack(alignment:.center,spacing:16) {
                Image(systemName:connectionSymbol)
                    .font(.system(size:27,weight:.regular))
                    .foregroundStyle(channelVerified ? Color.accentColor : Color.secondary)
                    .frame(width:42,height:42)
                    .background(Color.primary.opacity(0.055),
                                in:RoundedRectangle(cornerRadius:11))
                    .accessibilityHidden(true)
                VStack(alignment:.leading,spacing:5) {
                    Text(channelTitle)
                        .font(.system(size:21,weight:.semibold))
                    Text(channelDescription)
                        .font(.system(size:13))
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal:false,vertical:true)
                }
                Spacer(minLength:0)
            }
            Rectangle()
                .fill(Color.primary.opacity(0.09))
                .frame(height:1)
                .accessibilityHidden(true)
            LazyVGrid(columns:[GridItem(.adaptive(minimum:155),alignment:.leading)],
                      alignment:.leading,spacing:14) {
                quickStatus("cable.connector","USB 端口",
                            usbPortDetected ? "已检测到" : "未检测到",
                            verified:usbPortDetected)
                quickStatus("server.rack","官方 DSH",store.dshServiceState)
                quickStatus("waveform","本地语音合成",
                            store.localTTSReady ? "已就绪" : "尚未就绪",
                            verified:store.localTTSReady)
            }
        }
        .padding(20)
        .frame(maxWidth:.infinity,alignment:.leading)
        .background(Color(nsColor:.controlBackgroundColor),
                    in:RoundedRectangle(cornerRadius:15))
        .accessibilityIdentifier("r457-diagnostics-connection-overview")
    }

    private var wirelessControls:some View {
        VStack(alignment:.leading,spacing:12) {
            HStack {
                Text("无线与唤醒")
                    .font(.system(size:16,weight:.semibold))
                Spacer()
                Text("设备麦克风")
                    .font(.system(size:11))
                    .foregroundStyle(.secondary)
            }
            WiFiGatewayStatusView(live:$wifiStatus,embedded:true)
                .frame(maxWidth:.infinity,alignment:.leading)
        }
        .padding(.top,4)
    }

    private var advancedDiagnostics:some View {
        VStack(alignment:.leading,spacing:0) {
            HStack(spacing:9) {
                Text("深入检查")
                    .font(.system(size:16,weight:.semibold))
                Spacer()
                Text("出现异常时使用")
                    .font(.system(size:11))
                    .foregroundStyle(.secondary)
            }
            .padding(.bottom,14)
            DisclosureGroup(isExpanded:$showServiceRepair) {
                VStack(alignment:.leading,spacing:12) {
                    Text("只有需要恢复服务时才操作。无线通话期间不会重连 USB。")
                        .font(.system(size:12))
                        .foregroundStyle(.secondary)
                    CompanionServiceControlsView(store:store,compact:true)
                        .frame(maxWidth:.infinity,alignment:.leading)
                }
                .padding(.top,12)
            } label: {
                advancedLabel("后台服务与恢复","server.rack")
            }
            Divider().padding(.vertical,13)
            DisclosureGroup(isExpanded:$showAudioDetails) {
                VStack(alignment:.leading,spacing:8) {
                    statusRow("ESP32 实体协议握手",
                              sessionFresh && store.espVerified,
                              "本轮实体协议已确认","没有新的可信实体协议回执")
                    statusRow("PCM2 流式播放",
                              sessionFresh && store.snapshot?.voice_streaming_enabled == true,
                              "本轮增量传输模式已确认","当前模式尚未验证")
                    statusRow("SD 动画",store.motionPackageVerified,
                              "板端播放能力已握手","播放能力尚未验证")
                    if sessionFresh &&
                       store.snapshot?.wake_capability_verified == true {
                        statusRow("板端离线唤醒协议",true,
                                  "USB 固件能力已确认",
                                  "")
                    }
                    Text("「你好大肥鱼」的 Wi-Fi 持续唤醒状态请查看上方开关。它与板端离线 WakeNet 属于不同链路。")
                        .font(.system(size:11))
                        .foregroundStyle(.secondary)
                    Divider()
                    Text("最近一次音频统计")
                        .font(.system(size:12,weight:.semibold))
                    Text(sessionFresh
                         ? ((store.snapshot?.voice_audio_diagnostics?.isEmpty == false)
                            ? String((store.snapshot?.voice_audio_diagnostics ?? "").prefix(240))
                            : "本轮暂未产生完整的音频统计。")
                         : "会话状态已过期；不显示历史统计为当前结果。")
                        .font(.system(size:12))
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                    Text("传输数据不能证明人耳音质或真实屏幕画面。")
                        .font(.system(size:11))
                        .foregroundStyle(.secondary)
                }
                .padding(.top,12)
            } label: {
                advancedLabel("声音与动画","waveform.path")
            }
        }
        .padding(.top,4)
        .accessibilityIdentifier("r457-diagnostics-advanced")
    }

    private func advancedLabel(_ title:String,_ symbol:String) -> some View {
        Label {
            Text(title).font(.system(size:13,weight:.medium))
        } icon: {
            Image(systemName:symbol)
                .frame(width:19)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth:.infinity,alignment:.leading)
        .contentShape(Rectangle())
    }

    var body:some View {
        VStack(alignment:.leading,spacing:0) {
            HStack(spacing:12) {
                Text("设备诊断")
                    .font(.system(size:20,weight:.semibold))
                Spacer(minLength:12)
                if !embedded {
                    Button("关闭"){dismiss()}
                }
            }
            .padding(.horizontal,embedded ? 26 : 18)
            .padding(.top,embedded ? 22 : 16)
            .padding(.bottom,15)
            Divider()
            ScrollView {
                VStack(alignment:.leading,spacing:26) {
                    connectionOverview
                    wirelessControls
                    Divider()
                    advancedDiagnostics
                }
                .frame(maxWidth:760,alignment:.leading)
                .padding(.horizontal,embedded ? 26 : 18)
                .padding(.vertical,22)
                .frame(maxWidth:.infinity,alignment:.center)
            }
            Divider()
            HStack(spacing:12) {
                Button("查看设备软件画面"){openPixels()}
                    .help("只有打开专用窗口并请求USB单帧截图才会读取设备，不显示历史缓存为实时画面。")
                Button("语音说明"){openVoice()}
                if !embedded {
                    Button("动画素材库"){openMotions()}
                }
                Spacer(minLength:8)
                Button {
                    NSPasteboard.general.clearContents()
                    copied=NSPasteboard.general.setString(diagnosticSummary,forType:.string)
                } label: {
                    Label(copied ? "已复制摘要":"复制诊断摘要",
                          systemImage:copied ? "checkmark":"doc.on.doc")
                }
                .help("仅复制已验证状态和能力，不含录音、会话和密钥")
            }
            .buttonStyle(.bordered)
            .controlSize(.regular)
            .padding(.horizontal,embedded ? 26 : 18)
            .padding(.vertical,12)
        }
        .frame(width:embedded ? nil : 620,height:embedded ? nil : 655)
        .frame(maxWidth:embedded ? .infinity : nil,
               maxHeight:embedded ? .infinity : nil,
               alignment:.topLeading)
        .background(Color(nsColor:.windowBackgroundColor))

    }

}
