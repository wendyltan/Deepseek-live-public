import Foundation
import Combine
import SwiftUI

// R316: private Mac-only gateway receipt. This is a read-only summary of
// authenticated WSS events; it is not proof of ESP32 pixels or audible sound.
struct VerifiedWiFiGateway: Decodable {
    let schema:Int
    let transport:String
    let active_devices:Int
    let pending_dsh_jobs:Int
    let completed_verified_dsh_offers:Int
    let updated_at_unix:Double
    let server_protocol_ping_enabled:Bool
    let prewake_enabled:Bool?
    let device_phase:String?
    let phase_changed_at_unix:Double?

    // UI only: the heartbeat timestamp is intentionally excluded, otherwise
    // each 1s ping repaints every SwiftUI layout even with no state change.
    // Freshness is still independently checked by read() on each tick.
    func sameVisibleStatus(as other:VerifiedWiFiGateway) -> Bool {
        return transport==other.transport &&
            active_devices==other.active_devices &&
            pending_dsh_jobs==other.pending_dsh_jobs &&
            completed_verified_dsh_offers==other.completed_verified_dsh_offers &&
            server_protocol_ping_enabled==other.server_protocol_ping_enabled &&
            prewake_enabled==other.prewake_enabled &&
            device_phase==other.device_phase &&
            phase_changed_at_unix==other.phase_changed_at_unix
    }
    var connected:Bool {
        active_devices == 1 && device_phase != nil &&
        device_phase != "connecting" && device_phase != "disconnected"
    }
    var phaseDescription:String {
        guard connected else {
            return pending_dsh_jobs == 1 ? "设备已断开 · 后台任务尚在收尾" : "没有正在进行的无线会话"
        }
        switch device_phase {
        case "connecting": return "正在验证无线连接"
        case "prewake_streaming": return "已鉴权 · 待机唤醒监测"
        case "idle": return "已鉴权 · 等待说话"
        case "recording": return "正在录音"
        case "processing": return "正在识别或等待回答"
        case "audio_ready": return "音频已就绪 · 等待设备播放"
        case "speaking": return "设备已报告开始播放"
        case "error": return "本轮出现错误 · 查看设备诊断"
        default: return "已连接 · 语音阶段尚未确认"
        }
    }

    static func read() -> VerifiedWiFiGateway? {
        let root=FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Deepseek-live/lan-pairing")
        let file=root.appendingPathComponent("lan-gateway-status.json")
        guard let attrs=try? FileManager.default.attributesOfItem(atPath:file.path),
              let mode=attrs[.posixPermissions] as? NSNumber,
              mode.intValue & 0o077 == 0,
              let owner=attrs[.ownerAccountID] as? NSNumber,
              owner.intValue == Int(getuid()),
              let size=attrs[.size] as? NSNumber,
              size.intValue > 0 && size.intValue < 4096,
              let flags=try? file.resourceValues(forKeys:[.isRegularFileKey,.isSymbolicLinkKey]),
              flags.isRegularFile == true, flags.isSymbolicLink != true,
              let data=try? Data(contentsOf:file),
              let result=try? JSONDecoder().decode(VerifiedWiFiGateway.self,from:data),
              result.schema==1 && result.transport=="trusted_mac_lan",
              result.updated_at_unix.isFinite,
              result.active_devices >= 0 && result.active_devices <= 1,
              result.pending_dsh_jobs >= 0 && result.pending_dsh_jobs <= 1,
              result.completed_verified_dsh_offers >= 0,
              abs(Date().timeIntervalSince1970-result.updated_at_unix)<15 else {
            return nil
        }
        if let phase=result.device_phase,
           !["connecting","prewake_streaming","idle","recording","processing","audio_ready","speaking",
             "error","disconnected"].contains(phase) { return nil }
        if let changed=result.phase_changed_at_unix,
           (!changed.isFinite || changed>result.updated_at_unix+5 ||
            changed > Date().timeIntervalSince1970+5) { return nil }
        return result
    }
}

// R448: one read-only transport selection contract for floating and manager UIs.
// Wi-Fi requires a fresh authenticated gateway receipt; a serial port alone is
// never evidence of an authenticated conversation.
enum VerifiedCompanionTransport {
    case wifi(VerifiedWiFiGateway)
    case usb
    case unavailable

    static func resolve(usbVerified:Bool, wifi:VerifiedWiFiGateway?) -> Self {
        if let wifi, wifi.connected { return .wifi(wifi) }
        if usbVerified { return .usb }
        return .unavailable
    }

    var isWiFi:Bool {
        if case .wifi = self { return true }
        return false
    }
    var isConnected:Bool {
        switch self {
        case .wifi, .usb: return true
        case .unavailable: return false
        }
    }
    var phaseDescription:String {
        switch self {
        case .wifi(let gateway): return gateway.phaseDescription
        case .usb: return "USB 已验证"
        case .unavailable: return "没有已验证的语音通道"
        }
    }
}

struct WiFiGatewayStatusView: View {
    @Binding var live:VerifiedWiFiGateway?
    @State private var showDetails=false
    var embedded=false

    private var briefConnection:String {
        guard let live else {return "网关状态待确认"}
        if live.connected {return "Wi-Fi 已通过鉴权"}
        if live.active_devices == 1 {return "设备正在等待鉴权"}
        return "没有已连接的无线设备"
    }

    var body:some View {
        VStack(alignment:.leading,spacing:12) {
            if embedded {
                HStack(alignment:.center,spacing:10) {
                    Image(systemName:"wifi")
                        .font(.system(size:16,weight:.medium))
                        .foregroundStyle(live?.connected == true ? Color.accentColor : Color.secondary)
                        .frame(width:19)
                    VStack(alignment:.leading,spacing:4) {
                        Text(briefConnection)
                            .font(.system(size:13,weight:.medium))
                        Text(live?.phaseDescription ??
                             "暂无15秒内的可信网关回执，可能正在使用USB。")
                            .font(.system(size:12))
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal:false,vertical:true)
                    }
                    Spacer(minLength:0)
                }
                .accessibilityElement(children:.combine)
            } else {
                Label("Wi-Fi / WSS",systemImage:"wifi")
                    .font(.system(size:16,weight:.semibold))
                if let live {
                    LabeledContent("Mac Wi-Fi 网关",value:"已启动 · 加密监听中")
                    LabeledContent("ESP32 无线",value:briefConnection)
                    LabeledContent("当前阶段",value:live.phaseDescription)
                } else {
                    LabeledContent("Mac Wi-Fi 网关",value:"未确认运行")
                    LabeledContent("ESP32 无线",value:"连接状态未知")
                }
            }
            PersistentWakeToggleView(gatewayActive:live?.prewake_enabled)
            if let live {
                DisclosureGroup("无线连接详情",isExpanded:$showDetails) {
                    VStack(alignment:.leading,spacing:9) {
                        LabeledContent("最近网关回执",
                           value:"\(max(0,Int(Date().timeIntervalSince1970-live.updated_at_unix))) 秒前")
                        LabeledContent("进行中的任务",
                           value:live.pending_dsh_jobs == 1 ? "1项" : "无")
                        LabeledContent("加密链路",value:"WSS")
                        LabeledContent("协议心跳",
                           value:live.server_protocol_ping_enabled ? "启用" : "暂停")
                        LabeledContent("已发出的语音轮次",
                           value:String(live.completed_verified_dsh_offers))
                        Text("协议回执只能确认通信，不能代替人耳听感和屏幕实拍。")
                            .foregroundStyle(.secondary)
                    }
                    .font(.system(size:12))
                    .padding(.top,8)
                }
                .font(.system(size:12))
            }
        }
        .font(.system(size:13))
        .padding(embedded ? 0 : 16)
        .background(Color.primary.opacity(embedded ? 0 : 0.035),
                    in:RoundedRectangle(cornerRadius:12))
        .onAppear{live=VerifiedWiFiGateway.read()}
        .onReceive(Timer.publish(every:4,on:.main,in:.common).autoconnect()){_ in
            live=VerifiedWiFiGateway.read()
        }
    }

}

// R439: actual persistent user setting, never an optimistic UI-only toggle.
// Each action writes a mode-0600 private preference through the verified
// Python controller. The already authenticated gateway owner supervisor may
// reload it ONLY when no ESP32/DSH session is in flight.
private struct R439WakeSettingReceipt:Decodable {
    let schema:Int
    let configured:Bool
    let requested_on:Bool
    let enabled:Bool
    let eligible:Bool
    let reason:String
}
struct PersistentWakeToggleView: View {
    var gatewayActive:Bool? = nil
    @State private var wanted=false
    @State private var eligible=false
    @State private var busy=false
    @State private var note="读取无线唤醒设置…"

    private nonisolated static func command(_ argument:String) -> R439WakeSettingReceipt? {
        let tool=Process()
        tool.executableURL=URL(fileURLWithPath:CompanionProjectPaths.python)
        tool.arguments=[
            CompanionProjectPaths.script("r439_persistent_prewake_control.py"),
            argument
        ]
        let pipe=Pipe()
        tool.standardOutput=pipe
        tool.standardError=Pipe()
        do {
            try tool.run()
            tool.waitUntilExit()
            guard tool.terminationStatus == 0 else {return nil}
            let data=pipe.fileHandleForReading.readDataToEndOfFile()
            return try? JSONDecoder().decode(R439WakeSettingReceipt.self,from:data)
        } catch {return nil}
    }
    private func apply(_ result:R439WakeSettingReceipt) {
        guard result.schema == 1 else { note="设置回执不受信";return }
        wanted=result.requested_on
        eligible=result.eligible
        let actualGatewayActive=VerifiedWiFiGateway.read()?.prewake_enabled ?? gatewayActive
        if result.requested_on && !result.enabled {
            note="已保存但未生效 · 请核对当前固件与设备配对"
        } else if result.enabled {
            if actualGatewayActive == true {
                note="已启用 · 当前网关正在提供唤醒识别"
            } else {
                note="已启用 · 等待无线网关空闲重载或连接确认"
            }
        } else if actualGatewayActive == true {
            note="已关闭 · 等待当前无线对话结束后重载"
        } else {
            note="已关闭 · 可随时手动开启"
        }
    }
    private func refresh() {
        guard !busy else {return}
        Task.detached(priority:.utility) {
            let result=Self.command("--status")
            await MainActor.run {
                guard !busy else {return}
                if let result {apply(result)}
                else {note="无法核验设置 · 请检查外置盘挂载"}
            }
        }
    }
    private func change(_ newValue:Bool) {
        guard !busy else {return}
        busy=true
        note="正在保存设置…"
        Task.detached(priority:.userInitiated) {
            let result=Self.command(newValue ? "--enable" : "--disable")
            await MainActor.run {
                busy=false
                if let result {apply(result)}
                else {note="保存失败 · 未确认开关变化"}
            }
        }
    }
    var body:some View {
        VStack(alignment:.leading,spacing:5) {
            Toggle(isOn:Binding(get:{wanted},set:{change($0)})) {
                Label("「你好大肥鱼」持续唤醒",systemImage:"waveform.badge.mic")
            }
            .disabled(busy || (!eligible && !wanted))
            .toggleStyle(.switch)
            Text(note)
                .font(.system(size:12))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal:false,vertical:true)
            Text("仅由 ESP32 麦克风识别唤醒词；Mac 麦克风不参与。")
                .font(.system(size:11))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal:false,vertical:true)
            DisclosureGroup("隐私与切换说明") {
                Text("可信设备的声音在局域网加密传输，未唤醒不会发起 DSH 对话。关闭后等当前无线会话结束再生效。")
                    .font(.system(size:11))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal:false,vertical:true)
            }
            .font(.system(size:11))
        }
        .accessibilityIdentifier("r439-persistent-wake-setting")
        .onAppear(perform:refresh)
        .onReceive(Timer.publish(every:10,on:.main,in:.common).autoconnect()) { _ in
            refresh()
        }
    }
}
